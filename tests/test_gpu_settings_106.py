"""Regression for the 1.0.6 GPU / settings fixes:
1. the GPU preference is written for the real process image (python.exe), not
   the script path (which Windows never matched — the discrete GPU was never
   used even though the registry had an entry)
2. adapters are listed BY NAME and map onto the class Windows supports
3. the settings dialog opens instantly and every page fits its viewport width
   (text used to be clipped at the edges)
4. an empty group's background is the theme colour in the real window
5. toggling GPU rendering at runtime never swaps the viewport (that crashed the
   renderer and blackened the sticker page)
1.0.6 GPU / 设置修复回归：
1. GPU 首选项写入真正的进程映像（python.exe），而非脚本路径（Windows 从不匹配，
   所以注册表里即使有项也从未切到独显）
2. 显卡按名称列出，并映射到 Windows 支持的类别
3. 设置对话框瞬时打开，且每页都放得下（此前文字在边缘被裁切）
4. 真实窗口中空分组背景为主题色
5. 运行时切换 GPU 渲染绝不替换视口（此前会导致渲染崩溃、表情页变黑）
"""
import collections
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="gifmgr_gpu106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import QSettings

# isolate QSettings / 隔离 QSettings
# NOTE: setDefaultFormat(IniFormat) + setPath() do NOT isolate anything --
# QSettings("Org","App") keeps using the native registry format. And this test
# applies/removes the per-app GPU preference, which used to delete the user's
# own GpuPreference entry. isolate_all() redirects both.
# 注意：setDefaultFormat(IniFormat) + setPath() 并不能隔离——QSettings("Org",
# "App") 仍使用原生注册表格式。而本测试会写入再删除按应用 GPU 首选项，以前会
# 把用户自己设置的 GpuPreference 删掉。isolate_all() 同时重定向两者。
from tests._iso import isolate_all, drain_and_exit  # noqa: E402

isolate_all()

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


# --- 1. preference targets the real process image ----------------------
from app.utils import gpu_pref

check("current_exe 指向进程映像", gpu_pref.current_exe() == os.path.abspath(
    sys.executable), gpu_pref.current_exe())
check("current_exe 不是脚本路径",
      not gpu_pref.current_exe().endswith((".py", ".pyw")),
      gpu_pref.current_exe())

# --- 2. adapter classification & naming --------------------------------
cases = [
    ("NVIDIA GeForce RTX 3050 Laptop GPU", gpu_pref.PREF_HIGH),
    ("AMD Radeon(TM) Graphics", gpu_pref.PREF_POWER),
    ("Intel(R) UHD Graphics 620", gpu_pref.PREF_POWER),
    ("AMD Radeon RX 6600", gpu_pref.PREF_HIGH),
    ("Honor Virtual Display Device", None),
]
bad = [(n, gpu_pref.classify_adapter(n), want) for n, want in cases
       if gpu_pref.classify_adapter(n) != want]
check("显卡名称分类正确", not bad, bad)

from app.widgets.settings_dialog import SettingsDialog
names = ["NVIDIA GeForce RTX 3050 Laptop GPU", "AMD Radeon(TM) Graphics",
         "Honor Virtual Display Device"]
sd = SettingsDialog(gpu_pref=2, gpu_adapters=names)
items = [sd._combo_gpu_pref.itemText(i)
         for i in range(sd._combo_gpu_pref.count())]
check("下拉框按名称列出显卡",
      items[0] == "系统默认" and "NVIDIA GeForce RTX 3050 Laptop GPU" in items
      and "AMD Radeon(TM) Graphics" in items, items)
check("无法分类的适配器不入列表",
      "Honor Virtual Display Device" not in items, items)
check("选中项映射到高性能", sd.gpu_preference() == 2, sd.gpu_preference())
check("显示写入目标程序", gpu_pref.current_exe()[:12] in sd._lbl_gpu_target.text(),
      sd._lbl_gpu_target.text()[:70])

