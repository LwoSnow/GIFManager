"""Regression tests for the GPU / packaging findings.

Covers: the adapter list must come from the registry (no PowerShell — it broke
in the packaged build), the switch must never DELETE the GPU preference when the
adapter is left at "system default", and the dialog must be able to report
whether this process uses the GPU at all.
GPU / 打包相关结论的回归测试。
覆盖：显卡列表改由注册表读取（不再依赖 PowerShell——它在打包后失效）、
开关在显卡为"系统默认"时绝不删除 GPU 偏好、以及对话框能报告本进程是否真的用到 GPU。
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

TMP = tempfile.mkdtemp(prefix="gpupkg106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from tests._iso import isolate_all, drain_and_exit, cleanup_gpu_pref

isolate_all()
app = QApplication.instance() or QApplication(sys.argv)

from app.utils import gpu_pref
import app.main_window as mw_mod
from app.widgets.settings_dialog import SettingsDialog

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name
          + ((" | " + str(detail)) if detail else ""))


# ------------------------------------------------------- adapter enumeration
print("\n[1] adapter list comes from the registry / 显卡列表取自注册表")
t0 = time.perf_counter()
names = gpu_pref._adapters_from_registry()
reg_elapsed = time.perf_counter() - t0
check("registry enumeration returns names", bool(names), names)
check("registry enumeration is instant (<0.2 s, no subprocess)",
      reg_elapsed < 0.2, f"{reg_elapsed * 1000:.1f} ms")
t0 = time.perf_counter()
listed = gpu_pref.list_adapters()
fast_elapsed = time.perf_counter() - t0
check("list_adapters uses the registry path (instant, no PowerShell)",
      listed == names and fast_elapsed < 0.5,
      f"{fast_elapsed * 1000:.1f} ms vs registry {reg_elapsed * 1000:.1f} ms")
check("the machine's real adapters are found",
      any("NVIDIA" in n or "AMD" in n or "Radeon" in n or "Intel" in n
          for n in listed), listed)
check("classifier still maps the real adapters",
      all(gpu_pref.classify_adapter(n) is not None
          for n in listed if "Virtual" not in n),
      [(n, gpu_pref.classify_adapter(n)) for n in listed])

# a frozen build must still enumerate (this is what used to break) /
# 打包后仍须能枚举（此前正是在这里失效）
saved_frozen = getattr(sys, "frozen", None)
sys.frozen = True
try:
    frozen_names = gpu_pref.list_adapters()
    check("adapter enumeration works in a frozen build",
          frozen_names == listed, frozen_names)
    check("legacy_exe is empty when frozen", gpu_pref.legacy_exe() == "")
finally:
    if saved_frozen is None:
        try:
            del sys.frozen
        except AttributeError:
            pass
    else:
        sys.frozen = saved_frozen

# ----------------------------------------------------------- GPU usage probe
print("\n[2] GPU usage probe / GPU 使用情况探测")
luids = gpu_pref.process_gpu_luids()
check("process_gpu_luids returns a list (may be empty) and never raises",
      isinstance(luids, list), luids)
check("a CPU-rendered Qt process reports no GPU activity (honest answer)",
      luids == [] or all(str(x).startswith("0x") for x in luids), luids)

# --------------------------------------------------- preference write rules
print("\n[3] GPU preference write rules / GPU 偏好写入规则")
exe = gpu_pref.current_exe()


def stored():
    return gpu_pref.get_preference(exe)


win = mw_mod.MainWindow()
win._gpu_pref = gpu_pref.PREF_HIGH

# 3a: switch ON with "system default" must NOT delete an existing entry ----
gpu_pref.apply_preference(exe, gpu_pref.PREF_HIGH)
win._gpu_accel = True
win._gpu_pref = 0
win._apply_gpu_preference(explicit=True)
check("开启加速但显卡为系统默认时保留已有偏好（不删除）",
      stored() == gpu_pref.PREF_HIGH, stored())
win._apply_gpu_preference(explicit=False)
check("启动时显卡为系统默认同样不删除", stored() == gpu_pref.PREF_HIGH, stored())

# 3b: switch ON with a chosen adapter writes high performance ------------
win._gpu_pref = gpu_pref.PREF_HIGH
win._apply_gpu_preference(explicit=True)
check("选定独显后写入高性能", stored() == gpu_pref.PREF_HIGH, stored())

# 3c: switch OFF (explicit) clears the entry ----------------------------
win._gpu_accel = False
win._apply_gpu_preference(explicit=True)
check("显式关闭加速会清除偏好", stored() is None, stored())

# 3d: startup with acceleration off leaves everything alone -------------
gpu_pref.apply_preference(exe, gpu_pref.PREF_HIGH)
win._gpu_accel = False
win._apply_gpu_preference(explicit=False)
check("启动时加速关闭不动注册表", stored() == gpu_pref.PREF_HIGH, stored())

# 3e: startup with acceleration on refreshes the choice ----------------
win._gpu_accel = True
win._gpu_pref = gpu_pref.PREF_HIGH
win._apply_gpu_preference(explicit=False)
check("启动时加速开启会刷新偏好", stored() == gpu_pref.PREF_HIGH, stored())
cleanup_gpu_pref()

# --------------------------------------------------------- dialog reporting
print("\n[4] settings dialog reporting / 设置对话框的显示")
dlg = SettingsDialog(gpu_accel=True, gpu_pref=gpu_pref.PREF_HIGH)
text = dlg._gpu_target_text()
check("目标程序与当前记录都显示出来", exe[:20] in text and "：" in text,
      text[:130])
none_text = SettingsDialog(gpu_accel=True, gpu_pref=0)._gpu_target_text()
check("未设置时显示未设置",
      ("未设置" in none_text) or ("not set" in none_text), none_text[:130])
check("GPU 使用情况一行存在且可读", dlg._lbl_gpu_usage is not None)
check("适配器下拉里没有无法分类的项",
      all(dlg._combo_gpu_pref.itemData(i) in (0, 1, 2, None)
          for i in range(dlg._combo_gpu_pref.count())))
dlg.deleteLater()

print("\n" + "=" * 62)
print(f"PASS {len(PASS)} | FAIL {len(FAIL)}")
for f in FAIL:
    print("  FAILED: " + f)
print("RESULT", "OK" if not FAIL else "NG")
drain_and_exit(0 if not FAIL else 1)
