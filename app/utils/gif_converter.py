# GIF conversion utilities based on the bundled ffmpeg binary.
# 基于内置 ffmpeg 的 GIF 转换工具。
import logging
import os
import re
import shutil
import subprocess

log = logging.getLogger("GIFManager")

# One-time flag: Pillow-missing notice is logged only on the first
# dimension read, not on every call (avoids log spam during imports) /
# 一次性标记：Pillow 缺失提示只在首次尺寸读取时记录，避免导入期间刷屏
_PILLOW_MISSING_LOGGED = False


def _log_warn(msg, *args):
    # Log a warning without failing when the logger is not initialized yet
    # (e.g. tests import this module standalone). / 记录警告；logger 尚未
    # 初始化时（如测试单独导入本模块）不因此失败。
    try:
        log.warning(msg, *args)
    except Exception:
        pass

# Supported image formats that should be converted to gif on import /
# 导入时需要转换为 gif 的图片格式（尽量覆盖更多格式）
CONVERT_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".apng", ".avif", ".jfif", ".ico", ".ppm", ".pgm", ".pbm", ".pnm",
}

# Formats we import without conversion / 直接导入不转换的格式
KEEP_EXTS = {".gif"}

# Formats accepted for import at all (converted or kept as-is) /
# 所有可导入的格式（转换或原样保留）
IMPORT_EXTS = KEEP_EXTS | CONVERT_EXTS

# Max dimension (px) of a converted gif. Chat apps (QQ/WeChat) often fail to
# recognize a pasted file path as an image when the gif is huge (e.g. a
# 1920x1920 2MB single-frame gif falls back to a file attachment), while
# 300-400px stickers paste reliably. Conversion therefore downscales
# oversized images to fit within this box, keeping the aspect ratio.
# 转换出的 gif 最大边长（px）。聊天软件（QQ/微信）对超大 gif 的路径粘贴常
# 无法识别为图片（如 1920x1920、2MB 的单帧 gif 会退化为文件附件），而
# 300-400px 的表情包能可靠粘贴。转换时对超大图等比缩放到该范围内。
MAX_GIF_DIM = 512


