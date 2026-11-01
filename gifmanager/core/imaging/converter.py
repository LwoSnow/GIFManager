"""Image-to-GIF conversion with ffmpeg and Pillow back ends.

The route is chosen by CONTENT, not by extension, because that is the only way
to handle real QQ emoji packs:

    gif                -> copy as-is (zero cost, animation kept)
    animated png/webp  -> ffmpeg (keeps every frame); Pillow is the fallback
    static png/webp    -> Pillow (in-process, no process spawn)
    jpeg (MJPEG)       -> ffmpeg (keeps the frame sequence)
    jpeg (static)      -> Pillow

ffmpeg is optional and user-configurable, so every entry point degrades to
Pillow and never raises for a missing binary.

基于 ffmpeg 与 Pillow 的图片转 GIF。

路径按"内容"而非扩展名选择，这是处理真实 QQ 表情包的唯一办法：

    gif                -> 直接复制（零开销，保留动画）
    动画 png/webp      -> ffmpeg（保留全部帧）；Pillow 兜底
    静态 png/webp      -> Pillow（进程内，不启动子进程）
    jpeg（MJPEG）      -> ffmpeg（保留帧序列）
    jpeg（静态）       -> Pillow

ffmpeg 是可选且用户可配置的，因此每个入口都会降级到 Pillow，且不会因缺少二进制
而抛异常。
"""
import logging
import os
import shutil
import subprocess

from gifmanager.core import fileops as file_ops
from gifmanager.core.imaging import signatures

log = logging.getLogger("GIFManager")

# One-time flag so the "Pillow missing" notice is logged on the first dimension
# read rather than on every call (a 400-file import would otherwise emit 400
# identical lines). / 一次性标记：Pillow 缺失提示只在首次尺寸读取时记录，
# 避免导入期间刷屏（否则 400 个文件会打印 400 行相同内容）。
_pillow_missing_logged = False


def _warn(message, *args):
    # Log a warning without failing when the logger is not configured yet
    # (tests import this module standalone). / 记录警告；日志器尚未配置时
    #（测试单独导入本模块）不因此失败。
    try:
        log.warning(message, *args)
    except Exception:
        pass


class ProcessRunner:
    # Default subprocess policy: the standard library's own behaviour.
    #
    # Windows needs `CREATE_NO_WINDOW`, or a black console flashes for every
    # spawned ffmpeg. That is genuinely OS-specific, so it lives in
    # `gifmanager.platform.process`, which implements this same interface and is
    # injected by the backend at startup. Keeping a working default HERE means
    # the converter still runs — and is still testable — with no platform layer
    # at all, which is what lets `core` stay free of OS imports.
    # 默认子进程策略：标准库自身的行为。
    #
    # Windows 需要 `CREATE_NO_WINDOW`，否则每次启动 ffmpeg 都会闪出黑色控制台。这确实
    # 是系统专有的，因此位于 `gifmanager.platform.process`，它实现同一个接口并由后端在
    # 启动时注入。把可用默认实现放在"这里"，使转换器在没有平台层时仍能运行、也仍可
    # 测试——这正是让 `core` 不导入系统相关模块的前提。

    # File name suffixes tried for an executable, most specific first /
    # 尝试的可执行文件后缀，最具体的在前
    _SUFFIXES = ("{}.exe", "{}")

    # Sub-directories searched under each root / 在各根目录下搜索的子目录
    _SUBDIRS = ("ffmpeg", "bin", "")

    def find_executable(self, name, explicit=None):
        if explicit:
            explicit = os.path.abspath(explicit)
            if os.path.isfile(explicit):
                return explicit
            return None
        from gifmanager.core import paths

        for directory in (paths.resources_dir(), paths.project_root()):
            for sub in self._SUBDIRS:
                base = os.path.join(directory, sub) if sub else directory
                for suffix in self._SUFFIXES:
                    candidate = os.path.join(base, suffix.format(name))
                    if os.path.isfile(candidate):
                        return candidate
        return shutil.which(name)

    def run_capture(self, argv, timeout=30):
        return subprocess.run(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout)

    def run_quiet(self, argv, timeout=120):
        return subprocess.run(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout)

    def decode_output(self, data, preferred="utf-8"):
        # Decode captured bytes, replacing undecodable ones rather than raising.
        # Windows consoles frequently encode as the OEM code page, which cannot
        # represent every adapter name.
        # 解码捕获到的字节，无法解码时替换而非抛异常。Windows 控制台常以 OEM 代码页
        # 编码，无法表示所有显卡名称。
        if not data:
            return ""
        fallbacks = (preferred, "utf-8")
        if os.name == "nt":
            fallbacks = fallbacks + ("mbcs",)
        for encoding in fallbacks:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", "replace")


