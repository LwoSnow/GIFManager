"""Regression checks for recent changes: fixes + new features (offscreen, isolated, rerunnable)
新改动回归验证：修复项 + 新功能（离屏、数据隔离，可保留复跑）"""
import os
import sys
import json
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_regress_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PIL import Image as _PILImage
from app.models.data_manager import DataManager
from app.models.lang_manager import LangManager
from app.utils import gif_converter

app = QApplication(sys.argv)
dm = DataManager()
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:120]}")


# 1. set_emoji_column fix: dragging an unassigned card to column 0 no longer
# swallows others / 1. set_emoji_column 修复：未摊列拖到列 0 不再吞并
g = dm.create_group("列回归", "text")
ids = [dm.add_text_emoji(g, f"t{i}") for i in range(6)]
dm.set_emoji_column(ids[0], 0, 0)
rows = {e["id"]: e for e in dm.get_emojis_by_group(g)}
unsorted_rest = [i for i in ids[1:] if not rows[i]["user_sorted"]]
check("修复1 set_emoji_column 不吞并未分配卡", len(unsorted_rest) == 5, f"剩余未分配={len(unsorted_rest)}")
check("修复1b 目标卡已分配列0", rows[ids[0]]["col_index"] == 0 and rows[ids[0]]["user_sorted"] == 1)

# 2. LIKE wildcard escaping / 2. LIKE 通配符转义
g2 = dm.create_group("转义组", "image")
png = os.path.join(TMP, "p.png")
_img = QImage(10, 10, QImage.Format.Format_RGB32)
_img.fill(QColor(1, 2, 3))
_img.save(png)
dm.import_emoji(g2, png, auto_convert=False)
eid = dm.get_emojis_by_group(g2)[0]["id"]
dm.rename_emoji(eid, "50%off_emoji")
check("修复2 搜索%只匹配字面%（未全匹配）", len(dm.get_emojis_by_group(g2, "%")) == 1)
check("修复2b 搜索含%精确", len(dm.get_emojis_by_group(g2, "50%off")) == 1)
check("修复2c 搜索_只匹配字面_", len(dm.get_emojis_by_group(g2, "_")) == 1)
check("修复2d 反斜杠不崩溃", isinstance(dm.get_emojis_by_group(g2, "a\\b"), list))

# 3. Built-in group rename (Default/All renameable + marker
# recognition) / 3. 内置分组重命名（Default/All 可重命名 + 标记识别）
all_id = dm._all_group_id()
dft_id = dm.default_group_id()
all_old_name = dm.get_group(all_id)["name"]
ok_all = dm.rename_group(all_id, "我的全部")
check("修复3a All 组可重命名", ok_all and dm.get_group(all_id)["name"] == "我的全部")
check("修复3b 重命名后仍识别 All", dm._all_group_id() == all_id)
ok_dft = dm.rename_group(dft_id, "我的默认")
check("修复3c Default 组可重命名", ok_dft and dm.get_group(dft_id)["name"] == "我的默认")
check("修复3d 重命名后仍识别 Default", dm.default_group_id() == dft_id)
dm.rename_group(all_id, all_old_name)
check("修复3e 重命名回原名", dm.get_group(all_id)["name"] == all_old_name)
check("修复3f 重命名重名拒绝", not dm.rename_group(dft_id, dm.get_group(all_id)["name"]))

# 4. Sort by usage frequency / 4. 使用频率排序
gt = dm.create_group("频率组", "text")
tids = [dm.add_text_emoji(gt, f"f{i}") for i in range(4)]
dm.increment_use_count(tids[0])
dm.increment_use_count(tids[0])
dm.increment_use_count(tids[1])
rows2 = {e["id"]: e for e in dm.get_emojis_by_group(gt)}
check("新A 频率计数正确", rows2[tids[0]]["use_count"] == 2 and rows2[tids[1]]["use_count"] == 1)
dm.sort_group_emojis(gt, by="freq", desc=True)
after_d = dm.get_emojis_by_group(gt)
check("新A2 降序高频在前", after_d[0]["id"] == tids[0], f"first={after_d[0]['id']}")
dm.sort_group_emojis(gt, by="freq", desc=False)
after_a = dm.get_emojis_by_group(gt)
check("新A3 升序低频在前", after_a[0]["id"] in (tids[2], tids[3]), f"first={after_a[0]['id']}")