def _root_dir():
    # Project root: two levels up from app/utils / 项目根目录：app/utils 上溯两级
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ffmpeg_path():
    # Locate the bundled ffmpeg binary (works for both .py source and
    # packaged exe layouts). / 定位内置 ffmpeg（.py 源码与打包 exe 布局都适用）
    candidates = [
        os.path.join(_root_dir(), "ffmpeg", "ffmpeg.exe"),
        os.path.join(_root_dir(), "ffmpeg.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def needs_conversion(path):
    # Return True when the file is a supported image but not a gif /
    # 文件是支持的图片但非 gif 时返回 True（需要转换）
    ext = os.path.splitext(path)[1].lower()
    return ext in CONVERT_EXTS


def needs_gif_conversion(path):
    # True when the file is not real GIF content. With "auto-convert to gif"
    # enabled on import, everything except genuine GIFs (static jpg/png,
    # animated webp/apng, MJPEG) is converted to gif; GIF content stored
    # under a mislabeled extension (e.g. .jpg) is copied as-is.
    # 非真实 GIF 内容即为 True。导入勾选"自动转换为 GIF"时，除真实 GIF 外
    # 的一切（静态 jpg/png、动画 webp/apng、MJPEG）都转为 gif；伪装扩展名的
    # GIF 内容（如 .jpg）原样复制。
    return _content_kind(path) != "gif"


# Sniff the real image format by content, not by extension: QQ emoji packs
# routinely save GIFs and PNGs under .jpg names, and some .jpg files are
# actually MJPEG frame sequences. Returns "gif"/"png"/"jpeg"/"webp"/None.
# 按内容而非扩展名嗅探真实格式：QQ 表情包常把 GIF/PNG 存成 .jpg，
# 部分 .jpg 实为 MJPEG 帧序列。返回 "gif"/"png"/"jpeg"/"webp"/None。
def _content_kind(path):
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError as exc:
        _log_warn("content_kind: cannot read %s -> %s", path, exc)
        return None
    if head.startswith(b"GIF8"):
        return "gif"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head.startswith(b"\xff\xd8"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    # fallback to the extension for exotic containers / 未知内容回退扩展名
    ext = os.path.splitext(path)[1].lower()
    if ext in (".gif",):
        return "gif"
    if ext in (".png", ".apng"):
        return "png"
    if ext in (".jpg", ".jpeg", ".jfif"):
        return "jpeg"
    if ext == ".webp":
        return "webp"
    return None


# True when the image has more than one frame (animated webp/apng).
# Pillow would keep only the first frame, so ffmpeg is preferred for these.
# 图片多于 1 帧视为动画（动画 webp/apng）。Pillow 只保留首帧，故优先 ffmpeg。
def _is_animated_image(path):
    try:
        from PIL import Image
    except ImportError:
        _log_warn("is_animated_image: Pillow not installed, treat %s as static", path)
        return False
    try:
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception as exc:
        _log_warn("is_animated_image: cannot open %s -> %s", path, exc)
        return False


# True when a .jpg file is actually a MJPEG frame sequence. The SOI marker
# (FF D8) cannot appear inside JPEG entropy data, but EXIF thumbnails embed
# a whole JPEG inside an APP1 segment, so naive SOI counting is wrong.
# Parse the segment structure instead: skip APPn/COM segments, then look
# for a second SOI after the first SOS (entropy) scan.
# .jpg 文件实为 MJPEG 帧序列时为 True。SOI 标记（FF D8）不会出现在 JPEG
# 熵编码数据中，但 EXIF 缩略图会把整张 JPEG 嵌在 APP1 段内，因此简单地
# 统计 SOI 数量是错误的。改为解析段结构：跳过 APPn/COM 段，再在第一个
# SOS（熵数据）之后查找第二个 SOI。
def _is_mjpeg(path):
    try:
        with open(path, "rb") as f:
            data = f.read(1 << 20)  # the first 1 MB is enough for stickers / 前 1MB 足够
    except OSError as exc:
        _log_warn("is_mjpeg: cannot read %s -> %s", path, exc)
        return False
    n = len(data)
    i = 2  # skip the initial SOI / 跳过起始 SOI
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m == 0xD9:  # EOI / 图像结束
            return False
        if m == 0xDA:  # SOS: entropy-coded scan follows / SOS：其后为熵数据
            seg_len = (data[i + 2] << 8) | data[i + 3]
            sos_end = i + 2 + seg_len
            return data.find(b"\xff\xd8", sos_end) >= 0
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            i += 2  # standalone markers / 独立标记
            continue
        seg_len = (data[i + 2] << 8) | data[i + 3]
        if seg_len < 2:
            return False
        i += 2 + seg_len  # skip the segment (APPn/COM/DQT/DHT/SOF...)
    return False


# Convert an image to gif. The route is chosen by CONTENT, not extension:
#   gif   -> copy as-is (zero conversion cost, animation kept)
#   png/webp (animated) -> ffmpeg keeps the animation; Pillow first-frame fallback
#   png/webp (static)   -> Pillow (in-process, no ffmpeg spawn)
#   jpeg (MJPEG)        -> ffmpeg keeps the frame sequence
#   jpeg (static)       -> Pillow
# Returns True on success.
# 把图片转为 gif，按内容而非扩展名选择路径：
#   gif   -> 直接复制（零转换开销，动画保留）
#   png/webp（动画）-> ffmpeg 保留动画；Pillow 首帧回退
#   png/webp（静态）-> Pillow（进程内，不启动 ffmpeg）
#   jpeg（MJPEG）-> ffmpeg 保留帧序列
#   jpeg（静态）-> Pillow
# 成功返回 True。
def convert_to_gif(src, dst):
    kind = _content_kind(src)
    if kind == "gif":
        return _copy_as_gif(src, dst)
    if kind in ("png", "webp"):
        if _is_animated_image(src):
            if _ffmpeg_convert_to_gif(src, dst):
                return True
            return _pillow_convert_to_gif(src, dst)
        return _pillow_convert_to_gif(src, dst) or _ffmpeg_convert_to_gif(src, dst)
    if kind == "jpeg":
        if _is_mjpeg(src) and _ffmpeg_convert_to_gif(src, dst):
            return True
        return _pillow_convert_to_gif(src, dst) or _ffmpeg_convert_to_gif(src, dst)
    if _pillow_convert_to_gif(src, dst):
        return True
    return _ffmpeg_convert_to_gif(src, dst)


# Copy a GIF (possibly mislabeled as .jpg) verbatim to dst, upgrading a
# GIF87a header to GIF89a in the process. GIF89a is a superset of GIF87a,
# so rewriting only the 6-byte version header is lossless; WeChat/QQ treat
# GIF87a files as non-image attachments, so the upgrade makes them send as
# emoji. Pillow re-encoding is NOT used here (it quantizes large images and
# loses most pixels).
# 把 GIF（可能被命名为 .jpg）复制到 dst，并把 GIF87a 头升级为 GIF89a。
# GIF89a 是 GIF87a 的超集，只改写 6 字节版本头完全无损；微信/QQ 会把
# GIF87a 当作非图片附件，升级后可正常以表情包形式发送。这里不用 Pillow
# 重编码（它会量化大图并丢失大部分像素）。
def _copy_as_gif(src, dst):
    try:
        with open(src, "rb") as f:
            head = f.read(6)
            if head == b"GIF87a":
                # Header-only upgrade: GIF89a prefix + original payload /
                # 仅升级头：GIF89a 前缀 + 原始内容
                with open(dst, "wb") as out:
                    out.write(b"GIF89a")
                    shutil.copyfileobj(f, out)
            else:
                with open(dst, "wb") as out:
                    out.write(head)
                    shutil.copyfileobj(f, out)
    except OSError as exc:
        _log_warn("copy_as_gif: copy %s -> %s failed -> %s", src, dst, exc)
        return False
    ok = os.path.isfile(dst) and os.path.getsize(dst) > 0
    if not ok:
        _log_warn("copy_as_gif: output %s missing or empty (src=%s)", dst, src)
    return ok


# Convert with the bundled ffmpeg binary; on Windows suppress the black
# console window that otherwise flashes for every spawned process.
# Oversized inputs are downscaled to MAX_GIF_DIM to keep the output small
# enough for chat apps to recognize it as an image.
# 用内置 ffmpeg 转换；Windows 下抑制每次启动进程时闪出的黑色控制台窗口。
# 超大输入等比缩放到 MAX_GIF_DIM 内，保证聊天软件能识别为图片。
def _ffmpeg_convert_to_gif(src, dst):
    ff = ffmpeg_path()
    if not ff:
        _log_warn("ffmpeg_convert: ffmpeg binary not found (src=%s)", src)
        return False
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    cmd = [ff, "-y", "-i", src]
    dims = _image_dimensions(src)
    if dims and max(dims) > MAX_GIF_DIM:
        w, h = dims
        if w >= h:
            nw, nh = MAX_GIF_DIM, max(1, round(h * MAX_GIF_DIM / w))
        else:
            nw, nh = max(1, round(w * MAX_GIF_DIM / h)), MAX_GIF_DIM
        # Even sizes are required by some encoders / 部分编码器要求偶数边长
        nw, nh = nw - nw % 2, nh - nh % 2
        cmd += ["-vf", "scale={}:{}".format(max(2, nw), max(2, nh))]
    cmd += [dst]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            **kwargs,
        )
        if proc.returncode == 0 and os.path.isfile(dst) and \
                os.path.getsize(dst) > 0:
            return True
        _log_warn("ffmpeg_convert: rc=%s for %s -> %s (cmd=%s)",
                  proc.returncode, src, dst, cmd)
    except OSError as exc:
        _log_warn("ffmpeg_convert: OSError %s -> %s -> %s", src, dst, exc)
    except subprocess.TimeoutExpired:
        _log_warn("ffmpeg_convert: timeout for %s -> %s", src, dst)
    # Clean up the half-written output so a failed conversion does not leave
    # a temp-file fragment in %TEMP% / 清理半成品输出，转换失败不残留临时残片
    try:
        os.remove(dst)
    except OSError:
        pass
    return False


# Read the pixel dimensions of an image. Pillow first; when Pillow is not
# installed (e.g. the user runs the app with a bare Python without PIL), fall
# back to parsing the bundled ffmpeg's `-i` probe output. Returns (w, h) or
# None when unreadable.
# 读取图片像素尺寸。优先用 Pillow；Pillow 未安装（例如用户用没装 PIL 的
# 裸 Python 运行程序）时，回退解析内置 ffmpeg 的 `-i` 探测输出。返回
# (w, h)，读取失败返回 None。
def _image_dimensions(path):
    global _PILLOW_MISSING_LOGGED
    try:
        from PIL import Image
    except ImportError:
        if not _PILLOW_MISSING_LOGGED:
            _PILLOW_MISSING_LOGGED = True
            # One-time notice: Pillow is absent, ffmpeg probing is used for
            # every dimension read (informational, not an error) / 一次性
            # 提示：未安装 Pillow，尺寸读取改用 ffmpeg 探测（信息性，非错误）
            _log_warn("image_dimensions: Pillow not installed, use ffmpeg probe "
                      "for all dimension reads")
    else:
        try:
            with Image.open(path) as im:
                return im.size
        except Exception as exc:
            _log_warn("image_dimensions: Pillow cannot open %s -> %s, try ffmpeg", path, exc)
    # ffmpeg fallback: probe the stream and parse "WxH" from its output /
    # ffmpeg 兜底：探测流并从输出中解析 "WxH"
    ff = ffmpeg_path()
    if not ff:
        _log_warn("image_dimensions: ffmpeg not found, cannot probe %s", path)
        return None
    try:
        proc = subprocess.run(
            [ff, "-i", path, "-f", "null", "-"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        text = proc.stderr.decode("utf-8", "replace")
    except OSError as exc:
        _log_warn("image_dimensions: ffmpeg probe OSError for %s -> %s", path, exc)
        return None
    except subprocess.TimeoutExpired:
        _log_warn("image_dimensions: ffmpeg probe timeout for %s", path)
        return None
    m = re.search(r"(\d{2,5})x(\d{2,5})", text)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    _log_warn("image_dimensions: no WxH in ffmpeg probe output for %s", path)
    return None


# Downscale a gif to fit within MAX_GIF_DIM and write it to dst, keeping the
# aspect ratio. Used by the clipboard path so legacy oversized gifs in the
# library also paste as pictures instead of file attachments. Animation is
# preserved. Pillow is used when available (per-frame save_all); without
# Pillow the bundled ffmpeg scales the whole animation in one pass. Returns
# True when a downscaled copy was written, False when src is already small
# enough (or cannot be read) — in that case dst is left untouched.
# 把 gif 等比缩放到 MAX_GIF_DIM 内并写入 dst。用于发送路径：库里遗留的
# 超大 gif 也能粘贴为图片而非文件附件。动画保留。有 Pillow 时逐帧
# save_all；没有 Pillow 时用内置 ffmpeg 一次缩放整段动画。返回 True 表示
# 已写入缩小版；src 本就足够小（或读取失败）时返回 False，dst 不动。
def downscale_gif_if_needed(src, dst):
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        # No Pillow -> ffmpeg scale (keeps animation, shrinks only) /
        # 无 Pillow → 用 ffmpeg 缩放（保留动画，只缩小不放大）
        _log_warn("downscale: Pillow not installed for %s, use ffmpeg scale", src)
        return _ffmpeg_scale(src, dst, MAX_GIF_DIM)
    try:
        with Image.open(src) as im:
            if max(im.size) <= MAX_GIF_DIM:
                return False
            frames = []
            for frame in ImageSequence.Iterator(im):
                f = frame.copy()
                if f.mode not in ("P", "L", "RGB", "RGBA"):
                    f = f.convert("RGB")
                f.thumbnail((MAX_GIF_DIM, MAX_GIF_DIM))
                frames.append(f)
            if len(frames) == 1:
                frames[0].save(dst, "GIF", optimize=True)
            else:
                # Keep timing/loop count from the source / 保留源时长与循环次数
                duration = im.info.get("duration")
                loop = im.info.get("loop", 0)
                save_kw = {"save_all": True, "append_images": frames[1:],
                           "loop": loop}
                if isinstance(duration, (list, tuple)):
                    save_kw["duration"] = list(duration)
                elif duration:
                    save_kw["duration"] = int(duration)
                frames[0].save(dst, "GIF", **save_kw)
    except Exception as exc:
        _log_warn("downscale: Pillow downscale failed for %s -> %s (%s)",
                  src, dst, exc)
        return False
    ok = os.path.isfile(dst) and os.path.getsize(dst) > 0
    if not ok:
        _log_warn("downscale: output %s missing or empty (src=%s)", dst, src)
    return ok


# Scale an image/gif with the bundled ffmpeg to fit within max_dim (aspect
# ratio kept, never upscales). Returns True on success; a half-written dst
# is removed on failure. / 用内置 ffmpeg 把图片/gif 等比缩放到 max_dim 内
# （保持比例，不放大）。成功返回 True；失败时清理半成品 dst。
def _ffmpeg_scale(src, dst, max_dim):
    ff = ffmpeg_path()
    if not ff:
        _log_warn("ffmpeg_scale: ffmpeg binary not found (src=%s)", src)
        return False
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            [ff, "-y", "-i", src,
             "-vf", "scale={}:{}:force_original_aspect_ratio=decrease".format(
                 max_dim, max_dim),
             dst],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            **kwargs,
        )
        if proc.returncode == 0 and os.path.isfile(dst) and \
                os.path.getsize(dst) > 0:
            return True
        _log_warn("ffmpeg_scale: rc=%s for %s -> %s (max=%s)",
                  proc.returncode, src, dst, max_dim)
    except OSError as exc:
        _log_warn("ffmpeg_scale: OSError %s -> %s -> %s", src, dst, exc)
    except subprocess.TimeoutExpired:
        _log_warn("ffmpeg_scale: timeout for %s -> %s", src, dst)
    try:
        os.remove(dst)
    except OSError:
        pass
    return False


# Convert with Pillow: load the image and re-save as a single-frame gif.
# Oversized images are downscaled to MAX_GIF_DIM (aspect ratio kept) so the
# resulting gif stays small enough for chat apps to paste it as a picture.
# Animated webp/apng fall back to their first frame.
# 用 Pillow 转换：加载图片并以单帧 gif 重新保存。超大图等比缩放到
# MAX_GIF_DIM 内（保持比例），保证聊天软件能粘贴为图片。
# 动画 webp/apng 只取第一帧。
def _pillow_convert_to_gif(src, dst):
    try:
        from PIL import Image
    except ImportError:
        _log_warn("pillow_convert: Pillow not installed for %s", src)
        return False
    try:
        with Image.open(src) as im:
            im.load()
            if im.mode not in ("P", "L", "RGB", "RGBA"):
                im = im.convert("RGB")
            # Downscale oversized images (thumbnail never upscales) /
            # 超大图等比缩小（thumbnail 不会放大）
            im.thumbnail((MAX_GIF_DIM, MAX_GIF_DIM))
            im.save(dst, "GIF", optimize=True)
    except Exception as exc:
        _log_warn("pillow_convert: failed for %s -> %s (%s)", src, dst, exc)
        return False
    ok = os.path.isfile(dst) and os.path.getsize(dst) > 0
    if not ok:
        _log_warn("pillow_convert: output %s missing or empty (src=%s)", dst, src)
    return ok
