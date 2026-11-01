"""Image format detection and dimension probing.

Format is decided by CONTENT, not by extension. QQ emoji packs routinely save
GIFs and PNGs under `.jpg` names, and some `.jpg` files are really MJPEG frame
sequences; trusting the extension imports the wrong thing or silently stores a
static frame where an animation was expected.

图片格式检测与尺寸探测。

格式按"内容"而非扩展名判断。QQ 表情包常把 GIF/PNG 存成 `.jpg`，部分 `.jpg` 实为
MJPEG 帧序列；相信扩展名会导入错误的内容，或在期望动画时静默存入一帧静态图。
"""
import logging
import os

log = logging.getLogger("GIFManager")

# Formats converted to GIF on import / 导入时转换为 GIF 的格式
CONVERT_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
    ".apng", ".avif", ".jfif", ".ico", ".ppm", ".pgm", ".pbm", ".pnm",
})

# Formats imported without conversion / 直接导入、不做转换的格式
KEEP_EXTS = frozenset({".gif"})

# Every format accepted for import / 所有可导入的格式
IMPORT_EXTS = KEEP_EXTS | CONVERT_EXTS

# Longest side of a stored GIF. Chat applications often fail to recognise a
# pasted file path as an image when the GIF is huge (a 1920x1920 2 MB
# single-frame GIF degrades to a file attachment), while 300-400 px stickers
# paste reliably, so oversized images are downscaled into this box.
# 存储 GIF 的最长边。GIF 过大时聊天软件常无法把粘贴的文件路径识别为图片
# （1920x1920、2MB 的单帧 GIF 会退化为文件附件），而 300-400px 的表情包能可靠
# 粘贴，因此超大图会等比缩放进这个范围。
MAX_GIF_DIM = 512

# Content kinds / 内容类型
KIND_GIF = "gif"
KIND_PNG = "png"
KIND_JPEG = "jpeg"
KIND_WEBP = "webp"

# Bytes inspected to identify a format / 用于识别格式而读取的字节数
_SNIFF_BYTES = 12

# Bytes inspected when looking for an MJPEG frame sequence. The first megabyte
# is enough for a sticker. / 查找 MJPEG 帧序列时读取的字节数。对表情包而言前
# 1MB 足够。
_MJPEG_BYTES = 1 << 20

_EXT_KINDS = {
    ".gif": KIND_GIF,
    ".png": KIND_PNG,
    ".apng": KIND_PNG,
    ".jpg": KIND_JPEG,
    ".jpeg": KIND_JPEG,
    ".jfif": KIND_JPEG,
    ".webp": KIND_WEBP,
}


def extension_of(path):
    return os.path.splitext(path)[1].lower()


def is_importable(path):
    # True when the extension is one the importer accepts /
    # 扩展名属于导入器接受的类型时为 True
    return extension_of(path) in IMPORT_EXTS


def needs_conversion(path):
    # True when the file must be re-encoded before storing /
    # 入库前必须重新编码时为 True
    return extension_of(path) in CONVERT_EXTS


def content_kind(path):
    # Real format sniffed from the leading bytes, with the extension as a
    # fallback for containers without a recognisable signature. Returns one of
    # the KIND_* constants, or None.
    # 从起始字节嗅探出的真实格式；无可识别签名的容器回退到扩展名。返回 KIND_*
    # 之一或 None。
    try:
        with open(path, "rb") as handle:
            head = handle.read(_SNIFF_BYTES)
    except OSError as exc:
        log.warning("content_kind: cannot read %s -> %s", path, exc)
        return None
    if head.startswith(b"GIF8"):
        return KIND_GIF
    if head.startswith(b"\x89PNG"):
        return KIND_PNG
    if head.startswith(b"\xff\xd8"):
        return KIND_JPEG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return KIND_WEBP
    return _EXT_KINDS.get(extension_of(path))


def needs_gif_conversion(path):
    # True when the file is not genuine GIF content. With "auto-convert" on,
    # everything except a real GIF (static jpg/png, animated webp/apng, MJPEG)
    # is converted; GIF content under a mislabelled extension is copied as-is.
    # 非真实 GIF 内容时为 True。开启"自动转换"时，除真实 GIF 外的一切（静态
    # jpg/png、动画 webp/apng、MJPEG）都转换；伪装扩展名的 GIF 内容原样复制。
    return content_kind(path) != KIND_GIF


def has_gif_signature(path):
    # Cheap magic-number test used on the send path, where decoding the whole
    # file only to learn its type would be wasteful.
    # 发送路径使用的廉价魔数判断：那里为了解类型而解码整个文件是浪费。
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == b"GIF8"
    except OSError as exc:
        log.warning("has_gif_signature: cannot read %s -> %s", path, exc)
        return False


