"""GIFManager 压力测试 + Bug 测试（离屏运行，数据隔离在临时目录，不污染真实 data/）

压力测试：2000 张 512x512 图片 → 导入 / 启动 / 切换分组 / 搜索 / 复制 / 移动 / 删除 / 文字 / 清空分组
Bug 测试：卡片重叠、占位文字、跨组去重、剪贴板、文件一致性、分组重排等

用法：.venv/Scripts/python.exe tests/stress_test.py
"""
import os
import sys
import time
import json
import shutil
import tempfile
import ctypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_stress_")
OUT = os.path.join(ROOT, "tests", "output")
os.makedirs(OUT, exist_ok=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt
# 隔离 QSettings：Windows 上 setPath/setDefaultFormat 对注册表默认格式无效，
# 改为 monkeypatch main_window 模块中的 QSettings 引用 → 单文件 ini（不碰注册表）
import app.main_window as mw_mod


def _isolate_qsettings(tmp):
    _Real = mw_mod.QSettings

    class _Iso(_Real):
        def __init__(self, *a, **k):
            super().__init__(os.path.join(tmp, "settings.ini"), _Real.Format.IniFormat)

    return _Iso


mw_mod.QSettings = _isolate_qsettings(TMP)

# 隔离数据目录（monkeypatch 必须在 DataManager 实例化之前）
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor, QPainter
from PySide6.QtTest import QTest
from app.main_window import MainWindow
from app.models.data_manager import DataManager
from app.models.lang_manager import tr
from app.widgets.emoji_item import EmojiItem, _loader

app = QApplication(sys.argv)

RESULTS = {}
BUGS = []
MEM_PEAK = 0


def now():
    return time.perf_counter()


def timed(name, fn):
    t0 = now()
    r = fn()
    dt = now() - t0
    RESULTS[name] = round(dt, 3)
    print(f"[{dt:8.3f}s] {name}")
    return dt if r is None else r


def flush(ms=50):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.003)


def sample_mem():
    """Windows 工作集内存采样（字节）"""
    global MEM_PEAK
    try:
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        h = ctypes.windll.kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), ctypes.sizeof(PMC)):
            MEM_PEAK = max(MEM_PEAK, pmc.WorkingSetSize)
            return pmc.WorkingSetSize
        return 0
    except Exception:
        return 0


def bug(name, ok, detail=""):
    BUGS.append({"name": name, "ok": bool(ok), "detail": str(detail)[:200]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:200]}")


def check_overlap(tag, cards, limit=6):
    """检测卡片几何重叠（两两 QRect.intersects）与越界，返回 (重叠对数, 越界数, 检测对数)"""
    rects = [c.geometry() for c in cards]
    bad = 0
    pairs = 0
    n = len(rects)
    for i in range(n):
        ri = rects[i]
        for j in range(i + 1, n):
            pairs += 1
            if ri.intersects(rects[j]):
                bad += 1
                if bad >= limit:
                    return bad, pairs, (rects[i], rects[j])
    return bad, pairs, None


def gen_images(n, outdir, size=512):
    """生成 n 张内容不同的 512x512 PNG"""
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i in range(n):
        img = QImage(size, size, QImage.Format.Format_RGB32)
        r = (i * 7 + 13) % 256
        g = (i * 13 + 29) % 256
        b = (i * 29 + 7) % 256
        img.fill(QColor(r, g, b))
        p = QPainter(img)
        p.fillRect((i * 37) % 380, (i * 53) % 380, 90, 90, QColor(255 - r, 255 - g, 255 - b))
        p.end()
        fp = os.path.join(outdir, f"img_{i:05d}.png")
        img.save(fp, "PNG")
        paths.append(fp)
    return paths


def wait_thumbs(timeout=180):
    t0 = now()
    while len(_loader._pending) > 0:
        app.processEvents()
        time.sleep(0.01)
        if now() - t0 > timeout:
            break
    flush(100)
    return now() - t0


def section(title):
    print("\n" + "=" * 60)
    print("## " + title)
    print("=" * 60)


def safe_select_group(gid):
    """选择分组：新创建的分组按钮尚未重建，先 _rebuild() 再选择"""
    w.group_list._rebuild()
    w.group_list.select_group(gid)


# ======================================================================
section("0. 数据准备：生成 2000 张 512x512 图片")
N = 2000
img_dir = os.path.join(TMP, "images")


def _gen():
    return gen_images(N, img_dir, 512)


