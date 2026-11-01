"""Image handling: format detection, dimension probing and GIF conversion.

图片处理：格式检测、尺寸探测与 GIF 转换。
"""
from gifmanager.core.imaging.converter import MediaConverter, ProcessRunner
from gifmanager.core.imaging.signatures import (
    CONVERT_EXTS,
    IMPORT_EXTS,
    KEEP_EXTS,
    KIND_GIF,
    KIND_JPEG,
    KIND_PNG,
    KIND_WEBP,
    MAX_GIF_DIM,
    content_kind,
    extension_of,
    has_gif_signature,
    image_dimensions,
    is_animated_image,
    is_importable,
    is_mjpeg,
    is_oversized,
    needs_conversion,
    needs_gif_conversion,
)

__all__ = [
    "CONVERT_EXTS",
    "IMPORT_EXTS",
    "KEEP_EXTS",
    "KIND_GIF",
    "KIND_JPEG",
    "KIND_PNG",
    "KIND_WEBP",
    "MAX_GIF_DIM",
    "MediaConverter",
    "ProcessRunner",
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
