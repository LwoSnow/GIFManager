"""Regression tests for the experimental GPU (OpenGL) viewport.

Contract:
  * OFF by default — the viewport must stay a plain QWidget (this protects every
    existing user from the mechanism that used to crash the renderer);
  * when enabled AND acceleration is on, MainWindow installs a GridGlViewport as
    the scroll area's viewport at startup;
  * the surface carries the theme colour (no black first paint);
  * it is never swapped at runtime — changing the setting only takes effect at
    the next launch, and the window says so;
  * a platform without usable OpenGL falls back instead of breaking the grid.
实验性 GPU（OpenGL）视口的回归测试。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="gpuvp106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from tests._iso import isolate_settings, isolate_gpu_pref, drain_and_exit

ini = isolate_settings()
isolate_gpu_pref()
app = QApplication.instance() or QApplication(sys.argv)

import app.main_window as mw_mod
from app.widgets.gl_viewport import GridGlViewport
from app.widgets.settings_dialog import SettingsDialog

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name
          + ((" | " + str(detail)) if detail else ""))


def settle(ms=250):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def fresh_settings():
    s = QSettings(ini, QSettings.Format.IniFormat)
    s.clear()
    s.sync()


# ------------------------------------------------------- 1. default OFF
print("\n[1] default is OFF (CPU viewport) / 默认关闭")
fresh_settings()
win = mw_mod.MainWindow()
win.show()
settle()
check("gpu_viewport defaults to False", win._gpu_viewport is False,
      win._gpu_viewport)
check("the viewport is NOT an OpenGL widget by default",
      not isinstance(win._scroll_area.viewport(), QOpenGLWidget),
      type(win._scroll_area.viewport()).__name__)
check("nothing was installed", win._gpu_viewport_installed is False)
win.close()
settle(100)

# ------------------------------------------- 2. enabled + accel -> installed
print("\n[2] enabled with acceleration installs the GL viewport / 开启后安装")
fresh_settings()
s = QSettings(ini, QSettings.Format.IniFormat)
s.setValue("gpu_viewport", True)
s.setValue("gpu_accel", True)
s.setValue("gpu_pref", 2)
s.sync()
win2 = mw_mod.MainWindow()
win2.show()
settle(500)
vp = win2._scroll_area.viewport()
check("the setting was loaded", win2._gpu_viewport is True)
check("the offscreen platform is detected as having no OpenGL",
      win2._gpu_viewport_supported() is False,
      win2._platform_name())
check("so it stays on the CPU viewport instead of breaking the grid",
      win2._gpu_viewport_installed is False
      and not isinstance(vp, QOpenGLWidget), type(vp).__name__)
check("the grid is still alive and connected",
      win2.emoji_grid is not None and win2.emoji_grid.parent() is vp,
      type(win2.emoji_grid.parent()).__name__)

# Force the install path anyway: on this platform the GL context will not come
# up, but the SWAP itself must not destroy the grid (setViewport() deletes the
# old viewport, which used to take the grid with it).
# 仍然强制走一次安装路径：本平台拿不到 GL 上下文，但替换本身绝不能把网格销毁
# （setViewport() 会删除旧视口，而网格曾是它的子控件）。
win2._gpu_viewport_supported = lambda: True
win2._apply_gpu_viewport()
settle(300)
vp2 = win2._scroll_area.viewport()
check("the viewport was replaced with a GridGlViewport",
      isinstance(vp2, GridGlViewport), type(vp2).__name__)
check("the grid SURVIVED the swap (parented to the new viewport)",
      win2.emoji_grid is not None and win2.emoji_grid.parent() is vp2,
      type(win2.emoji_grid.parent()).__name__)
check("its signals are still connectable (not a deleted C++ object)",
      win2.emoji_grid.emoji_clicked is not None)
check("the surface carries a theme colour, not black",
      vp2.palette().color(vp2.backgroundRole()).name().upper() != "#000000",
      vp2.palette().color(vp2.backgroundRole()).name())
check("autoFillBackground is on (background always painted)",
      vp2.autoFillBackground())
check("NoPartialUpdate avoids stale/black regions",
      vp2.updateBehavior() == QOpenGLWidget.UpdateBehavior.NoPartialUpdate)
win2._theme = "light"
win2._apply_viewport_background()
check("the theme background follows a theme change",
      vp2.palette().color(vp2.backgroundRole()) == QColor("#F2F3F5"),
      vp2.palette().color(vp2.backgroundRole()).name())
win2._theme = "dark"
win2._apply_viewport_background()
check("and back for the dark theme",
      vp2.palette().color(vp2.backgroundRole()) == QColor("#1E1E1E"),
      vp2.palette().color(vp2.backgroundRole()).name())
# the deferred verifier must roll back when there is no context /
# 延迟核实发现没有上下文时必须回退
win2._verify_gpu_viewport()
settle(200)
check("a missing GL context rolls back to the CPU viewport",
      win2._gpu_viewport_installed is False
      and not isinstance(win2._scroll_area.viewport(), QOpenGLWidget),
      type(win2._scroll_area.viewport()).__name__)
check("the grid still works after the rollback",
      win2.emoji_grid is not None
      and win2.emoji_grid.parent() is win2._scroll_area.viewport())
win2.close()
settle(100)

# ------------------------------------- 3. accel off -> not installed
print("\n[3] acceleration off means no GPU surface / 加速关闭则不安装")
win2.close()
settle(100)
fresh_settings()
s = QSettings(ini, QSettings.Format.IniFormat)
s.setValue("gpu_viewport", True)
s.setValue("gpu_accel", False)
s.sync()
win3 = mw_mod.MainWindow()
win3.show()
settle(250)
check("the master switch stays authoritative",
      win3._gpu_viewport_installed is False
      and not isinstance(win3._scroll_area.viewport(), QOpenGLWidget),
      type(win3._scroll_area.viewport()).__name__)

# ------------------------------- 4. runtime change only marks a restart
print("\n[4] changing it at runtime needs a restart / 运行时修改需重启")
fresh_settings()
win4 = mw_mod.MainWindow()
win4.show()
# showEvent defers the hotkey registration by 200ms; let that timer fire first,
# otherwise its offscreen failure notice lands on top of the restart notice and
# this check fails for no real reason.
# showEvent 会把快捷键注册延后 200ms；先让该定时器跑完，否则它在离屏下的失败提示
# 会盖住重启提示，让本项检查无谓失败。
settle(500)
check("not installed at startup (setting off)",
      win4._gpu_viewport_installed is False)
before = win4._scroll_area.viewport()
dlg = SettingsDialog(gpu_accel=True, gpu_viewport=True)
win4._apply_settings(dlg)
settle(200)
check("the new value is stored", win4._gpu_viewport is True
      and QSettings(ini, QSettings.Format.IniFormat).value(
          "gpu_viewport", False, type=bool) is True)
check("the viewport was NOT swapped at runtime (restart required)",
      win4._scroll_area.viewport() is before,
      type(win4._scroll_area.viewport()).__name__)
check("the user is told a restart is needed",
      "重启" in win4.status_bar.currentMessage()
      or "restart" in win4.status_bar.currentMessage().lower(),
      win4.status_bar.currentMessage()[:60])

# ------------------------------------------------- 5. dialog control
print("\n[5] settings dialog control / 设置对话框控件")
d0 = SettingsDialog(gpu_accel=True)
check("the switch exists and defaults to off", d0.gpu_viewport() is False)
d1 = SettingsDialog(gpu_accel=True, gpu_viewport=True)
check("it round-trips", d1.gpu_viewport() is True)
d2 = SettingsDialog(gpu_accel=False, gpu_viewport=True)
check("it is disabled while acceleration is off",
      not d2._cb_gpu_viewport.isEnabled())
d3 = SettingsDialog(gpu_accel=True, gpu_viewport=True)
check("it is enabled while acceleration is on",
      d3._cb_gpu_viewport.isEnabled())
d3._cb_gpu_viewport.setChecked(False)
d3._on_ok()
check("turning it off is reported by the getter", d3.gpu_viewport() is False)
for d in (d0, d1, d2, d3):
    d.deleteLater()

print("\n" + "=" * 62)
print(f"PASS {len(PASS)} | FAIL {len(FAIL)}")
for f in FAIL:
    print("  FAILED: " + f)
print("RESULT", "OK" if not FAIL else "NG")
drain_and_exit(0 if not FAIL else 1)