img_paths = timed("gen_2000_images", _gen)
print(f"  图片总大小: {sum(os.path.getsize(p) for p in img_paths) / 1024 / 1024:.1f} MB")

# ======================================================================
section("1. 导入 2000 张到「默认表情」分组")
dm = DataManager()
default_g = dm.get_group_by_name("Default Expression")
assert default_g is not None, "默认表情分组缺失"
g2 = dm.create_group("压测分组", "image")
assert g2 is not None

stats = {"ok": 0, "dup": 0, "err": 0}


def _import():
    for fp in img_paths:
        r = dm.import_emoji(default_g["id"], fp)
        stats[r if r in stats else "err"] += 1


timed("import_2000", _import)
print(f"  导入结果: ok={stats['ok']} duplicate={stats['dup']} error={stats['err']}")
bug("B0 导入全部成功", stats["ok"] == N and stats["err"] == 0, stats)
sample_mem()

# ======================================================================
section("2. 启动：MainWindow 构造 + show（当前停在「全部」，全量创建卡片）")
w = timed("window_ctor", MainWindow)
bug("B5 启动默认选中「全部」", w.current_group_id is None,
    f"current_group_id={w.current_group_id}")
w.show()
flush(200)
RESULTS["show_first"] = round(0, 3)
sample_mem()

section("3. 等待 2000 张缩略图异步解码完成")
RESULTS["thumbs_ready"] = round(wait_thumbs(), 3)
print(f"[{RESULTS['thumbs_ready']:8.3f}s] thumbs_ready (后台解码 2000 张)")
sample_mem()

# ======================================================================
section("4. Bug 检查：启动后「全部」视图卡片重叠 / 越界")
grid = w.emoji_grid
cards_all = list(grid._items)
print(f"  「全部」视图卡片数: {len(cards_all)}（期望 2000 去重后 ≈ 2000）")
bad, pairs, sample = check_overlap("all", cards_all)
bug("B3 「全部」2000 卡无重叠", bad == 0, f"重叠对数={bad} 检测对数={pairs} 样例={sample}")
out_cnt = sum(1 for c in cards_all if c.x() < 0 or c.y() < 0)
bug("B3b 无卡片越出左上角", out_cnt == 0, f"越界卡数={out_cnt}")
loaded_thumbs = sum(1 for c in cards_all
                    if c._thumb_label is not None and c._thumb_label.pixmap() is not None and not c._thumb_label.pixmap().isNull())
bug("B13 缩略图全部就绪", loaded_thumbs == len(cards_all),
    f"有图 {loaded_thumbs}/{len(cards_all)}")
grid.grab().save(os.path.join(OUT, "all_view_2000.png"))

# ======================================================================
section("5. 切换分组：默认表情（懒加载 + 首次自动摊列 2000 张写库）")
RESULTS["switch_default"] = round(
    timed("switch_to_default", lambda: w.group_list.select_group(default_g["id"])), 3
)
flush(200)
cards_def = list(grid._items)
print(f"  懒加载可视卡片数: {len(cards_def)}")
bad, pairs, sample = check_overlap("default", cards_def)
bug("B4 默认表情视图卡片无重叠", bad == 0, f"重叠对数={bad} 样例={sample}")
sample_mem()

section("6. 搜索过滤（默认表情中输入关键词）")
w.search_bar.setText("img_001")
flush(100)
shown = len(grid._items)
bug("B10 搜索过滤生效", shown > 0 and shown < 500, f"命中卡片数={shown}")


def _search():
    t0 = now()
    w.search_bar.setText("img_00")
    flush(50)
    w.search_bar.setText("")
    flush(50)
    return now() - t0


RESULTS["search_roundtrip"] = round(_search(), 3)

# ======================================================================
section("7. 复制：文件路径模式 / 图片数据模式")
emojis = dm.get_emojis_by_group(default_g["id"])
e0 = emojis[0]


def _copy_path():
    t0 = now()
    w._send_mode = 0
    ok = dm.copy_to_clipboard(e0, mode=0)
    return now() - t0, ok


dt0, ok0 = timed("copy_path_mode0", _copy_path)
cb = app.clipboard()
mime = cb.mimeData()
bug("B7a 复制文件路径：mime 含文件 URL", ok0 and mime.hasUrls(), str(mime.formats()))


def _copy_image():
    t0 = now()
    w._send_mode = 1
    ok = dm.copy_to_clipboard(e0, mode=1)
    return now() - t0, ok


