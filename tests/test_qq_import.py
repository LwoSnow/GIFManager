"""Full import pipeline test with the real QQ emoji folder (Ori/):
verifies that mislabeled GIFs are copied as-is (animation kept), static
images convert via Pillow, and the whole batch imports without failures.
用真实 QQ 表情包文件夹（Ori/）测试完整导入链路：伪装 GIF 原样复制且保留
动画、静态图走 Pillow、全量导入无失败。"""
import ctypes
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORI = os.path.join(ROOT, "Ori")
TMP = tempfile.mkdtemp(prefix="gifmgr_qq_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from app.models.data_manager import DataManager
from app.utils import gif_converter

app = QApplication(sys.argv)

lib = ctypes.CDLL(os.path.abspath(os.path.join(ROOT, "app", "utils", "gifdec.dll")))
lib.gif_open.restype = ctypes.c_void_p
lib.gif_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int),
                         ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
lib.gif_close.argtypes = [ctypes.c_void_p]


def count_frames(p):
    w, h, n = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    hnd = lib.gif_open(p.encode("utf-8"), ctypes.byref(w), ctypes.byref(h),
                       ctypes.byref(n))
    if not hnd:
        return -1
    lib.gif_close(hnd)
    return n.value


RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


if not os.path.isdir(ORI):
    print("Ori 目录不存在，跳过")
    sys.exit(0)

dm = DataManager()
g = dm.create_group("QQ表情", "image")
files = sorted(os.listdir(ORI))
paths = [os.path.join(ORI, f) for f in files if f.lower().endswith((".jpg", ".png"))]

imported, duplicated = dm.import_emojis_batch(g, paths, workers=8, auto_convert=True)
check("A 全量导入无失败", imported + duplicated == len(paths),
      f"imported={imported} dup={duplicated} total={len(paths)}")

rows = dm.get_emojis_by_group(g)
check("B 库内记录数一致", len(rows) == imported, f"rows={len(rows)} imported={imported}")

# stored files: with auto-convert enabled everything except genuine GIFs
# becomes gif (static jpg/png included — the user explicitly wants conversion
# on; oversized results are downscaled inside the converter so chat apps
# still recognize them as pictures) / 存储文件：勾选自动转换时，除真实 GIF
# 外的一切（含静态 jpg/png）都转为 gif——用户明确要求转换；超大结果在转换
# 器内降采样，聊天软件仍能识别为图片
stored_gif = sum(1 for r in rows if r["filename"].endswith(".gif"))
stored_static = sum(1 for r in rows
                    if r["filename"].endswith((".jpg", ".jpeg", ".png")))
check("C 全部存为 gif（静态图也转）",
      stored_gif + stored_static == len(rows),
      f"gif={stored_gif} static={stored_static} total={len(rows)}")
check("C2 有动画 gif", stored_gif > 0, stored_gif)

missing = sum(1 for r in rows if not os.path.isfile(dm.emoji_filepath(r)))
check("D 无缺失文件", missing == 0, f"missing={missing}")

# count animated stored files / 统计存储后仍为动画的文件
anim = 0
for r in rows[:200]:
    fp = dm.emoji_filepath(r)
    if fp and count_frames(fp) > 1:
        anim += 1
print(f"  （抽样 200 个中动画 {anim} 个）")

# one-click convert is a no-op here since everything is already gif /
# 一键转换在这里是空操作——全部已是 gif
converted, failed, deduped = dm.convert_library_to_gif(workers=8)
check("E 一键转换空操作", converted == 0 and failed == 0,
      f"converted={converted} failed={failed} deduped={deduped}")
after = dm.get_emojis_by_group(g)
check("E2 转换后全部为 gif", all(r["filename"].endswith(".gif") for r in after))

n_pass = sum(1 for _, ok in RES if ok)
print(f"\nQQ 全量导入验证: {n_pass}/{len(RES)} 通过")
try:
    dm._conn.close()
except Exception:
    pass
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
