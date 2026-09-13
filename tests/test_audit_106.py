"""Regression tests for the Report_1.0.6.md audit findings (C1 + B1-B21).
Report_1.0.6.md 审计结论的回归测试（C1 + B1-B21）。"""
import os
import sys
import tempfile
import time
import inspect

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="audit106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PIL import Image
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from PySide6.QtCore import Qt, QSettings
from tests._iso import isolate_all, drain_and_exit

isolate_all()

app = QApplication.instance() or QApplication(sys.argv)

from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem, _loader
from app.widgets.emoji_grid import EmojiGridWidget
from app.utils import gpu_pref
import app.utils.gif_converter as gif_converter
import app.widgets.emoji_item as ei
import app.main_window as mw_mod

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name
          + ((" | " + str(detail)) if detail else ""))


def flush(ms=120):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


def make_gif(path, seed, size=(40, 40), frames=3):
    imgs = [Image.new("RGB", size, ((seed * 37 + j * 11) % 256, 90, 180))
            for j in range(frames)]
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=80,
                 loop=0)


dm = DataManager()
gid = dm.create_group("Audit", "image")
src_dir = os.path.join(TMP, "src")
os.makedirs(src_dir, exist_ok=True)
for i in range(24):
    p = os.path.join(src_dir, f"s{i}.gif")
    make_gif(p, i)
    dm.import_emoji(gid, p, auto_convert=False)

# ---------------------------------------------------------------- B1
print("\n[B1] adapter classification / 显卡分类")
cases = [
    ("Intel(R) Arc(TM) A770 Graphics", gpu_pref.PREF_HIGH),
    ("Intel Arc A750", gpu_pref.PREF_HIGH),
    ("AMD Radeon 780M", gpu_pref.PREF_POWER),
    ("AMD Radeon 680M", gpu_pref.PREF_POWER),
    ("AMD Radeon(TM) Graphics", gpu_pref.PREF_POWER),
    ("Intel(R) UHD Graphics 620", gpu_pref.PREF_POWER),
    ("NVIDIA GeForce RTX 3050 Laptop GPU", gpu_pref.PREF_HIGH),
    ("AMD Radeon RX 6600", gpu_pref.PREF_HIGH),
    ("Honor Virtual Display Device", None),
]
bad = [(n, gpu_pref.classify_adapter(n), w) for n, w in cases
       if gpu_pref.classify_adapter(n) != w]
check("B1 Arc / AMD M-series / unknown adapters classified correctly",
      not bad, bad)
_sd = __import__("app.widgets.settings_dialog", fromlist=["x"])
check("B1 an unclassifiable adapter is offered (disabled) not dropped",
      "gpu_adapter_unmapped" in inspect.getsource(
          _sd.SettingsDialog._fill_gpu_combo))

# ---------------------------------------------------------------- B12
print("\n[B12] per-group indexes / 分组索引")
idx = {r[1] for r in dm._conn.execute(
    "PRAGMA index_list(emojis)").fetchall()}
check("B12 (group_id, content_hash) index exists",
      "idx_emojis_group_hash" in idx, idx)
check("B12 (group_id, src_hash) index exists",
      "idx_emojis_group_src" in idx, idx)

# ---------------------------------------------------------------- B6
print("\n[B6] hashes computed once / 哈希只算一次")
srcs = [os.path.join(src_dir, f"s{i}.gif") for i in range(5)]
hash_out = {}
kept, skipped = dm.filter_already_imported(gid, srcs, hash_out=hash_out)
check("B6 filter_already_imported fills hash_out for every file",
      len(hash_out) == len(srcs), len(hash_out))
check("B6 all five are already imported", skipped == 5 and not kept,
      f"kept={len(kept)} skipped={skipped}")
calls = {"n": 0}
real_md5_static = DataManager._file_md5


def counting_md5(path):
    calls["n"] += 1
    return real_md5_static(path)