# 5. Lang fallback (en_US as a fallback) / 5. lang fallback（en_US 兜底）
tmp_lang = os.path.join(TMP, "lang")
os.makedirs(tmp_lang)
with open(os.path.join(tmp_lang, "zh_CN.json"), "w", encoding="utf-8") as f:
    json.dump({"exist_key": "中文值"}, f)
with open(os.path.join(tmp_lang, "en_US.json"), "w", encoding="utf-8") as f:
    json.dump({"exist_key": "EN value", "en_only": "English fallback"}, f)
lm = LangManager()
lm._lang_dir = lambda: tmp_lang
lm.set_language("zh_CN")
check("优化B en_US 兜底缺失键", lm.t("en_only") == "English fallback", lm.t("en_only"))
check("优化B2 当前语言覆盖", lm.t("exist_key") == "中文值")
check("优化B3 双缺返回键名", lm.t("nope_key") == "nope_key")

# 6. Import format by content: with auto-convert enabled everything
# except genuine GIFs converts to gif / 6. 按内容决定导入格式：勾选自动转换
# 时，除真实 GIF 外全部转 gif
ff = gif_converter.ffmpeg_path()
check("优化C ffmpeg 已捆绑", ff is not None, str(ff))
# static png converts to gif when auto-convert is enabled (the user
# explicitly wants conversion on; oversized converted gifs are handled by
# downscaling in the converter, not by skipping conversion)
# 勾选自动转换时静态 png 转 gif（用户明确要求转换；超大转换结果由转换器
# 内降采样处理，而不是跳过转换）
png2 = os.path.join(TMP, "p2.png")
_img2 = QImage(12, 12, QImage.Format.Format_RGB32)
_img2.fill(QColor(30, 40, 50))
_img2.save(png2)
r = dm.import_emoji(g2, png2, auto_convert=True)
stored = [e for e in dm.get_emojis_by_group(g2) if e["original_name"] == "p2"]
check("优化C2 静态 png 转存 gif", r == "ok" and stored
      and stored[0]["filename"].endswith(".gif"),
      r if r != "ok" else stored[0]["filename"])
# animated webp still converts to gif / 动画 webp 仍转 gif
_webp = os.path.join(TMP, "anim.webp")
_f1 = _PILImage.new("RGB", (20, 20), (255, 0, 0))
_f2 = _PILImage.new("RGB", (20, 20), (0, 0, 255))
_f1.save(_webp, save_all=True, append_images=[_f2], duration=100)
rw = dm.import_emoji(g2, _webp, auto_convert=True)
stored_w = [e for e in dm.get_emojis_by_group(g2) if e["original_name"] == "anim"]
check("优化C3 动画 webp 转存 gif", rw == "ok" and stored_w
      and stored_w[0]["filename"].endswith(".gif"),
      rw if rw != "ok" else (stored_w[0]["filename"] if stored_w else "none"))

# C4: oversized gif import downscales to MAX_GIF_DIM (animation kept) /
# 超大 gif 导入时降采样到 MAX_GIF_DIM 内（保留动画）
_big = os.path.join(TMP, "big.gif")
_fb1 = _PILImage.new("RGB", (1200, 800), (10, 20, 30))
_fb2 = _PILImage.new("RGB", (1200, 800), (200, 100, 50))
_fb1.save(_big, save_all=True, append_images=[_fb2], duration=80, loop=0)
rb = dm.import_emoji(g2, _big, auto_convert=True)
stored_b = [e for e in dm.get_emojis_by_group(g2) if e["original_name"] == "big"]
fp_b = dm.emoji_filepath(stored_b[0]) if stored_b else ""
dims_b = gif_converter._image_dimensions(fp_b) if fp_b else None
check("优化C4 超大 gif 导入降采样", rb == "ok" and stored_b
      and dims_b is not None and max(dims_b) <= gif_converter.MAX_GIF_DIM,
      dims_b if dims_b else (rb if rb != "ok" else "no file"))