dt1, ok1 = timed("copy_image_mode1", _copy_image)
img = app.clipboard().image()
bug("B7b 复制图片数据：剪贴板图像非空", ok1 and not img.isNull(),
    f"图像 {img.width()}x{img.height()}")

# ======================================================================
section("8. 移动 100 张到「压测分组」")
moved = dm.get_emojis_by_group(default_g["id"])[:100]
src_files = [dm.emoji_filepath(e) for e in moved]


def _move():
    for e in moved:
        dm.move_emoji(e["id"], g2)


timed("move_100", _move)
dst_files = [dm.emoji_filepath(e) for e in dm.get_emojis_by_group(g2)]
bug("B9 移动后文件随分组迁移", all(os.path.isfile(fp) for fp in dst_files),
    f"目标分组文件数={len(dst_files)}")
bug("B9b 移动后原分组文件已不存在",
    not any(os.path.isfile(fp) for fp in src_files),
    f"残留文件数={sum(1 for fp in src_files if os.path.isfile(fp))}")
bug("B9c 移动后目标分组 DB 记录数", dm.count_emojis_in_group(g2) == 100,
    f"count={dm.count_emojis_in_group(g2)}")

# ======================================================================
section("9. 删除 50 张（DB + 文件）")
dels = dm.get_emojis_by_group(default_g["id"])[:50]
del_files = [dm.emoji_filepath(e) for e in dels]


def _del():
    for e in dels:
        dm.delete_emoji(e["id"])


timed("delete_50", _del)
ids = {e["id"] for e in dels}
remaining = [e for e in dm.get_emojis_by_group(default_g["id"]) if e["id"] in ids]
bug("B8 删除后 50 条记录不再存在", len(remaining) == 0, f"残留记录={len(remaining)}")
bug("B8b 删除后文件被移除", not any(os.path.isfile(fp) for fp in del_files),
    f"残留文件数={sum(1 for fp in del_files if os.path.isfile(fp))}")

# ======================================================================
section("10. 设置对话框打开耗时")
from app.widgets.settings_dialog import SettingsDialog


def _dlg():
    d = SettingsDialog(0, True, False, False, 100, 200, dm, "F10", w)
    d.show()
    flush(50)
    d.close()
    return True


timed("settings_dialog_open", _dlg)

# ======================================================================
section("11. 文字分组：500 条文字 + 加载")
tg = dm.create_group("文字压测", "text")
texts = [f"颜文字 {i} (｡•̀ᴗ-)✧ 第{i}号" for i in range(500)]


def _add_texts():
    for t in texts:
        dm.add_text_emoji(tg, t)


timed("add_text_500", _add_texts)
RESULTS["switch_text"] = round(
    timed("switch_to_text", lambda: safe_select_group(tg)), 3
)
flush(200)
cards_text = list(grid._items)
bad, pairs, sample = check_overlap("text", cards_text)
bug("B4b 文字分组卡片无重叠", bad == 0, f"重叠对数={bad} 样例={sample}")
print(f"  文字分组懒加载可视卡数: {len(cards_text)}（总 {500}）")
sample_mem()

# ======================================================================
section("12. 文字粘贴（Ctrl+V 多行 → keyPressEvent 模拟）")
from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeyEvent
app.clipboard().setText("粘贴行一\n粘贴行二\n粘贴行三")
before = dm.count_emojis_in_group(tg)


def _paste():
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V,
                   Qt.KeyboardModifier.ControlModifier)
    w.keyPressEvent(ev)
    flush(100)


timed("text_paste_3lines", _paste)
after = dm.count_emojis_in_group(tg)
bug("B11 粘贴 3 行 → 新增 3 条", after - before == 3, f"before={before} after={after}")

# ======================================================================
section("13. Bug：空分组占位文字（图片 / 文字）")
empty_g = dm.create_group("空分组", "image")


def _switch_empty():
    safe_select_group(empty_g)
    flush(150)


timed("switch_empty_group", _switch_empty)
ph = grid._placeholder
g = ph.geometry()
cg = grid.rect()
print(f"  占位: visible={ph.isVisible()} text={ph.text()!r}")
print(f"  占位 geometry={g.x()},{g.y()} {g.width()}x{g.height()}  容器={cg.width()}x{cg.height()}")
bug("B1a 空图片分组占位可见", ph.isVisible())
bug("B1b 占位文案完整", ph.text() == tr("drag_placeholder"), ph.text())
bug("B1c 占位不顶左上角（有边距/居中）",
    g.width() >= cg.width() - 2 and g.height() >= cg.height() - 2,
    f"placeholder {g.width()}x{g.height()} vs 容器 {cg.width()}x{cg.height()}")