DataManager._file_md5 = staticmethod(counting_md5)
try:
    gid2 = dm.create_group("Batch", "image")
    dm.import_emojis_batch(
        gid2, [os.path.join(src_dir, "s0.gif")],
        src_hash_map={os.path.join(src_dir, "s0.gif"): hash_out[
            os.path.join(src_dir, "s0.gif")]})
    # the stored-file hash is still computed; the SOURCE hash must not be
    check("B6 batch import reuses the supplied source hash",
          calls["n"] <= 2, f"md5 calls={calls['n']}")
finally:
    DataManager._file_md5 = staticmethod(real_md5_static)
real_md5 = DataManager._file_md5

# ---------------------------------------------------------------- B7
print("\n[B7] batch src_hash records the ORIGINAL file / 批量 src_hash 记录原文件")
gid3 = dm.create_group("Batch2", "image")
orig = os.path.join(src_dir, "s7.gif")
orig_hash = DataManager._file_md5(orig)
temp_gif = os.path.join(TMP, "converted.gif")
make_gif(temp_gif, 999)          # different bytes from the source
dm.import_emojis_batch(gid3, [temp_gif], auto_convert=False,
                       src_hash_map={temp_gif: orig_hash})
row = dm._conn.execute(
    "SELECT content_hash, src_hash FROM emojis WHERE group_id=?",
    (gid3,)).fetchone()
check("B7 src_hash stores the original file's hash, not the temp gif's",
      row[1] == orig_hash, f"src_hash={row[1][:12]} want={orig_hash[:12]}")
check("B7 content_hash still identifies the stored bytes",
      row[0] != orig_hash, row[0][:12])
kept, skipped = dm.filter_already_imported(gid3, [orig])
check("B7 the pre-skip now recognises the original file",
      skipped == 1 and not kept, f"skipped={skipped}")

# ---------------------------------------------------------------- B11
print("\n[B11] import cleanup never deletes a user source file / 不误删用户源文件")
win = mw_mod.MainWindow()
win.data_manager = dm
user_temp = os.path.join(tempfile.gettempdir(), f"user_src_{os.getpid()}.gif")
make_gif(user_temp, 4242)
try:
    win._import_with_progress(gid, [user_temp])
    check("B11 a user file chosen from %TEMP% survives the import cleanup",
          os.path.isfile(user_temp), user_temp)
finally:
    if os.path.isfile(user_temp):
        os.remove(user_temp)

# ---------------------------------------------------------------- B5
print("\n[B5] GPU preference sync / GPU 偏好同步")
reg = gpu_pref._REG_PATH
gpu_pref._REG_PATH = r"Software\GIFManager\AuditGpuPref"
try:
    exe = gpu_pref.current_exe()
    gpu_pref.apply_preference(exe, gpu_pref.PREF_SYSTEM)
    win._gpu_accel = True
    win._gpu_pref = 0
    win._apply_gpu_preference(explicit=False)
    check("B5 startup with 'system default' leaves the entry untouched",
          gpu_pref.get_preference(exe) is None)
    gpu_pref.apply_preference(exe, gpu_pref.PREF_HIGH)
    win._apply_gpu_preference(explicit=False)
    check("B5 startup with accel on does not DELETE an existing entry",
          gpu_pref.get_preference(exe) == gpu_pref.PREF_HIGH)
    win._gpu_accel = False
    win._apply_gpu_preference(explicit=True)
    check("B5 explicit OK clears the entry (switch turned off)",
          gpu_pref.get_preference(exe) is None)
    win._gpu_accel = True
    win._gpu_pref = gpu_pref.PREF_HIGH
    win._apply_gpu_preference(explicit=True)
    check("B5 explicit OK rewrites it", gpu_pref.get_preference(exe)
          == gpu_pref.PREF_HIGH)
finally:
    gpu_pref._REG_PATH = reg

check("B19 legacy cleanup only targets the app's own launcher",
      gpu_pref.legacy_exe() == "" or
      os.path.basename(gpu_pref.legacy_exe()).lower() in
      ("main.py", "main.pyw", "gifmanager.py", "gifmanager.pyw"),
      repr(gpu_pref.legacy_exe()))

# ---------------------------------------------------------------- C1
print("\n[C1] private thread pool teardown / 私有线程池收尾")
check("C1 _ThumbLoader has a real shutdown() that drains the pool",
      "waitForDone" in inspect.getsource(type(_loader).shutdown))
