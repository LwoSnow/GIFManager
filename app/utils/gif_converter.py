# GIF conversion utilities based on the bundled ffmpeg binary.
# 基于内置 ffmpeg 的 GIF 转换工具。
import os
import shutil
import subprocess

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


# Sniff the real image format by content, not by extension: QQ emoji packs
# routinely save GIFs and PNGs under .jpg names, and some .jpg files are
# actually MJPEG frame sequences. Returns "gif"/"png"/"jpeg"/"webp"/None.
# 按内容而非扩展名嗅探真实格式：QQ 表情包常把 GIF/PNG 存成 .jpg，
# 部分 .jpg 实为 MJPEG 帧序列。返回 "gif"/"png"/"jpeg"/"webp"/None。
def _content_kind(path):
    try:
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError:
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
        with Image.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception:
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
    except OSError:
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


# Copy a GIF (possibly mislabeled as .jpg) verbatim to dst.
# 把 GIF（可能被命名为 .jpg）原样复制到 dst。
def _copy_as_gif(src, dst):
    try:
        shutil.copy2(src, dst)
    except OSError:
        return False
    return os.path.isfile(dst) and os.path.getsize(dst) > 0


# Convert with the bundled ffmpeg binary; on Windows suppress the black
# console window that otherwise flashes for every spawned process.
# 用内置 ffmpeg 转换；Windows 下抑制每次启动进程时闪出的黑色控制台窗口。
def _ffmpeg_convert_to_gif(src, dst):
    ff = ffmpeg_path()
    if not ff:
        return False
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            [ff, "-y", "-i", src, dst],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            **kwargs,
        )
        if proc.returncode == 0 and os.path.isfile(dst) and \
                os.path.getsize(dst) > 0:
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Clean up the half-written output so a failed conversion does not leave
    # a temp-file fragment in %TEMP% / 清理半成品输出，转换失败不残留临时残片
    try:
        os.remove(dst)
    except OSError:
        pass
    return False


# Convert with Pillow: load the image and re-save as a single-frame gif,
# keeping dimensions. Animated webp/apng fall back to their first frame.
# 用 Pillow 转换：加载图片并以单帧 gif 重新保存，保持尺寸不变。
# 动画 webp/apng 只取第一帧。
def _pillow_convert_to_gif(src, dst):
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            im.load()
            if im.mode not in ("P", "L", "RGB", "RGBA"):
                im = im.convert("RGB")
            im.save(dst, "GIF", optimize=True)
    except Exception:
        return False
    return os.path.isfile(dst) and os.path.getsize(dst) > 0
