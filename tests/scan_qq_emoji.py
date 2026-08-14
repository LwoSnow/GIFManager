# Scan the QQ emoji folder: detect the real format behind .jpg names.
# 扫描 QQ 表情包目录：识别 .jpg 后缀下的真实格式（GIF/APNG/JPEG/MJPEG）。
import os
import sys

DIR = r"C:\TLWorkStation\GIFManager\Ori"


def sniff(path):
    with open(path, "rb") as f:
        head = f.read(64)
    if head.startswith(b"GIF8"):
        # count frames by image descriptors / 数图像描述符个数
        data = open(path, "rb").read()
        n = data.count(b"\x2c")  # rough frame count / 粗略帧数
        return f"GIF(帧~{max(n - 1, 1)})"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        data = open(path, "rb").read()
        if b"acTL" in data[:200] or b"acTL" in data:
            return "APNG(动画)"
        return "PNG(静态)"
    if head.startswith(b"\xff\xd8\xff"):
        # MJPEG: many JFIF/EXIF markers in sequence -> multiple SOI markers
        # MJPEG：含多个 SOI（FFD8）即视频帧序列
        data = open(path, "rb").read()
        n = data.count(b"\xff\xd8")
        if n > 1:
            return f"MJPEG(帧~{n})"
        return "JPEG(静态)"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        data = open(path, "rb").read()
        return "WebP(动画)" if b"ANIM" in data[:64] else "WebP(静态)"
    if head.startswith(b"BM"):
        return "BMP"
    return "未知:" + head[:8].hex()


from collections import Counter

counts = Counter()
examples = {}
files = [f for f in os.listdir(DIR) if f.lower().endswith(".jpg")]
for fn in sorted(files):
    kind = sniff(os.path.join(DIR, fn))
    counts[kind] += 1
    examples.setdefault(kind, []).append(fn)

for kind, n in counts.most_common():
    print(f"{n:5d}  {kind}")
    print(f"       例: {examples[kind][:5]}")
print("合计:", len(files))