src_run = inspect.getsource(ei._LoadTask.run)
check("C1 _LoadTask.run guards the emit with shiboken.isValid",
      "isValid" in src_run and "RuntimeError" in src_run)
check("C1 the loader is drained on aboutToQuit",
      "aboutToQuit" in inspect.getsource(mw_mod.MainWindow._connect_signals))
check("C1 the adapter probe uses an owned, drainable pool",
      "_gpu_pool" in inspect.getsource(mw_mod.MainWindow._stop_gpu_adapter_probe)
      and "waitForDone" in inspect.getsource(
          mw_mod.MainWindow._stop_gpu_adapter_probe))

# ---------------------------------------------------------------- B8
print("\n[B8] no blocking probes on the GUI thread / GUI 线程不阻塞")
check("B8 list_adapters is off the GUI thread in the dialog",
      "QThreadPool" in inspect.getsource(_sd.SettingsDialog._refresh_gpu_adapters))
check("B8 the ffmpeg test is off the GUI thread",
      "QThreadPool" in inspect.getsource(_sd.SettingsDialog._check_ffmpeg))
check("B8 list_adapters uses a short timeout and forces UTF-8",
      "timeout=5" in inspect.getsource(gpu_pref.list_adapters)
      and "Text.Encoding" in inspect.getsource(gpu_pref.list_adapters))

# ---------------------------------------------------------------- B13
print("\n[B13] animation survives with ffmpeg disabled / 停用 ffmpeg 不丢动画")
frames = [Image.new("RGB", (32, 32), (i * 70 % 256, 30, 160))
          for i in range(4)]
anim = os.path.join(TMP, "anim.webp")
frames[0].save(anim, save_all=True, append_images=frames[1:], duration=100,
               loop=0)
gif_converter.set_ffmpeg_config(path="", enabled=False)
out = os.path.join(TMP, "anim.gif")
ok = gif_converter.convert_to_gif(anim, out)
with Image.open(out) as im:
    nframes = getattr(im, "n_frames", 1)
check("B13 animated webp keeps all frames without ffmpeg",
      ok and nframes == len(frames), f"ok={ok} frames={nframes}")
gif_converter.set_ffmpeg_config(path="", enabled=True)

# ---------------------------------------------------------------- B3
print("\n[B3] pooled cards stop playing / 池卡停止播放")
card = EmojiItem(dict(dm.get_emojis_by_group(gid)[0]), dm, None,
                 show_name=True)
card.show()
flush(60)
card._playing = True
card._frames = ["x"]
card._play_timer = ei.QTimer()
card._play_timer.start(50)
card._stop_gif()
check("B3 _stop_gif stops the playback timer", not card._play_timer.isActive())
check("B3 _stop_gif drops the decoded frames", card._frames is None)
check("B3 _stop_gif clears the playing flag", card._playing is False)
check("B3 stop_animation is the same complete teardown",
      "_stop_gif" in inspect.getsource(EmojiItem.stop_animation)
      and "_playing = False" not in inspect.getsource(
          EmojiItem.stop_animation).replace("self._stop_gif()", ""))
card.deleteLater()

# ---------------------------------------------------------------- B2
print("\n[B2] pooled cards honour the show-name setting / 池卡遵守名称设置")
sa = QScrollArea()
sa.resize(700, 500)
sa.setWidgetResizable(True)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = gid
sa.setWidget(grid)
sa.show()
for _ in range(4):
    app.processEvents()
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
flush(120)
for c in list(grid._items[:3]):
    grid._pool_put(c)
    grid._items.remove(c)
pooled_before = len(grid._card_pool)
check("B2 pool holds cards before the setting changes", pooled_before > 0,
      pooled_before)
take = grid._pool_take({"id": 999999, "filename": "", "text_content": ""})
check("B2 _pool_take still works for image emojis", take is not None)
if take is not None:
    grid._items.append(take)
grid.set_show_emoji_name(not grid._show_emoji_name)
flush(120)
check("B2 changing show-name clears the pool", len(grid._card_pool) == 0,
      len(grid._card_pool))