def is_animated_image(path):
    # True when an image holds more than one frame (animated webp/apng).
    # Pillow keeps only the first frame, so these must go through ffmpeg.
    # Pillow is optional: without it the caller falls back to the static path
    # rather than failing the import.
    # 图片多于 1 帧（动画 webp/apng）时为 True。Pillow 只保留首帧，因此这些必须
    # 交给 ffmpeg。Pillow 是可选依赖：缺失时调用方回退到静态路径而不是导入失败。
    try:
        from PIL import Image
    except ImportError:
        log.warning("is_animated_image: Pillow not installed, treat %s as static", path)
        return False
    try:
        with Image.open(path) as image:
            return int(getattr(image, "n_frames", 1)) > 1
    except Exception as exc:
        log.warning("is_animated_image: cannot open %s -> %s", path, exc)
        return False


def is_mjpeg(path):
    # True when a `.jpg` file is really an MJPEG frame sequence.
    #
    # The SOI marker (FF D8) cannot occur inside JPEG entropy data, but an EXIF
    # thumbnail embeds a whole JPEG inside an APP1 segment, so simply counting
    # SOI markers is wrong. Parse the segment structure instead: skip APPn/COM
    # segments, then look for a second SOI after the first SOS (entropy) scan.
    # `.jpg` 文件实为 MJPEG 帧序列时为 True。
    #
    # SOI 标记（FF D8）不会出现在 JPEG 熵编码数据中，但 EXIF 缩略图会把整张 JPEG
    # 嵌在 APP1 段内，因此简单统计 SOI 数量是错误的。改为解析段结构：跳过
    # APPn/COM 段，再在第一个 SOS（熵数据）之后查找第二个 SOI。
    try:
        with open(path, "rb") as handle:
            data = handle.read(_MJPEG_BYTES)
    except OSError as exc:
        log.warning("is_mjpeg: cannot read %s -> %s", path, exc)
        return False
    total = len(data)
    index = 2  # skip the initial SOI / 跳过起始 SOI
    while index + 4 <= total:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xD9:  # EOI / 图像结束
            return False
        if marker == 0xDA:  # SOS: entropy-coded scan follows / SOS：其后为熵数据
            segment_length = (data[index + 2] << 8) | data[index + 3]
            scan_end = index + 2 + segment_length
            return data.find(b"\xff\xd8", scan_end) >= 0
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2  # standalone markers / 独立标记
            continue
        segment_length = (data[index + 2] << 8) | data[index + 3]
        if segment_length < 2:
            return False
        index += 2 + segment_length  # skip APPn/COM/DQT/DHT/SOF... / 跳过该段
    return False


def image_dimensions(path, probe=None):
    # Pixel dimensions of an image as (width, height), or None.
    #
    # Pillow is tried first because it is exact and in-process. `probe` is an
    # optional callable `(path) -> text` used as a fallback when Pillow is
    # absent (a bare Python without PIL) — the caller supplies one that shells
    # out to ffmpeg, so this module keeps no dependency on a subprocess policy.
    #
    # 图片的像素尺寸 (宽, 高)，读取失败返回 None。
    #
    # 优先用 Pillow，因其精确且在进程内。`probe` 是可选的 `(path) -> 文本`
    # 回调，在缺少 Pillow（裸 Python 未装 PIL）时兜底——由调用方提供一个调用
    # ffmpeg 的实现，使本模块不涉及任何子进程策略。
    dimensions = _dimensions_from_pillow(path)
    if dimensions is not None:
        return dimensions
    if probe is None:
        return None
    return _dimensions_from_probe(path, probe)


def _dimensions_from_pillow(path):
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            return tuple(image.size)
    except Exception as exc:
        log.warning(
            "image_dimensions: Pillow cannot open %s -> %s, try probe", path, exc)
        return None


def _dimensions_from_probe(path, probe):
    import re

    try:
        text = probe(path) or ""
    except Exception as exc:
        log.warning("image_dimensions: probe failed for %s -> %s", path, exc)
        return None
    match = re.search(r"(\d{2,5})x(\d{2,5})", text)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    log.warning("image_dimensions: no WxH in probe output for %s", path)
    return None


def is_oversized(path, max_dim=MAX_GIF_DIM, probe=None):
    # True when an image exceeds `max_dim` on its longer side. An unreadable
    # file reports False, so a probe failure never triggers a downscale that
    # would then fail again.
    # 图片较长边超过 `max_dim` 时为 True。不可读的文件返回 False，使探测失败不会
    # 触发一次同样会失败的降采样。
    dimensions = image_dimensions(path, probe=probe)
    if not dimensions:
        return False
    return max(dimensions) > max_dim


__all__ = [
    "CONVERT_EXTS",
    "IMPORT_EXTS",
    "KEEP_EXTS",
    "KIND_GIF",
    "KIND_JPEG",
    "KIND_PNG",
    "KIND_WEBP",
    "MAX_GIF_DIM",
    "content_kind",
    "extension_of",
    "has_gif_signature",
    "image_dimensions",
    "is_animated_image",
    "is_importable",
    "is_mjpeg",
    "is_oversized",
    "needs_conversion",
    "needs_gif_conversion",
]