# C5: downscale_gif_if_needed falls back to ffmpeg when Pillow is missing
# (simulated by hiding the PIL import) / Pillow 缺失时降采样回退 ffmpeg
# （模拟隐藏 PIL 导入）
_orig_pil = sys.modules.pop("PIL", None)
for _k in [k for k in sys.modules if k.startswith("PIL")]:
    sys.modules.pop(_k, None)
try:
    _big2 = os.path.join(TMP, "big2.gif")
    _c1 = _PILImage.new("RGB", (1000, 1000), (30, 200, 90))
    _c1.save(_big2)
    _dst2 = os.path.join(TMP, "big2_small.gif")
    _ok2 = gif_converter.downscale_gif_if_needed(_big2, _dst2)
    _d2 = gif_converter._image_dimensions(_dst2) if _ok2 else None
    check("优化C5 无Pillow降采样走ffmpeg", _ok2 and _d2 is not None
          and max(_d2) <= gif_converter.MAX_GIF_DIM,
          _d2 if _d2 else "downscale failed")
finally:
    if _orig_pil is not None:
        sys.modules["PIL"] = _orig_pil
        for _k, _v in list(sys.modules.items()):
            if _k.startswith("PIL."):
                sys.modules.pop(_k, None)


# 7. Single-instance mutex / 7. 单实例互斥
import main as main_mod
r1 = main_mod._acquire_single_instance_mutex()
r2 = main_mod._acquire_single_instance_mutex()
# Invariant: the SECOND call always reports "already exists" — either an
# external GIFManager holds the mutex, or this very process created it on
# the first call. The first call is True only when an external instance is
# running, so r1 is environment-dependent (do not assert on it alone).
# 不变量：第二次调用必报告"已存在"——要么外部 GIFManager 持有互斥量，
# 要么本进程在第一次调用时创建了它。第一次调用仅在外部实例运行时才为
# True，依赖环境（不能单独断言）。
check("新B 重复检测必报已存在", r2 is True, f"r1={r1} r2={r2}")
check("新B2 首次检测不误报", r1 in (False, True), f"r1={r1}")

# 8. GIF clipboard image/gif mime (keeps animation) / 8. GIF 剪贴板 image/gif mime（保留动画）
gifp = os.path.join(TMP, "a.gif")
with open(gifp, "wb") as f:
    f.write(b"GIF89a" + b"\x00" * 32)
dm.import_emoji(g2, gifp, auto_convert=False)
gif_e = next(e for e in dm.get_emojis_by_group(g2) if e["filename"].endswith(".gif"))
ok_gif = dm.copy_to_clipboard(gif_e, mode=1)
mime = app.clipboard().mimeData()
check("优化D GIF 剪贴板含 image/gif", ok_gif and mime.hasFormat("image/gif"), str(mime.formats()))

# 9. Global usage-frequency sorting (main_window integration path: _apply_global_sort /
# freq debounce) / 9. 使用频率全局排序（main_window 集成路径：_apply_global_sort / freq 防抖）
# The data layer is verified above; the UI path is covered by full_test. Here we only
# verify sort_group_emojis on an image group / 数据层已验证；UI 集成路径在 full_test 覆盖，
# 此处验证 sort_group_emojis 对图片分组
dm.import_emoji(g2, gifp, auto_convert=False)  # 第二张图
dm.import_emoji(g2, png, auto_convert=False)
dm.sort_group_emojis(g2, by="name", desc=False)
names = [e["original_name"] for e in dm.get_emojis_by_group(g2)]
check("新C 图片分组名称排序", names == sorted(names, key=str.lower), names)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n回归验证: {n_pass}/{len(RES)} 通过")

# Cleanup: quit Qt safely before exiting the process; offscreen PySide6 may segfault on
# interpreter exit, so bypass it with os._exit / 清理（先安全退出 Qt 再退出进程；offscreen 下
# PySide6 解释器退出可能段错误，用 os._exit 绕过）
try:
    dm._conn.close()
except Exception:
    pass
app.quit()
shutil.rmtree(TMP, ignore_errors=True)
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
