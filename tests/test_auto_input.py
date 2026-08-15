"""Auto-input feature checks: clicking an emoji with the setting on must
trigger a paste into the focused input (SendInput Ctrl+V), and the toggle
must gate it. Runs offscreen, paste is stubbed.
自动输入功能验证：开启"点击表情自动输入"时点击表情必须触发向焦点输入框
粘贴（SendInput Ctrl+V），开关能正确关闭。离屏运行，粘贴函数打桩。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_autoinput_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication

from app.models.data_manager import DataManager
import app.main_window as mw
import app.utils.input_sender as ins

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()
win = mw.MainWindow()
win.data_manager = dm

# A tiny valid gif / 一个极小的合法 gif
g = dm.create_group("自动输入", "image")
gifp = os.path.join(TMP, "a.gif")
with open(gifp, "wb") as f:
    f.write(b"GIF89a" + b"\x00" * 40)
dm.import_emoji(g, gifp, auto_convert=False)
e = dm.get_emojis_by_group(g)[0]

# Stub paste functions to observe calls / 打桩 paste 函数以观察调用
calls = []
_orig_w = ins.paste_to_window
_orig_f = ins.paste_to_foreground


def _fake_paste_to_window(hwnd, delay_ms=50):
    calls.append(("window", hwnd, delay_ms))
    return True


def _fake_paste_to_foreground(delay_ms=50):
    calls.append(("fg", delay_ms))
    return True


ins.paste_to_window = _fake_paste_to_window
ins.paste_to_foreground = _fake_paste_to_foreground

# 1. Setting on -> paste triggered (target not known -> fg fallback) /
#    开启 → 触发粘贴（无目标 → 前台回退）
win._auto_input = True
win._on_emoji_clicked(e)
check("A 开启时点击表情触发粘贴", len(calls) == 1 and calls[0][0] == "fg", calls)

# 1b. With a guard target -> paste_to_window used / 有守卫目标 → 用 paste_to_window
calls.clear()
win._focus_guard._target = 12345
win._on_emoji_clicked(e)
check("A2 有目标时投递到窗口",
      len(calls) == 1 and calls[0][0] == "window" and calls[0][1] == 12345, calls)
win._focus_guard._target = 0

# 2. Setting off -> no paste / 关闭 → 不触发
calls.clear()
win._auto_input = False
win._on_emoji_clicked(e)
check("B 关闭时不触发粘贴", len(calls) == 0, calls)

# 3. Text emoji also triggers / 文字表情同样触发
g2 = dm.create_group("文字", "text")
tid = dm.add_text_emoji(g2, "hi")
te = dm.get_emojis_by_group(g2)[0]
calls.clear()
win._auto_input = True
win._on_emoji_clicked(te)
check("C 文字表情触发粘贴", len(calls) == 1, calls)

# 4. input_sender: non-Windows returns False without raising / 非 Windows 平台直接返回 False
ins.paste_to_foreground = _orig_f
ins.paste_to_window = _orig_w
if sys.platform != "win32":
    check("D 非Windows平台安全返回", ins.paste_to_foreground() is False)
else:
    # Struct sanity only — no real keystrokes in tests / 仅校验结构，测试不真发按键
    check("D Windows结构定义可用", ins.INPUT_KEYBOARD == 1 and ins.VK_V == 0x56)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n自动输入验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