# --- 3. dialog opens fast and pages fit -------------------------------
t0 = time.perf_counter()
sd2 = SettingsDialog()
elapsed = time.perf_counter() - t0
check("设置对话框瞬时打开", elapsed < 0.5, f"{elapsed:.3f}s")
sd2.show()
too_wide = []
for i in range(sd2._cat_list.count()):
    sd2._cat_list.setCurrentRow(i)      # size the page like the user sees it
    for _ in range(8):
        app.processEvents()
    w = sd2._stack.widget(i)
    if not isinstance(w, QScrollArea):
        continue
    page = w.widget()
    if page is None:
        continue
    if page.width() > w.viewport().width() + 2:
        too_wide.append((i, page.width(), w.viewport().width()))
check("每一页都放得下（不裁切文字）", not too_wide, too_wide)
sd2.close()
sd.close()

# --- 4/5. real window: empty-group background + no viewport swapping ----
from app.models.data_manager import DataManager
import app.main_window as mw

w = mw.MainWindow()
dm = DataManager()
w.data_manager = dm
gid = dm.create_group("空分组", "image")
w.show()
w.current_group_id = gid
for theme, expect in (("dark", (30, 30, 30)), ("light", (242, 243, 245))):
    w._theme = theme
    w._apply_theme()
    w._refresh_emoji_grid()
    for _ in range(8):
        app.processEvents()
    img = w.emoji_grid.grab().toImage()
    hist = collections.Counter()
    for y in range(0, img.height(), 4):
        for x in range(0, img.width(), 4):
            c = img.pixelColor(x, y)
            hist[(c.red(), c.green(), c.blue())] += 1
    dom = hist.most_common(1)[0][0]
    check(f"空分组背景为主题色({theme})",
          dom == expect and (0, 0, 0) not in hist, f"dominant={dom}")

v0 = w._scroll_area.viewport().__class__.__name__
for i in range(20):
    w._gpu_render = (i % 2 == 0)
    w._apply_gpu_render(at_startup=False)
for _ in range(4):
    app.processEvents()
v1 = w._scroll_area.viewport().__class__.__name__
check("运行时切换不替换视口", v0 == v1 == "QWidget", f"{v0} -> {v1}")
check("视口背景随主题", w._scroll_area.viewport().palette().color(
    w._scroll_area.viewport().palette().ColorRole.Window).name() == "#f2f3f5",
    w._scroll_area.viewport().palette().color(
        w._scroll_area.viewport().palette().ColorRole.Window).name())

# --- 6. "system default" really clears the preference -------------------
# Turning GPU usage off must stop the app asking for a specific GPU; the
# removed render checkbox did not clear it, so the GPU stayed in use.
# 关闭 GPU 使用后必须不再请求指定显卡；此前那个被移除的渲染开关不会清除偏好，
# 所以独显仍被调用。
if os.name == "nt":
    gpu_pref.apply_preference(gpu_pref.current_exe(), gpu_pref.PREF_HIGH)
    check("选具体显卡会写入偏好",
          gpu_pref.get_preference(gpu_pref.current_exe()) == gpu_pref.PREF_HIGH,
          gpu_pref.get_preference(gpu_pref.current_exe()))
    sd3 = SettingsDialog(gpu_accel=True, gpu_pref=2, gpu_adapters=names)
    check("开关开启且已选具体显卡",
          sd3.gpu_accel() is True and sd3.gpu_render() is True
          and sd3.gpu_preference() == 2,
          f"accel={sd3.gpu_accel()} pref={sd3.gpu_preference()}")
    sd3.close()
    gpu_pref.apply_preference(gpu_pref.current_exe(), gpu_pref.PREF_SYSTEM)
    check("系统默认会清除偏好",
          gpu_pref.get_preference(gpu_pref.current_exe()) is None,
          gpu_pref.get_preference(gpu_pref.current_exe()))
    sd4 = SettingsDialog(gpu_accel=False, gpu_pref=0)
    check("开关关闭时界面显示为关闭", sd4.gpu_render() is False,
          sd4.gpu_accel())
    sd4.close()
else:
    check("选具体显卡会写入偏好", True, "non-Windows: skipped")
    check("系统默认会清除偏好", True, "non-Windows: skipped")
    check("系统默认时界面显示为关闭", True, "non-Windows: skipped")

# --- 7. no OpenGL viewport is ever created ------------------------------
check("不创建 QOpenGLWidget 视口",
      "QOpenGLWidget" not in v0 and "QOpenGLWidget" not in v1, v1)

w.close()
n_pass = sum(1 for _, ok in RES if ok)
print(f"\n1.0.6 GPU/设置修复验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
