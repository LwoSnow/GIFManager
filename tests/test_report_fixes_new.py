"""Verify the Report.md fixes:
1. Alt+wheel (global scroll) persists card scale + syncs the settings dialog
2. SmoothScroll is eased (ease-out) and completes in STEPS frames
3. marquee per-char width caching is used (no per-tick re-measure)
4. SmoothScroll QTimer has a parent (cleaned up with the widget)
5. _is_light falls back to the QSS QDialog background for non-main parents
验证 Report.md 的修复：
1. Alt+滚轮（全局滚动）持久化卡片缩放并同步设置对话框
2. 平滑滚动带 easing（ease-out）并在 STEPS 帧内完成
3. 跑马灯复用逐字符宽度缓存（不再每 tick 重新度量）
4. 平滑滚动 QTimer 有父对象（随控件回收）
5. _is_light 对非主窗口父级回退到 QSS QDialog 背景"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_reportfix_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

# Isolate QSettings and the per-app GPU preference from the real user state: a
# test must never rewrite the user's preferences (this used to reset
# "窗口置顶", the chosen GPU and the window geometry).
# 隔离 QSettings 与按应用 GPU 首选项，测试绝不重写用户真实设置（以前会重置
# "窗口置顶"、已选显卡与窗口几何）。
from tests._iso import isolate_all, drain_and_exit  # noqa: E402

isolate_all()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget, QSpinBox
from PySide6.QtCore import Qt

import app.main_window as mw
from app.main_window import SmoothScroll, MainWindow
from app.widgets.settings_dialog import SettingsDialog

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


# --- 1. SmoothScroll ease-out completes in STEPS frames and is not linear ---
sa = QScrollArea()
inner = QWidget()
inner.setMinimumHeight(3000)
sa.setWidget(inner)
sa.resize(300, 200)
sa.show()
app.processEvents()
bar = sa.verticalScrollBar()
bar.setValue(bar.maximum() // 2)
app.processEvents()
start = bar.value()
sm = SmoothScroll(sa)
# timer parented to the scroll area / 定时器以滚动区为父级
check("SmoothScroll QTimer 有父对象", sm._timer.parent() is sa)
sm.handle_wheel(-360)   # wheel DOWN -> value increases by 360 / 向下滚 -> 增大
seen = []
for _ in range(SmoothScroll.STEPS + 1):
    seen.append(bar.value())
    app.processEvents()
    sm._tick()
# The eased path: leading frames jump ahead faster than trailing ones.
deltas = [seen[i + 1] - seen[i] for i in range(len(seen) - 1)]
# Verify it reached the target (start+360 capped) / 到达终点
check("ease 到达终点", bar.value() == min(start + 360, bar.maximum()), bar.value())
# Verify not constant: first deltas larger than late deltas (ease-out).
if deltas:
    early = max(deltas[:3])
    late = max(deltas[-3:])
    check("ease-out 先快后慢", early > late, f"early={early} late={late}")

# --- 2. Alt+wheel persists + syncs settings dialog (item 7) ---
w = MainWindow()
w._theme = "dark"
w.show()
app.processEvents()
old_scale = w._card_scale
# simulate an open settings dialog / 模拟打开的设置对话框
dlg = SettingsDialog(card_scale=old_scale, name_font_size=10)
w._settings_dialog = dlg
# Alt+wheel scroll down (delta>0 grows) / Alt+滚轮向下（放大）
w._on_global_scroll(1)   # delta>0 -> +2%
app.processEvents()
check("Alt+滚轮更新 _card_scale", abs(w._card_scale - old_scale - 0.02) < 1e-6,
      f"{old_scale:.2f}->{w._card_scale:.2f}")
# persisted to settings QSettings / 持久化到 QSettings
persisted = float(w._settings.value("card_scale", 1.0))
check("Alt+滚轮已持久化 card_scale", abs(persisted - w._card_scale) < 1e-6, persisted)
# settings dialog spin synced / 设置对话框输入框已同步
check("设置对话框 spin 同步",
      abs(dlg._spin_card_size.value() / 100.0 - w._card_scale) < 1e-6,
      dlg._spin_card_size.value())
w._settings_dialog = None
w.close()
app.processEvents()

# --- 3. marquee char-width cache used (item 1) ---
import inspect
import app.widgets.emoji_item as ei
src = inspect.getsource(ei.EmojiItem._tick_name_scroll)
check("跑马灯复用字符宽度缓存", "_scroll_char_widths" in src)
check("无每 tick 重新度量", "cache.get(ch)" in src or "cache[ch]" in src)

# --- 4. dead code removed (item 8) ---
src2 = inspect.getsource(ei.EmojiItem)
check("死代码 _name_scroll_dir 已删除", "_name_scroll_dir" not in src2)

# --- 5. _is_light QSS fallback (item 4 robustness) ---
from app.theme.light_theme import QSS as LIGHT_QSS
from app.theme.dark_theme import QSS as DARK_QSS
from app.widgets.rename_dialog import _is_light
app.setStyleSheet(LIGHT_QSS)
check("无 _theme 父级+浅色 QSS -> light", _is_light(None) is True)
app.setStyleSheet(DARK_QSS)
check("无 _theme 父级+深色 QSS -> dark", _is_light(None) is False)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\nReport 修复验证: {n_pass}/{len(RES)} 通过")
return_code = 0 if n_pass == len(RES) else 1
drain_and_exit(return_code)