class MediaConverter:
    # Convert images to GIF, locate ffmpeg, and read image dimensions.
    #
    # ffmpeg settings are instance state rather than module globals, so two
    # profiles (or a test) can hold different configurations at the same time.
    # 把图片转为 GIF、定位 ffmpeg、读取图片尺寸。
    #
    # ffmpeg 配置是实例状态而非模块全局量，因此两套配置（或一个测试）可以同时
    # 持有不同设置。
    def __init__(self, ffmpeg_path=None, ffmpeg_enabled=True,
                 max_dim=signatures.MAX_GIF_DIM, process_runner=None):
        self._ffmpeg_path = ffmpeg_path or ""
        self._ffmpeg_enabled = bool(ffmpeg_enabled)
        self._max_dim = int(max_dim)
        self._process = process_runner or ProcessRunner()

    # ---- configuration / 配置 ------------------------------------------

    def configure(self, path=None, enabled=None):
        # Update the ffmpeg configuration; None leaves a value unchanged.
        # 更新 ffmpeg 配置；传 None 表示不改动该项。
        if enabled is not None:
            self._ffmpeg_enabled = bool(enabled)
        if path is not None:
            self._ffmpeg_path = str(path or "")

    @property
    def ffmpeg_enabled(self):
        return self._ffmpeg_enabled

    @property
    def configured_ffmpeg_path(self):
        return self._ffmpeg_path

    @property
    def max_dim(self):
        return self._max_dim

    @property
    def import_extensions(self):
        return signatures.IMPORT_EXTS

    def resolve_ffmpeg(self):
        # Effective ffmpeg binary: the user's choice wins, otherwise the bundled
        # copy is auto-detected. None when disabled or absent, which makes every
        # caller fall back to Pillow.
        # 生效的 ffmpeg 二进制：用户指定优先，否则自动检测内置副本。关闭或缺失时
        # 返回 None，使各调用方回退到 Pillow。
        if not self._ffmpeg_enabled:
            return None
        explicit = self._ffmpeg_path if self._ffmpeg_path else None
        if explicit and os.path.isfile(explicit):
            return explicit
        return self._process.find_executable("ffmpeg")

    def probe_ffmpeg(self, path=None):
        # Run `ffmpeg -version` and return (ok, first_line_or_error). Backs the
        # settings dialog's "test ffmpeg" button.
        # 运行 `ffmpeg -version`，返回 (是否成功, 首行或错误信息)。供设置界面的
        # "测试 ffmpeg" 按钮使用。
        exe = path or self.resolve_ffmpeg()
        if not exe:
            return False, "ffmpeg not found / 未找到 ffmpeg"
        if not os.path.isfile(exe):
            return False, f"not a file / 不是文件: {exe}"
        try:
            completed = self._process.run_capture([exe, "-version"], timeout=15)
        except (OSError, Exception) as exc:
            return False, str(exc)
        text = self._process.decode_output(completed.stdout).strip()
        if completed.returncode == 0 and text:
            return True, text.splitlines()[0]
        error = self._process.decode_output(completed.stderr).strip()
        return False, (error.splitlines()[0] if error
                       else f"exit code {completed.returncode}")

    # ---- format queries / 格式查询 --------------------------------------

    def content_kind(self, path):
        return signatures.content_kind(path)

    def needs_conversion(self, path):
        return signatures.needs_conversion(path)

    def needs_gif_conversion(self, path):
        return signatures.needs_gif_conversion(path)

    def image_dimensions(self, path):
        # Pillow first, then an ffmpeg probe. The one-time "Pillow missing"
        # notice is emitted here because this is the first call that suffers
        # from its absence.
        # 优先 Pillow，其次 ffmpeg 探测。Pillow 缺失的一次性提示在此发出，因为这是
        # 第一个受其缺失影响的调用。
        if not _pillow_available():
            _log_pillow_missing_once()
        return signatures.image_dimensions(path, probe=self._probe_dimensions)

    def _probe_dimensions(self, path):
        exe = self.resolve_ffmpeg()
        if not exe:
            _warn("image_dimensions: ffmpeg not found, cannot probe %s", path)
            return ""
        try:
            completed = self._process.run_capture(
                [exe, "-i", path, "-f", "null", "-"], timeout=30)
        except OSError as exc:
            _warn("image_dimensions: probe OSError for %s -> %s", path, exc)
            return ""
        except Exception as exc:
            _warn("image_dimensions: probe timeout for %s -> %s", path, exc)
            return ""
        return self._process.decode_output(completed.stderr)

    def is_oversized(self, path):
        return signatures.is_oversized(path, self._max_dim,
                                      probe=self._probe_dimensions)

    # ---- conversion / 转换 ---------------------------------------------

    def convert_to_gif(self, src, dst):
        # Convert any supported image to GIF. Returns True on success.
        # 把任意受支持的图片转为 GIF。成功返回 True。
        kind = signatures.content_kind(src)
        if kind == signatures.KIND_GIF:
            return self.copy_as_gif(src, dst)
        if kind in (signatures.KIND_PNG, signatures.KIND_WEBP):
            if signatures.is_animated_image(src):
                if self._ffmpeg_convert_to_gif(src, dst):
                    return True
                return self._pillow_convert_to_gif(src, dst)
            return (self._pillow_convert_to_gif(src, dst)
                    or self._ffmpeg_convert_to_gif(src, dst))
        if kind == signatures.KIND_JPEG:
            if signatures.is_mjpeg(src) and self._ffmpeg_convert_to_gif(src, dst):
                return True
            return (self._pillow_convert_to_gif(src, dst)
                    or self._ffmpeg_convert_to_gif(src, dst))
        if self._pillow_convert_to_gif(src, dst):
            return True
        return self._ffmpeg_convert_to_gif(src, dst)

    def copy_as_gif(self, src, dst):
        # Copy a GIF verbatim, upgrading a GIF87a header to GIF89a.
        # 原样复制 GIF，并把 GIF87a 头升级为 GIF89a。
        try:
            ok = file_ops.copy_upgrading_gif(src, dst)
        except OSError as exc:
            _warn("copy_as_gif: copy %s -> %s failed -> %s", src, dst, exc)
            return False
        if not ok:
            _warn("copy_as_gif: output %s missing or empty (src=%s)", dst, src)
        return ok

    def downscale_gif_if_needed(self, src, dst):
        # Write a downscaled copy of a GIF into `dst` when its longer side
        # exceeds `max_dim`, keeping the animation. Returns False when `src` is
        # already small enough (or unreadable), in which case `dst` is untouched.
        # 当 GIF 较长边超过 `max_dim` 时，把等比缩小的副本写入 `dst`，并保留动画。
        # `src` 本就足够小（或不可读）时返回 False，此时 `dst` 不动。
        try:
            from PIL import Image, ImageSequence
        except ImportError:
            _warn("downscale: Pillow not installed for %s, use ffmpeg scale", src)
            return self._ffmpeg_scale(src, dst, self._max_dim)
        try:
            with Image.open(src) as image:
                if max(image.size) <= self._max_dim:
                    return False
                frames = []
                for frame in ImageSequence.Iterator(image):
                    copy = frame.copy()
                    if copy.mode not in ("P", "L", "RGB", "RGBA"):
                        copy = copy.convert("RGB")
                    copy.thumbnail((self._max_dim, self._max_dim))
                    frames.append(copy)
                if len(frames) == 1:
                    frames[0].save(dst, "GIF", optimize=True)
                else:
                    duration = image.info.get("duration")
                    loop = image.info.get("loop", 0)
                    save_kwargs = {
                        "save_all": True,
                        "append_images": frames[1:],
                        "loop": loop,
                    }
                    if isinstance(duration, (list, tuple)):
                        save_kwargs["duration"] = list(duration)
                    elif duration:
                        save_kwargs["duration"] = int(duration)
                    frames[0].save(dst, "GIF", **save_kwargs)
        except Exception as exc:
            _warn("downscale: Pillow downscale failed for %s -> %s (%s)",
                  src, dst, exc)
            return False
        ok = file_ops.is_nonempty_file(dst)
        if not ok:
            _warn("downscale: output %s missing or empty (src=%s)", dst, src)
        return ok

    # ---- ffmpeg back end / ffmpeg 后端 ---------------------------------

    def _ffmpeg_scale(self, src, dst, max_dim):
        exe = self.resolve_ffmpeg()
        if not exe:
            _warn("ffmpeg_scale: ffmpeg binary not found (src=%s)", src)
            return False
        argv = [
            exe, "-y", "-i", src,
            "-vf", f"scale={max_dim}:{max_dim}:force_original_aspect_ratio=decrease",
            dst,
        ]
        ok = self._run_ffmpeg(argv, src, dst)
        if not ok:
            _warn("ffmpeg_scale: failed for %s -> %s (max=%s)", src, dst, max_dim)
        return ok

    def _ffmpeg_convert_to_gif(self, src, dst):
        exe = self.resolve_ffmpeg()
        if not exe:
            # ffmpeg switched off (or missing) is an expected state, not a
            # failure: do not log a warning per file, and do not leave a
            # half-written output behind.
            # ffmpeg 被关闭（或缺失）属预期状态而非失败：不要每个文件都记一条警告，
            # 也不要留下半成品输出。
            if self._ffmpeg_enabled:
                _warn("ffmpeg_convert: ffmpeg binary not found (src=%s)", src)
            return False
        argv = [exe, "-y", "-i", src]
        dimensions = self.image_dimensions(src)
        if dimensions and max(dimensions) > self._max_dim:
            width, height = dimensions
            if width >= height:
                new_w = self._max_dim
                new_h = max(1, round(height * self._max_dim / width))
            else:
                new_w = max(1, round(width * self._max_dim / height))
                new_h = self._max_dim
            # Some encoders require even side lengths / 部分编码器要求偶数边长
            new_w -= new_w % 2
            new_h -= new_h % 2
            argv += ["-vf", f"scale={max(2, new_w)}:{max(2, new_h)}"]
        argv.append(dst)
        ok = self._run_ffmpeg(argv, src, dst)
        if not ok:
            _warn("ffmpeg_convert: failed for %s -> %s", src, dst)
        return ok

    def _run_ffmpeg(self, argv, src, dst):
        try:
            completed = self._process.run_quiet(argv, timeout=120)
        except OSError as exc:
            _warn("ffmpeg: OSError %s -> %s -> %s", src, dst, exc)
        except Exception as exc:
            _warn("ffmpeg: timeout for %s -> %s (%s)", src, dst, exc)
        else:
            if completed.returncode == 0 and file_ops.is_nonempty_file(dst):
                return True
        # Clean up the half-written output so a failed conversion leaves no
        # fragment behind. / 清理半成品输出，转换失败不残留碎片。
        file_ops.remove_quietly(dst)
        return False

    # ---- Pillow back end / Pillow 后端 ---------------------------------

    def _pillow_convert_to_gif(self, src, dst):
        # Convert with Pillow, keeping ALL frames of an animated source.
        #
        # Saving a single frame silently turned every animated sticker into a
        # still image when ffmpeg was disabled — the user saw "the animation
        # just vanished" with no error.
        # 用 Pillow 转换，并保留动画源的全部帧。
        #
        # 只保存单帧会在停用 ffmpeg 时静默把每个动态表情变成静态图——用户看到的
        # 是"动画直接没了"且没有任何报错。
        try:
            from PIL import Image
        except ImportError:
            _warn("pillow_convert: Pillow not installed for %s", src)
            return False
        try:
            with Image.open(src) as image:
                try:
                    frame_count = max(1, int(getattr(image, "n_frames", 1)))
                except Exception:
                    frame_count = 1
                if frame_count > 1:
                    self._save_animated(image, dst, frame_count)
                else:
                    image.load()
                    if image.mode not in ("P", "L", "RGB", "RGBA"):
                        image = image.convert("RGB")
                    # thumbnail never upscales / thumbnail 不会放大
                    image.thumbnail((self._max_dim, self._max_dim))
                    image.save(dst, "GIF", optimize=True)
        except Exception as exc:
            _warn("pillow_convert: failed for %s -> %s (%s)", src, dst, exc)
            return False
        ok = file_ops.is_nonempty_file(dst)
        if not ok:
            _warn("pillow_convert: output %s missing or empty (src=%s)", dst, src)
        return ok

    def _save_animated(self, image, dst, frame_count):
        from PIL import Image

        frames = []
        durations = []
        for index in range(frame_count):
            image.seek(index)
            frame = image.convert("RGBA")
            frame.thumbnail((self._max_dim, self._max_dim))
            # GIF is palette based: quantise each frame separately /
            # GIF 基于调色板：逐帧量化
            frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE))
            durations.append(int(image.info.get("duration", 100) or 100))
        frames[0].save(
            dst, "GIF", save_all=True, append_images=frames[1:],
            duration=durations, loop=int(image.info.get("loop", 0) or 0),
            optimize=True, disposal=2,
        )


def _pillow_available():
    try:
        import PIL.Image  # noqa: F401 - availability probe / 可用性探测
    except ImportError:
        return False
    return True


def _log_pillow_missing_once():
    global _pillow_missing_logged
    if _pillow_missing_logged:
        return
    _pillow_missing_logged = True
    _warn("Pillow not installed, ffmpeg probing is used for all dimension reads")


__all__ = ["MediaConverter"]
