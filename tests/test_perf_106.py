"""Performance pass regression tests (1.0.6).
Lazy-loader card reuse pool + file-probe cache + group-name cache.
性能优化回归测试（1.0.6）——懒加载卡片复用池 + 文件探测缓存 + 分组名缓存。"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="perf106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PIL import Image
from PySide6.QtWidgets import QApplication, QScrollArea, QLabel
from PySide6.QtCore import Qt, QSettings, QCoreApplication, QEvent

# --- settings isolation -------------------------------------------------
# NEVER touch the user's real QSettings key. An earlier version of this test
# called QSettings("GIFManager", "GIFManager").clear(), which wiped the real
# registry key -- it silently reset "窗口置顶", the chosen GPU and the window
# geometry. MainWindow now builds its settings through _new_settings(), so the
# test can redirect it to a throwaway INI file instead.
# / 绝不触碰用户真实的 QSettings 键。本测试早期版本调用了
# QSettings("GIFManager","GIFManager").clear()，清空了真实注册表键——静默重置
# 了"窗口置顶"、已选显卡与窗口几何。MainWindow 现在通过 _new_settings() 构建设置
# 对象，测试据此改为指向一个临时 INI 文件。
from tests._iso import isolate_settings, drain_and_exit  # noqa: E402

_ISO_INI = isolate_settings()
# Snapshot the REAL key (read-only) so the test can prove it never touched it /
# 只读快照真实键，使测试能证明自己从未碰过它
_REAL_SETTINGS = QSettings("GIFManager", "GIFManager")
_REAL_KEYS_BEFORE = sorted(_REAL_SETTINGS.allKeys())

app = QApplication.instance() or QApplication(sys.argv)

from app.models.data_manager import DataManager
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.emoji_item import (
    EmojiItem, _probe_file, clear_file_probe_cache, _file_probe_cache,
)

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + ((" | " + detail) if detail else ""))


def make_gif(path, seed, size=(64, 64)):
    frames = [Image.new("RGB", size,
                        ((seed * 37 + j * 11) % 256, (seed * 53) % 256, 180))
              for j in range(3)]
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=80, loop=0)


def make_png(path, seed):
    Image.new("RGB", (48, 48), ((seed * 17) % 256, 90, 200)).save(path)


# ---------------------------------------------------------------- fixtures
N = 90
dm = DataManager()
gid = dm.create_group("Perf", "image")
src_dir = os.path.join(TMP, "src")
os.makedirs(src_dir, exist_ok=True)
for i in range(N):
    p = os.path.join(src_dir, f"s{i}.gif")
    make_gif(p, i)
    dm.import_emoji(gid, p, auto_convert=False)

from app.main_window import MainWindow  # noqa: E402  (needs QApplication first)
win = MainWindow()
win.resize(1000, 700)
win.show()
for _ in range(6):
    app.processEvents()
win.emoji_grid.current_group_id = gid
win.emoji_grid.load_emojis(dm.get_emojis_by_group(gid), "image")
for _ in range(8):
    app.processEvents()
grid = win.emoji_grid

# ------------------------------------------------------------------ probe cache
print("\n[1] file probe cache / 文件探测缓存")
png = os.path.join(src_dir, "p.png")
make_png(png, 3)
missing = os.path.join(src_dir, "nope.gif")

calls = {"n": 0}
real_isfile = os.path.isfile


def counting_isfile(p):
    calls["n"] += 1
    return real_isfile(p)


os.path.isfile = counting_isfile
try:
    clear_file_probe_cache()
    r1 = _probe_file(png)
    r2 = _probe_file(png)
    after_first = calls["n"]
    r3 = _probe_file(png)
    check("_probe_file: PNG -> (exists, not gif)",
          r1 == (True, False), f"got {r1}")
    check("_probe_file: repeated call is cached (no extra isfile)",
          r3 == r1 and calls["n"] == after_first,
          f"isfile calls {calls['n']} vs {after_first}")
    clear_file_probe_cache()
    rg = _probe_file(os.path.join(src_dir, "s0.gif"))
    check("_probe_file: GIF -> (exists, gif)", rg == (True, True), f"got {rg}")
    rm = _probe_file(missing)
    check("_probe_file: missing -> (False, False)", rm == (False, False),
          f"got {rm}")
    check("_probe_file: missing path does not crash on empty",
          _probe_file("") == (False, False))
    clear_file_probe_cache()
    check("clear_file_probe_cache empties the dict", len(_file_probe_cache) == 0)

    # load_emojis must drop the probe cache (files may have been rewritten)
    # load_emojis 必须清空探测缓存（文件可能已被重写）
    _probe_file(png)
    check("probe cache populated before reload", len(_file_probe_cache) > 0)
    grid.load_emojis(dm.get_emojis_by_group(gid), "image")
    for _ in range(4):
        app.processEvents()
    check("load_emojis clears the probe cache", len(_file_probe_cache) == 0,
          f"len={len(_file_probe_cache)}")
finally:
    os.path.isfile = real_isfile
clear_file_probe_cache()

# ---------------------------------------------------------------- group cache
print("\n[2] group name cache / 分组名缓存")
check("group_name returns the group name", dm.group_name(gid) == "Perf",
      f"got {dm.group_name(gid)}")
check("group_name of a missing id -> None", dm.group_name(10 ** 9) is None)
queries = {"n": 0}
real_get_group = DataManager.get_group


def counting_get_group(self, gid_):
    queries["n"] += 1
    return real_get_group(self, gid_)


DataManager.get_group = counting_get_group
try:
    for _ in range(50):
        dm.group_name(gid)
    check("50 cached group_name calls -> 0 SQL lookups", queries["n"] == 0,
          f"queries={queries['n']}")

    ok = dm.rename_group(gid, "PerfRenamed")
    check("rename_group succeeded", ok is True)
    check("rename_group invalidated the cache (new name returned)",
          dm.group_name(gid) == "PerfRenamed", f"got {dm.group_name(gid)}")
    # emoji_filepath must follow the renamed folder / emoji_filepath 必须跟随
    # 重命名后的目录
    em = dm.get_emojis_by_group(gid)[0]
    fp = dm.emoji_filepath(em)
    check("emoji_filepath follows the renamed group dir",
          bool(fp) and "PerfRenamed" in fp, f"got {fp}")
    check("emoji_filepath target exists", os.path.isfile(fp))
    dm.rename_group(gid, "Perf")
finally:
    DataManager.get_group = real_get_group

gid2 = dm.create_group("Second", "image")
check("create_group invalidated the cache", dm.group_name(gid2) == "Second")
check("delete_group invalidated the cache",
      dm.delete_group(gid2) is True and dm.group_name(gid2) is None)

# --------------------------------------------------------------- card reuse
print("\n[3] lazy-loader card reuse pool / 懒加载卡片复用池")
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
for _ in range(8):
    app.processEvents()
sb = grid._find_scroll().verticalScrollBar()
check("the grid is actually scrollable (scroll range > 0)",
      sb.maximum() > 0, f"maximum={sb.maximum()}")
live_before = len(grid._items)
reused_before = grid._pool_reused
for k in range(24):
    sb.setValue(int(sb.maximum() * k / 24))
    for _ in range(2):
        app.processEvents()
    grid._ensure_visible(allow_decode=False)
for _ in range(6):
    app.processEvents()
check("scrolling reused pooled cards",
      grid._pool_reused > reused_before,
      f"reused {grid._pool_reused - reused_before}")
check("card count stays bounded while scrolling (no unbounded growth)",
      len(grid._items) <= live_before + 4,
      f"{len(grid._items)} vs {live_before}")
check("pool stays within its cap", len(grid._card_pool) <= grid._CARD_POOL_MAX)

# Every live card must point at the emoji the layout expects, with the right
# thumbnail path and a unique id (a recycled card that still referenced its
# previous emoji would break both).
# 每张在用的卡都必须指向布局期望的表情，缩略图路径正确且 id 唯一（复用卡若
# 仍引用上一个表情，这两项都会出错）。
ids = [c._emoji.get("id") for c in grid._items]
check("live cards have unique emoji ids", len(ids) == len(set(ids)),
      f"{len(ids)} cards, {len(set(ids))} ids")
bad_path = [c._emoji.get("id") for c in grid._items
            if c._thumb_path != dm.emoji_filepath(c._emoji)]
check("every live card's thumbnail path matches its emoji",
      not bad_path, f"mismatched ids={bad_path[:5]}")
check("no live card is hidden", not any(c.isHidden() for c in grid._items))

rects, _tw, _th, _info = grid._masonry_layout_data(grid._layout_usable())
misplaced = []
for c in grid._items:
    r = rects.get(c._emoji.get("id"))
    if r is None:
        misplaced.append((c._emoji.get("id"), "no-rect"))
    elif (c.geometry().x(), c.geometry().y()) != (r[0], r[1]):
        misplaced.append((c._emoji.get("id"), (c.geometry().x(), c.geometry().y(), r)))
check("every live card sits at its data rect", not misplaced,
      f"bad={misplaced[:3]}")

# Names must be re-derived for the new emoji, never left over / 名称必须按新
# 表情重新推导，不能残留
name_bad = []
for c in grid._items:
    if not c._show_name:
        continue
    lbl = getattr(c, "_name_label", None)
    if lbl is None:
        name_bad.append((c._emoji.get("id"), "no-label"))
        continue
    if lbl.text() != c._elide_name(c._emoji.get("original_name", "")):
        name_bad.append((c._emoji.get("id"), lbl.text()))
check("reused cards show the name of their CURRENT emoji", not name_bad,
      f"bad={name_bad[:3]}")

# GIF flag must be recomputed for the reused emoji / GIF 标记须按复用后的表情重算
gif_bad = [c._emoji.get("id") for c in grid._items if not c.is_gif()]
check("reused cards still recognise their GIF", not gif_bad,
      f"not-gif ids={gif_bad[:5]}")

# ------------------------------------------------------- reset_for contract
print("\n[4] EmojiItem.reset_for contract / reset_for 契约")
img_em = dm.get_emojis_by_group(gid)[0]
card = EmojiItem(img_em, dm, grid._flow_container, show_name=True)
other = dict(img_em)
other["id"] = img_em["id"] + 100000
other["original_name"] = "zzz_reused_name"
other["filename"] = img_em["filename"]
check("reset_for accepts an image emoji", card.reset_for(other) is True)
card.set_checked(True)
check("precondition: set_checked(True) took effect", card.is_checked() is True)
emitted = []
card.selection_toggled.connect(lambda i, c: emitted.append((i, c)))
card.reset_for(other)
check("reset_for clears the checked state", card.is_checked() is False)
check("reset_for does not emit a spurious selection_toggled", not emitted,
      f"emitted={emitted}")
check("reset_for re-points _emoji", card._emoji["id"] == other["id"])
check("reset_for re-derives the name label",
      card._name_label.text() == card._elide_name("zzz_reused_name"),
      f"got {card._name_label.text()!r}")
check("reset_for clears the GIF byte cache", card._is_gif_file is None)
check("reset_for re-probes the file", card._thumb_path == dm.emoji_filepath(other))
check("reset_for refuses a text emoji",
      card.reset_for({"id": 1, "text_content": "hi"}) is False)
txt = EmojiItem({"id": 2, "text_content": "hello", "original_name": ""},
                dm, grid._flow_container)
check("reset_for refuses on a text card",
      txt.reset_for(other) is False)
card.deleteLater()
txt.deleteLater()
app.processEvents()

# ---------------------------------------------------------- pool cap / clear
print("\n[5] pool cap, retune and cache invalidation / 池上限、重调与缓存失效")
check("_pool_put deletes text cards instead of pooling",
      (lambda: (grid._pool_put(txt) or grid._card_pool.count(txt) == 0))())
grid._card_pool.clear()

# A pool card that cannot serve the requested emoji must be destroyed, not
# silently dropped (it would stay parented + hidden forever) /
# 无法服务目标表情的回收卡必须被销毁，而不是被静默丢弃（否则会一直挂在
# 父级上且隐藏）
for em in dm.get_emojis_by_group(gid)[:3]:
    grid._pool_put(EmojiItem(em, dm, grid._flow_container, show_name=True))
check("pool holds 3 cards before the text-em data set",
      len(grid._card_pool) == 3)
taken = grid._pool_take({"id": 999, "text_content": "text group emoji"})
check("_pool_take refuses a text emoji", taken is None)
check("refused cards are drained from the pool", len(grid._card_pool) == 0)
app.processEvents()

em_list = dm.get_emojis_by_group(gid)
pooled = []
for em in em_list[:60]:
    c = EmojiItem(em, dm, grid._flow_container, show_name=True)
    pooled.append(c)
for c in pooled:
    grid._pool_put(c)
check("pool obeys _CARD_POOL_MAX",
      len(grid._card_pool) == grid._CARD_POOL_MAX,
      f"{len(grid._card_pool)} vs {grid._CARD_POOL_MAX}")
for c in grid._card_pool:
    c.deleteLater()
grid._card_pool.clear()
for c in pooled:
    c.deleteLater()
app.processEvents()

grid._pool_put(EmojiItem(em_list[0], dm, grid._flow_container, show_name=True))
check("pool filled for the scale test", len(grid._card_pool) == 1)
grid._set_card_scale(1.25)
app.processEvents()
check("_set_card_scale clears the pool", len(grid._card_pool) == 0)
grid._set_card_scale(1.0)
app.processEvents()

# retune must follow the settings-driven hover behaviour on a reused card /
# retune 必须让复用卡跟随设置驱动的悬停行为
rc = EmojiItem(em_list[1], dm, grid._flow_container, show_name=True,
               hover_zoom=1.15, hover_enabled=True)
rc.retune(1.4, False)
check("retune applies the new zoom", abs(rc._hover_zoom - 1.4) < 1e-6)
check("retune applies the new switch", rc._hover_enabled is False)
rc.retune(1.0, True)
check("retune can re-enable hovering", rc._hover_enabled is True)
rc.deleteLater()

# ------------------------------------------------- name stylesheet re-parse
print("\n[6] name stylesheet is not re-parsed on every recycle / 名称样式表不重复解析")
ss = {"n": 0}
rc2 = EmojiItem(em_list[2], dm, grid._flow_container, show_name=True)
real_ss = QLabel.setStyleSheet
applied_font = {"size": rc2._name_font_applied}


def counting_ss(self, sheet):
    if self is getattr(rc2, "_name_label", None) and "font-size" in sheet:
        ss["n"] += 1
    return real_ss(self, sheet)


QLabel.setStyleSheet = counting_ss
try:
    for _ in range(12):
        rc2.refresh_display()
    check("12 refresh_display calls -> 0 extra setStyleSheet",
          ss["n"] == 0, f"calls={ss['n']}")
    # A real font-size change must still be applied / 真正的字号变化仍须生效
    EmojiItem.set_name_font_size(14)
    rc2.refresh_display()
    check("a real font-size change is still applied", ss["n"] == 1,
          f"calls={ss['n']}")
    check("the label really carries the new font size",
          "font-size: 14px" in rc2._name_label.styleSheet(),
          rc2._name_label.styleSheet())
finally:
    QLabel.setStyleSheet = real_ss
    EmojiItem.set_name_font_size(10)
rc2.deleteLater()

# ------------------------------------------------------------- elide cache
print("\n[7] elide measurement memo / 截断测量缓存")
rc3 = EmojiItem(dict(em_list[3], original_name="a_very_long_emoji_name_here"),
                dm, grid._flow_container, show_name=True)
rc3.show()
app.processEvents()
r_first = rc3._elide_name("a_very_long_emoji_name_here")
memo = rc3._elide_cache
r_again = rc3._elide_name("a_very_long_emoji_name_here")
check("elide result memoised", memo is not None and r_again == r_first)
check("elide memo keys on (name, width)",
      memo[0] == "a_very_long_emoji_name_here" and memo[1] > 0,
      f"memo={memo}")
check("elide still truncates a too-long name",
      r_first.endswith("…") and len(r_first) <= EmojiItem.NAME_CHAR_LIMIT + 1,
      f"got {r_first!r}")
short = rc3._elide_name("ok")
check("elide keeps a fitting name intact", short == "ok", f"got {short!r}")
rc3.deleteLater()
app.processEvents()

# -------------------------------------------------------------- selection
print("\n[8] selection state survives card reuse / 勾选状态经复用后仍正确")
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
for _ in range(6):
    app.processEvents()
grid.enter_edit_mode()
all_em = dm.get_emojis_by_group(gid)
target = all_em[-1]
grid._selection[str(target["id"])] = target
sb.setValue(sb.maximum())
for _ in range(4):
    app.processEvents()
grid._ensure_visible(allow_decode=False)
for _ in range(4):
    app.processEvents()
card_for_target = [c for c in grid._items if c._emoji["id"] == target["id"]]
check("the selected card exists after scrolling to the end",
      len(card_for_target) == 1, f"n={len(card_for_target)}")
if card_for_target:
    check("the reused/created card is checked", card_for_target[0].is_checked())
mismatch = [c._emoji["id"] for c in grid._items
            if c.is_checked() != (str(c._emoji["id"]) in grid._selection)]
check("no card is checked while its id is unselected", not mismatch,
      f"bad={mismatch[:5]}")
grid.exit_edit_mode()
grid._selection.clear()
for _ in range(4):
    app.processEvents()

# ------------------------------------------------------- mixed group switch
print("\n[9] image <-> text group switching does not orphan cards / 图文分组切换不产生孤儿卡")
tgid = dm.create_group("PerfText", "text")
dm.add_text_emoji(tgid, "文字表情一")
dm.add_text_emoji(tgid, "文字表情二")


def drain_deferred_deletes():
    # processEvents() alone does NOT run deleteLater() (DeferredDelete events
    # are only delivered by the event loop / an explicit sendPostedEvents),
    # so a naive count would report not-yet-freed widgets as orphans.
    # 单靠 processEvents() 不会执行 deleteLater()（DeferredDelete 事件只由事件
    # 循环或显式 sendPostedEvents 投递），否则未销毁的控件会被误判为孤儿。
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def orphan_count():
    # Every EmojiItem parented to the flow container must be either live or
    # pooled; anything else is a leaked, permanently hidden widget.
    # 挂在流容器下的每个 EmojiItem 必须要么在用、要么在池中，否则就是泄漏的
    # 永久隐藏控件。
    from shiboken6 import isValid
    kids = {k for k in grid._flow_container.findChildren(EmojiItem)
            if isValid(k)}
    known = {k for k in (set(grid._items) | set(grid._card_pool))
             if isValid(k)}
    return kids - known


sizes = []
# Baseline: sections [4]-[7] build cards by hand and deleteLater() them; take
# the count after draining so the pool switches below are judged on their own.
# 基线：第 [4]-[7] 节手工创建过卡片并调用了 deleteLater()；先排空再取基线，
# 使下面的分组切换只按自身行为判定。
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
drain_deferred_deletes()
baseline = len(orphan_count())
for _ in range(3):
    grid.load_emojis(dm.get_emojis_by_group(gid), "image")
    for _ in range(3):
        app.processEvents()
    grid._ensure_visible(allow_decode=False)
    grid.load_emojis(dm.get_emojis_by_group(tgid), "text")
    drain_deferred_deletes()
    sizes.append(len(orphan_count()) - baseline)
check("no orphaned cards after image->text->image switches",
      sizes[-1] == 0, f"orphans per round={sizes} (baseline={baseline})")
check("orphan count does not grow across switches (no slow leak)",
      len(set(sizes)) == 1, f"sizes={sizes} baseline={baseline}")
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
for _ in range(4):
    app.processEvents()
check("pool is empty after a text group (image cards are unusable there)",
      len(grid._card_pool) == 0, f"pool={len(grid._card_pool)}")

# ------------------------------------------------------------------ teardown
print("\n[10] settings isolation / 设置隔离")
check("the test's MainWindow uses an isolated settings file",
      os.path.normcase(os.path.abspath(win._settings.fileName()))
      == os.path.normcase(os.path.abspath(_ISO_INI)),
      f"{win._settings.fileName()} vs {_ISO_INI}")
_real_now = QSettings("GIFManager", "GIFManager")
check("the real settings key was not cleared or added to",
      sorted(_real_now.allKeys()) == _REAL_KEYS_BEFORE,
      f"before={len(_REAL_KEYS_BEFORE)} after={len(_real_now.allKeys())}")
check("the real always_on_top value is untouched",
      _real_now.value("always_on_top") == _REAL_SETTINGS.value("always_on_top"),
      f"now={_real_now.value('always_on_top')!r}")

# Let the thumbnail pool finish before exiting: drain_and_exit() below kills the
# process immediately, and a decode worker racing with the final print shows
# up as a nondeterministic 0xC0000005 exit AFTER the summary line.
# 退出前让缩略图线程池收工：下面的 drain_and_exit() 会立即结束进程，若解码线程
# 与最后的打印竞争，就会表现为汇总行之后偶发的 0xC0000005 退出码。
from app.widgets.emoji_item import _loader as _thumb_loader
_thumb_loader._pool.clear()
_thumb_loader._pool.waitForDone(3000)
try:
    dm._conn.close()
except Exception:
    pass

print("\n" + "=" * 62)
print(f"PASS {len(PASS)} | FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED: " + f)
code = 1 if FAIL else 0
print("RESULT", "OK" if code == 0 else "NG")
sys.stdout.flush()
drain_and_exit(code)
