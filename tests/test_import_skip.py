"""Verify the fast "already imported" skip for large imports:
- importing the same pack twice must do NO conversion/copy work the second
  time (the source hash is checked first and matching files are skipped)
- the skip is driven by the recorded source hash, so it also works when the
  first import converted the file (stored bytes differ from the source)
- the returned "duplicated" count includes the pre-skipped files
验证大批量导入的"已导入"快速跳过：
- 同一批文件导入两次，第二次不得再做任何转换/复制工作（先比对源哈希，
  命中即跳过）
- 跳过依据记录的源哈希，因此首次导入为转换的情况同样有效（存储字节与源不同）
- 返回的"重复数"包含被预跳过的文件
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

from PIL import Image

from app.utils import gif_converter
from app.models.data_manager import DataManager

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


def fresh_dm(tag):
    tmp = tempfile.mkdtemp(prefix=tag)
    import app.models.data_manager as dm_mod
    dm_mod._app_data_dir = lambda: os.path.join(tmp, "data")
    return dm_mod.DataManager(), tmp


def make_pack(tmp, n):
    # A QQ-like pack: mix of static png (needs conversion) and genuine gif
    paths = []
    for i in range(n):
        p = os.path.join(tmp, f"emoji_{i}.png")
        Image.new("RGB", (64, 64), (i * 7 % 256, 120, 200)).save(p)
        paths.append(p)
    for i in range(n // 2):
        p = os.path.join(tmp, f"anim_{i}.gif")
        # Distinct RGB colours per gif: single-colour palette images all save
        # to IDENTICAL bytes in Pillow, which would make the dedup (correctly)
        # collapse them and break the count assertions.
        # 每个 gif 使用不同的 RGB 颜色：单色调色板图在 Pillow 中会存成完全
        # 相同的字节，去重会（正确地）合并它们，使数量断言不符。
        frames = [Image.new("RGB", (64, 64),
                            ((i * 37 + j * 11) % 256, (i * 53) % 256, 180))
                  for j in range(3)]
        frames[0].save(p, save_all=True, append_images=frames[1:],
                       duration=80, loop=0)
        paths.append(p)
    return paths


# Count how much real work the import performs / 统计导入实际执行的工作量
CALLS = {"convert": 0, "copy": 0}
_real_convert = gif_converter.convert_to_gif
_real_copy = gif_converter._copy_as_gif


def _count_convert(*a, **k):
    CALLS["convert"] += 1
    return _real_convert(*a, **k)


def _count_copy(*a, **k):
    CALLS["copy"] += 1
    return _real_copy(*a, **k)


gif_converter.convert_to_gif = _count_convert
gif_converter._copy_as_gif = _count_copy

# ---------------------------------------------------------------- batch path
dm, tmp = fresh_dm("gifmgr_skip_")
gid = dm.create_group("QQ", "image")
pack = make_pack(tmp, 12)

CALLS["convert"] = CALLS["copy"] = 0
imported1, dup1 = dm.import_emojis_batch(gid, pack,
                                         workers=4, auto_convert=True)
work_first = CALLS["convert"] + CALLS["copy"]
check("首次导入有转换/复制工作", work_first > 0,
      f"convert={CALLS['convert']} copy={CALLS['copy']}")
check("首次导入全部入库", imported1 == len(pack),
      f"imported={imported1} of {len(pack)}")

# Second import of the SAME pack: must not convert or copy anything.
CALLS["convert"] = CALLS["copy"] = 0
imported2, dup2 = dm.import_emojis_batch(gid, pack,
                                         workers=4, auto_convert=True)
work_second = CALLS["convert"] + CALLS["copy"]
check("二次导入零转换/零复制", work_second == 0,
      f"convert={CALLS['convert']} copy={CALLS['copy']}")
check("二次导入零新增", imported2 == 0, f"imported={imported2}")
check("二次导入全部计为重复", dup2 == len(pack),
      f"duplicated={dup2} of {len(pack)}")
check("库中仍只有一份", len(dm.get_emojis_by_group(gid)) == len(pack),
      len(dm.get_emojis_by_group(gid)))

# ------------------------------------------- single path also pre-skips fast
CALLS["convert"] = CALLS["copy"] = 0
_one = os.path.join(tmp, "single.png")
Image.new("RGB", (50, 50), (9, 9, 9)).save(_one)
dm.import_emoji(gid, _one, auto_convert=True)
_first = CALLS["convert"] + CALLS["copy"]
CALLS["convert"] = CALLS["copy"] = 0
_res = dm.import_emoji(gid, _one, auto_convert=True)
check("单文件首次有工作", _first > 0, _first)
check("单文件二次零工作", (CALLS["convert"] + CALLS["copy"]) == 0,
      f"convert={CALLS['convert']} copy={CALLS['copy']}")
check("单文件二次返回 duplicate", _res == "duplicate", _res)

# ------------------------- skip works when the FIRST import was a conversion
dm2, tmp2 = fresh_dm("gifmgr_skip2_")
gid2 = dm2.create_group("G", "image")
pngs = []
for i in range(5):
    p = os.path.join(tmp2, f"c{i}.png")
    Image.new("RGB", (48, 48), (i * 40, 30, 90)).save(p)
    pngs.append(p)
dm2.import_emojis_batch(gid2, pngs, workers=2, auto_convert=True)  # -> gifs
# the source hash must have been recorded so the raw sources are recognised
_srcs = [e.get("src_hash") for e in dm2.get_emojis_by_group(gid2)]
check("转换导入记录了源哈希", all(bool(s) for s in _srcs),
      f"recorded={sum(1 for s in _srcs if s)}/{len(_srcs)}")
CALLS["convert"] = CALLS["copy"] = 0
_imp, _dup = dm2.import_emojis_batch(gid2, pngs, workers=2, auto_convert=True)
check("转换导入后二次零转换",
      (CALLS["convert"] + CALLS["copy"]) == 0 and _imp == 0 and _dup == 5,
      f"imp={_imp} dup={_dup} convert={CALLS['convert']}")

# ------------------------------------------- filter helper reports the split
dm3, tmp3 = fresh_dm("gifmgr_skip3_")
gid3 = dm3.create_group("G", "image")
p3 = make_pack(tmp3, 4)
dm3.import_emojis_batch(gid3, p3, workers=2, auto_convert=True)
_newfiles, _skipped = dm3.filter_already_imported(gid3, p3)
check("filter_already_imported 全跳过", len(_newfiles) == 0
      and _skipped == len(p3), f"new={len(_newfiles)} skipped={_skipped}")
# a brand new file must pass / 全新文件必须通过
extra = os.path.join(tmp3, "brand_new.png")
Image.new("RGB", (40, 40), (250, 1, 2)).save(extra)
_new2, _skip2 = dm3.filter_already_imported(gid3, p3 + [extra])
check("新文件不被跳过", len(_new2) == 1 and _skip2 == len(p3),
      f"new={len(_new2)} skipped={_skip2}")

# --------------------------------- main window progress path pre-filters too
import inspect
import app.main_window as mw
_psrc = inspect.getsource(mw.MainWindow._import_with_progress)
check("大批量路径预先过滤", "filter_already_imported" in _psrc)
check("大批量路径计入预跳过", "pre_skipped" in _psrc)

gif_converter.convert_to_gif = _real_convert
gif_converter._copy_as_gif = _real_copy

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n已导入快速跳过验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