check("B2 all live cards carry the new setting",
      all(c._show_name == grid._show_emoji_name for c in grid._items))
grid.set_show_emoji_name(True)
flush(80)
mismatch = 0
for c in list(grid._items[:2]):
    c._show_name = not grid._show_emoji_name
    grid._pool_put(c)
    grid._items.remove(c)
taken = grid._pool_take({"id": 999998, "filename": "", "text_content": ""})
mismatch = 1 if taken is not None else 0
check("B2 a pooled card built for the other setting is discarded",
      mismatch == 0, f"taken={taken}")

# ---------------------------------------------------------------- B10
print("\n[B10] filtered view never rewrites the group layout / 过滤态不改写整组布局")
grid._filter_keyword = "abc"
before_cols = {int(e["col_index"]) for e in dm.get_emojis_by_group(gid)}
check("B10 _check_column_merge is a no-op while filtering",
      grid._check_column_merge() is False)
check("B10 auto_fill_columns is a no-op while filtering",
      grid.auto_fill_columns() is False)
after_cols = {int(e["col_index"]) for e in dm.get_emojis_by_group(gid)}
check("B10 the stored column layout is unchanged",
      before_cols == after_cols, f"{before_cols} -> {after_cols}")
grid._filter_keyword = ""

# ---------------------------------------------------------------- B17/B18
print("\n[B17/B18] index + play set hygiene / 索引与播放集合")
grid._thumb_index = {("thumb:k"): [object()]}
grid._playing_gifs = {12345}
grid.load_emojis([], "image")
flush(60)
check("B17 an empty load clears _thumb_index", grid._thumb_index == {})
check("B17 an empty load clears _playing_gifs", grid._playing_gifs == set())
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
flush(80)
src_vis = inspect.getsource(EmojiGridWidget._update_visible_gifs)
check("B18 the parallel play count is still bounded",
      "min(len(visible)" in src_vis, src_vis[:0])
check("B17 recycled cards are dropped from the play set",
      "_playing_gifs.discard" in inspect.getsource(EmojiGridWidget._pool_put))

# ---------------------------------------------------------------- B9
print("\n[B9] selection chain / 选中链路")
check("B9 the move menu is cached, not rebuilt per card",
      "_edit_move_menu" in inspect.getsource(mw_mod.MainWindow._update_edit_count)
      and "_rebuild_edit_move_menu" not in inspect.getsource(
          mw_mod.MainWindow._update_edit_count))
check("B9 select-all batches the selection_changed signal",
      "set_all_selection" in inspect.getsource(
          mw_mod.MainWindow._edit_select_all)
      and "_selection_batch" in inspect.getsource(
          EmojiGridWidget._on_selection_toggled))
emits = []
grid.enter_edit_mode()
grid.selection_changed.connect(lambda n: emits.append(n))
grid.set_all_selection(True)
check("B9 select-all emits selection_changed exactly once",
      len(emits) == 1, emits)
check("B9 every data item is selected",
      grid.selection_count() == len(grid._data),
      f"{grid.selection_count()} / {len(grid._data)}")
emits.clear()
grid.set_all_selection(False)
check("B9 clear-all emits once and empties the selection",
      len(emits) == 1 and grid.selection_count() == 0, emits)
grid.exit_edit_mode()

# ---------------------------------------------------------------- B20
print("\n[B20] All-view delete removes every copy / 全部视图删除所有副本")
gid_a = dm.create_group("DupA", "image")
gid_b = dm.create_group("DupB", "image")
dup = os.path.join(src_dir, "dup.gif")
# A distinct SIZE keeps this fixture's content hash unique — the other fixtures
# are 40x40, and a hash collision would make the expansion (correctly) include
# their rows too. / 用不同尺寸保证该素材的内容哈希唯一：其他素材是 40x40，
# 一旦哈希相撞，展开（正确地）会把它们的行也包含进来。
make_gif(dup, 777, size=(36, 36))
dm.import_emoji(gid_a, dup, auto_convert=False)
dm.import_emoji(gid_b, dup, auto_convert=False)
rows = dm.get_all_emojis()
target = [e for e in rows if "Dup" in ""]  # placeholder, resolved below
dup_rows = dm._conn.execute(
    "SELECT id, content_hash FROM emojis WHERE group_id IN (?,?)",
    (gid_a, gid_b)).fetchall()