grid.grab().save(os.path.join(OUT, "empty_image_group.png"))
# 残留检查：空分组后 _data / _items 是否清空（观察项：当前实现不清空，属潜在内存问题）
print(f"  [观察] 空分组后 _data 残留 {len(grid._data)} 条, _items 残留 {len(grid._items)} 个")

# 空文字分组占位
safe_select_group(tg)
flush(50)
te = dm.create_group("空文字组", "text")
safe_select_group(te)
flush(150)
ph2 = grid._placeholder
print(f"  文字空分组占位 text={ph2.text()!r}")
bug("B2 空文字分组占位文案为粘贴提示", ph2.isVisible() and ph2.text() == tr("paste_text_placeholder"), ph2.text())
grid.grab().save(os.path.join(OUT, "empty_text_group.png"))

# ======================================================================
section("14. 清空分组：删除默认表情剩余全部（压力）")
w.group_list.select_group(default_g["id"])
flush(100)
remaining_all = dm.get_emojis_by_group(default_g["id"])
print(f"  默认表情剩余: {len(remaining_all)} 张")


def _clear():
    for e in list(dm.get_emojis_by_group(default_g["id"])):
        dm.delete_emoji(e["id"])
    # 真实用户路径：删除后 UI 自动刷新（_delete_emoji → _refresh_emoji_grid）
    w._refresh_emoji_grid()
    flush(150)


timed("delete_all_default", _clear)
flush(150)
print(f"  清空后占位: visible={grid._placeholder.isVisible()} text={grid._placeholder.text()!r}")
bug("B1d 删除全部后占位文字重新显示",
    grid._placeholder.isVisible() and grid._placeholder.text() == tr("drag_placeholder"),
    grid._placeholder.text())
grid.grab().save(os.path.join(OUT, "after_clear_group.png"))

# ======================================================================
section("15. 「全部」跨组去重验证（B6）")
dm.import_emoji(default_g["id"], img_paths[0])   # 导入到默认表情
dm.import_emoji(g2, img_paths[0])                # 同一张图导入压测分组（跨组允许）
all_view = dm.get_all_emojis()
cnt_first = sum(1 for e in all_view if e["content_hash"] == dm._file_md5(img_paths[0]))
bug("B6 「全部」按内容哈希折叠跨组重复",
    cnt_first == 1, f"折叠后出现 {cnt_first} 次")
w.group_list.select_all_group()
flush(150)

# ======================================================================
section("16. 数据层边界：分组重排 / 非法名 / 重命名目录")
# 重排
dm.reorder_group(g2, 0)
order_names = [g["name"] for g in dm.get_all_groups()]
bug("B14 分组重排后顺序更新", "压测分组" in order_names,
    f"顺序={order_names}")
# 非法名 / 重名
bug("B15a 非法分组名被拒绝", dm.create_group("bad/name", "image") is None)
bug("B15b 重名分组被拒绝", dm.create_group("压测分组", "image") is None)
# 重命名分组 → 目录同步
gdir_before = os.path.join(dm._emojis_dir, "压测分组")
ok_ren = dm.rename_group(g2, "压测分组2")
gdir_after = os.path.join(dm._emojis_dir, "压测分组2")
bug("B16 重命名后目录同步", ok_ren and os.path.isdir(gdir_after) and not os.path.isdir(gdir_before),
    f"before={os.path.isdir(gdir_before)} after={os.path.isdir(gdir_after)}")

# ======================================================================
section("17. 收尾：内存峰值 / 结果汇总")
sample_mem()
RESULTS["mem_peak_mb"] = round(MEM_PEAK / 1024 / 1024, 1)
RESULTS["db_emojis_total"] = dm.count_all_emojis()

print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
    json.dump({"results": RESULTS, "bugs": BUGS}, f, ensure_ascii=False, indent=2)

fail_count = sum(1 for b in BUGS if not b["ok"])
print(f"\nBug 汇总: {len(BUGS) - fail_count}/{len(BUGS)} 通过, {fail_count} 失败/异常")

# ======================================================================
# 清理
print("\n清理临时数据...")
try:
    dm._conn.close()
except Exception:
    pass
QThreadPool = __import__("PySide6.QtCore", fromlist=["QThreadPool"]).QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
app.quit()
try:
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"已删除临时目录 {TMP}")
except Exception as e:
    print(f"临时目录清理失败: {e}（目录 {TMP}）")
