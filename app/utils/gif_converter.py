# GIF conversion utilities based on the bundled ffmpeg binary.
# 基于内置 ffmpeg 的 GIF 转换工具。
import os
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


# Convert an image to gif. Prefers the bundled ffmpeg (supports animated
# webp/apng); falls back to Pillow, which always works and keeps the
# original size and aspect ratio. Returns True on success.
# 把图片转为 gif：优先用内置 ffmpeg（支持动画 webp/apng）；回退用 Pillow，
# 保持原始尺寸与比例不变。成功返回 True。
def convert_to_gif(src, dst):
    ff = ffmpeg_path()
    if ff:
        try:
            proc = subprocess.run(
                [ff, "-y", "-i", src, dst],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
            if proc.returncode == 0 and os.path.isfile(dst) and \
                    os.path.getsize(dst) > 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _pillow_convert_to_gif(src, dst)


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


# Convert a list of image paths to gif. For each source file a gif is
# written next to it (same basename, .gif extension). Returns
# (converted_paths, failed_paths) where converted_paths maps original path
# -> new gif path; failed files keep their original format.
# 批量把图片转成 gif：每个源文件旁生成同名 .gif。返回
# (converted, failed)，converted 是 {原路径: 新gif路径}，失败的文件保持原格式。
def convert_files(paths, progress_cb=None):
    converted = {}
    failed = []
    total = len(paths)
    for i, p in enumerate(paths):
        if progress_cb is not None:
            progress_cb(i, total, p)
        if not needs_conversion(p):
            continue
        dst = os.path.splitext(p)[0] + ".gif"
        if convert_to_gif(p, dst):
            converted[p] = dst
        else:
            failed.append(p)
    if progress_cb is not None and total:
        progress_cb(total, total, "")
    return converted, failed