check("B20 the same file is stored in both groups", len(dup_rows) == 2)
expanded = dm.ids_sharing_content_hash([dup_rows[0][0]])
check("B20 the selection expands to every row with the same hash",
      set(expanded) == {r[0] for r in dup_rows}, expanded)
for eid in expanded:
    dm.delete_emoji(eid)
left = dm._conn.execute(
    "SELECT COUNT(*) FROM emojis WHERE group_id IN (?,?)",
    (gid_a, gid_b)).fetchone()[0]
check("B20 no copy is left behind", left == 0, left)

# ---------------------------------------------------------------- B15/B16/B21
print("\n[B15/B16/B21] hover / marquee / sweep guards / 悬停、跑马灯与扫选护栏")
src_restore = inspect.getsource(EmojiItem._restore_neighbor_cards)
check("B15 restore skips cards no longer tracked by the grid",
      "_items" in src_restore and "live" in src_restore)
src_enter = inspect.getsource(EmojiItem.enterEvent)
check("B16 the marquee watchdog singleShot has a receiver context",
      "QTimer.singleShot(self.NAME_SCROLL_RETRY_MS, self," in src_enter)
check("B16 the layout retry is bounded",
      "_name_scroll_retries" in inspect.getsource(EmojiItem._start_name_scroll))
src_leave = inspect.getsource(EmojiItem.leaveEvent)
check("B21 leaving does not cancel an ACTIVE sweep",
      "if not self._range_select_active:" in src_leave, src_leave[:0])

# ---------------------------------------------------------------- B4
print("\n[B4] name width + elide memo / 名称宽度与截断缓存")
c2 = EmojiItem(dict(dm.get_emojis_by_group(gid)[0]), dm, None, show_name=True)
c2._name_full = "gm_conv_f4df2f6d"
avail_unlaid = c2._name_available_width()
check("B4 an unlaid-out 100px label width is rejected",
      avail_unlaid != c2._name_label.width() or c2._name_label.width() == 0,
      f"avail={avail_unlaid} lbl={c2._name_label.width()}")
c2.resize(c2.card_size(), c2.card_height(True))
c2.show()
flush(80)
check("B4 once laid out the label width is used",
      c2._name_available_width() == c2._name_label.width(),
      f"avail={c2._name_available_width()} lbl={c2._name_label.width()}")
memo = c2._elide_cache
check("B4 the memo key carries the resolved font",
      memo is not None and len(memo) == 4 and "…" in str(memo[3]) or
      (memo is not None and isinstance(memo[2], str) and memo[2]),
      memo)
c2.deleteLater()

# ---------------------------------------------------------------- B14
print("\n[B14] language switch re-fits wrapped hints / 语言切换重排换行提示")
check("B14 refresh_translations schedules the fit pass",
      "_schedule_fit" in inspect.getsource(_sd.SettingsDialog.refresh_translations))

# ---------------------------------------------------------------- teardown
# Drain BOTH pools (the loader owns one; the adapter/ffmpeg probes use the
# global one) and the deferred deletes before drain_and_exit(), otherwise a worker
# still running at interpreter shutdown shows up as an intermittent
# 0xC0000005 exit AFTER the summary line.
# 结束前排空两个线程池（加载器自有池 + 显卡/ffmpeg 探测用的全局池）与延迟删除，
# 否则解释器退出时仍在运行的 worker 会在汇总行之后表现为偶发 0xC0000005。
from PySide6.QtCore import QThreadPool, QCoreApplication, QEvent  # noqa: E402

_loader.shutdown(3000)
QThreadPool.globalInstance().clear()
QThreadPool.globalInstance().waitForDone(3000)
app.processEvents()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
app.processEvents()
print("\n" + "=" * 62)
print(f"PASS {len(PASS)} | FAIL {len(FAIL)}")
for f in FAIL:
    print("  FAILED: " + f)
print("RESULT", "OK" if not FAIL else "NG")
sys.stdout.flush()
drain_and_exit(0 if not FAIL else 1)
