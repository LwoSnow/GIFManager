"""Test card scale feature: Alt+scroll and settings UI.
测试卡片缩放功能：Alt+滚轮和设置界面。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_scale_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt, QSize
from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.widgets.emoji_grid import EmojiGridWidget

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    RES.append((name, ok))
    print(f"  [{status}] {name}" + (f" ({detail})" if detail and not ok else ""))


print("=== Card Scale Test ===")

# Setup
dm = DataManager()

# Create test images
for i in range(6):
    img = Image.new("RGB", (64, 64), color=(i * 40, 100, 200 - i * 30))
    path = os.path.join(TMP, f"test_{i}.png")
    img.save(path)

gid = dm.create_group("TestGroup", "image")
for i in range(6):
    dm.import_emoji(gid, os.path.join(TMP, f"test_{i}.png"), auto_convert=False)
emojis = dm.get_emojis_by_group(gid)

# Create grid inside a scroll area (simulates real window)
scroll = QScrollArea()
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = gid
grid._card_scale = 1.0
EmojiItem._card_scale = 1.0
scroll.setWidget(grid)
scroll.setWidgetResizable(True)
scroll.resize(600, 600)
scroll.show()
app.processEvents()

# Force load all emojis (bypass lazy loading)
grid._data = list(emojis)
from app.widgets.emoji_item import _loader, _thumb_key
for em in emojis:
    card = EmojiItem(em, dm, grid,
                     preview_limits=(100, 200),
                     show_name=True,
                     hover_zoom=1.15,
                     hover_enabled=True)
    grid._items.append(card)
    grid._flow.addWidget(card)
grid._flow.invalidate()
grid._flow.activate()
grid._flow.relayout()
app.processEvents()

print("\n--- Test 1: Initial card size (scale=1.0) ---")
card_size_100 = EmojiItem.card_size()
check("card_size() == 100", card_size_100 == 100, card_size_100)

thumb_100 = EmojiItem.thumb_size()
check("thumb_size() == 84", thumb_100 == 84, thumb_100)

card_h_100 = EmojiItem.card_height(True)
check("card_height(show_name=True) == 122", card_h_100 == 122, card_h_100)

if grid._items:
    card = grid._items[0]
    tl = card._thumb_label
    check("card fixedWidth == 100", card.width() == 100, card.width())
    check("thumb_label fixedWidth == 84", tl.width() == 84, tl.width())
else:
    check("grid has items", False, "0 items")

print("\n--- Test 2: Scale to 1.5 ---")
grid._set_card_scale(1.5)
app.processEvents()

check("card_size() == 150", EmojiItem.card_size() == 150, EmojiItem.card_size())
check("thumb_size() == 126", EmojiItem.thumb_size() == 126, EmojiItem.thumb_size())
check("card_height(show_name=True) == 172", EmojiItem.card_height(True) == 172,
      EmojiItem.card_height(True))

if grid._items:
    card = grid._items[0]
    tl = card._thumb_label
    check("card fixedWidth == 150", card.width() == 150, card.width())
    check("thumb_label fixedWidth == 126", tl.width() == 126, tl.width())
    # Pixmap should be scaled to match new thumb size
    pix = tl.pixmap()
    if pix and not pix.isNull():
        check("pixmap width == 126", pix.width() == 126, pix.width())
    else:
        check("pixmap exists", False, "null pixmap")
else:
    check("grid has items after scale", False, "0 items")

print("\n--- Test 3: Scale back to 1.0 ---")
grid._set_card_scale(1.0)
app.processEvents()

check("card_size() back == 100", EmojiItem.card_size() == 100, EmojiItem.card_size())
if grid._items:
    card = grid._items[0]
    check("card fixedWidth back == 100", card.width() == 100, card.width())
else:
    check("grid has items after scale back", False, "0 items")

print("\n--- Test 4: Scale 0.5 (min) and 2.0 (max) ---")
grid._set_card_scale(0.5)
app.processEvents()
check("card_size() at 0.5 == 50", EmojiItem.card_size() == 50, EmojiItem.card_size())

grid._set_card_scale(2.0)
app.processEvents()
check("card_size() at 2.0 == 200", EmojiItem.card_size() == 200, EmojiItem.card_size())

# Restore
grid._set_card_scale(1.0)
app.processEvents()

print("\n--- Test 5: GlobalScrollWatcher hook install/remove ---")
from app.widgets.hotkey_manager import GlobalScrollWatcher
watcher = GlobalScrollWatcher()
received = []

def on_scroll(delta):
    received.append(delta)

watcher.start(on_scroll)
# The low-level hook must have a REAL handle (a falsy 0 means
# SetWindowsHookExW failed — passing GetModuleHandleW(None) used to make it
# fail with ERROR_MOD_NOT_FOUND). / 低级钩子必须有真实句柄（0 表示
# SetWindowsHookExW 失败——此前传 GetModuleHandleW(None) 会以
# ERROR_MOD_NOT_FOUND 失败）。
check("hook installed (real handle)", bool(watcher._hook), watcher._hook)

watcher.stop()
check("hook removed", watcher._hook is None)

print("\n--- Test 6: Settings dialog card_scale ---")
from app.widgets.settings_dialog import SettingsDialog
dlg = SettingsDialog(card_scale=1.25)
app.processEvents()
check("getter == 1.25", abs(dlg.card_scale() - 1.25) < 0.01, dlg.card_scale())

dlg._spin_card_size.setValue(75)
check("getter == 0.75", abs(dlg.card_scale() - 0.75) < 0.01, dlg.card_scale())

dlg._spin_card_size.setValue(200)
check("getter == 2.0", abs(dlg.card_scale() - 2.0) < 0.01, dlg.card_scale())

# Summary
passed = sum(1 for _, ok in RES if ok)
total = len(RES)
print(f"\n=== Results: {passed}/{total} passed ===")
if passed < total:
    for name, ok in RES:
        if not ok:
            print(f"  FAILED: {name}")
    sys.exit(1)
