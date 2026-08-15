"""Integration check for the focus-guard auto-input design on real Windows:
after clicking an emoji in the manager, foreground focus must remain on the
chat window (never stolen), and the paste must be triggered. Requires a
desktop session (windows platform, not offscreen).
真实 Windows 焦点守卫自动输入集成验证：在管理器点击表情后，前台焦点必须
保持在聊天窗口（不被抢占），且必须触发粘贴。需要桌面会话（Windows 平台，
非 offscreen）。"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile
import time

sys.path.insert(0, r"C:\TLWorkStation\GIFManager")

user32 = ctypes.WinDLL("user32")

from PySide6.QtWidgets import QApplication

import app.models.data_manager as dm_mod
TMP = tempfile.mkdtemp(prefix="gifmgr_ai2_")
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from app.models.data_manager import DataManager
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()
win = mw.MainWindow()
win.data_manager = dm

g = dm.create_group("自动输入", "image")
gifp = os.path.join(TMP, "a.gif")
with open(gifp, "wb") as f:
    f.write(b"GIF89a" + b"\x00" * 40)
dm.import_emoji(g, gifp, auto_convert=False)
e = dm.get_emojis_by_group(g)[0]

import app.utils.input_sender as ins
paste_calls = []
_orig = ins.paste_to_foreground
ins.paste_to_foreground = lambda delay_ms=50: (paste_calls.append(delay_ms), True)[1]

win._auto_input = True
# chat window gets focus first / 先让聊天窗口获得焦点
import PySide6.QtWidgets as qw
chat = qw.QWidget()
chat.setWindowTitle("chat")
chat.resize(300, 150)
chat.show()
app.processEvents()
time.sleep(0.3)
app.processEvents()
chat_hwnd = int(chat.winId())
print("chat focused initially:", user32.GetForegroundWindow() == chat_hwnd)

win.show()
app.processEvents()
time.sleep(0.4)  # guard starts, tracks chat as target / 守卫启动并跟踪聊天窗口
app.processEvents()
fg_after_show = user32.GetForegroundWindow()
print("after gm show: fg==chat:", fg_after_show == chat_hwnd,
      "| fg==gm:", fg_after_show == int(win.winId()))
check("A gm 显示不抢聊天焦点", fg_after_show == chat_hwnd,
      "fg={} chat={}".format(fg_after_show, chat_hwnd))

# click the emoji / 点击表情
win._on_emoji_clicked(e)
app.processEvents()
time.sleep(0.3)
app.processEvents()
fg1 = user32.GetForegroundWindow()
print("after emoji click: fg==chat:", fg1 == chat_hwnd,
      "| paste:", len(paste_calls))
check("B 点击表情后焦点仍在聊天窗口", fg1 == chat_hwnd,
      "fg={} chat={}".format(fg1, chat_hwnd))
check("C 粘贴已触发", len(paste_calls) >= 1, paste_calls)

# a real mouse click on the manager (like the user does) / 真实鼠标点击管理器
r = wt.RECT()
user32.GetWindowRect(int(win.winId()), ctypes.byref(r))
cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
user32.SetCursorPos(cx, cy)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
user32.mouse_event(0x0004, 0, 0, 0, 0)
app.processEvents()
time.sleep(0.5)
app.processEvents()
fg2 = user32.GetForegroundWindow()
print("after real click: fg==chat:", fg2 == chat_hwnd,
      "| fg==gm:", fg2 == int(win.winId()))
check("D 真实点击后焦点仍回聊天窗口", fg2 == chat_hwnd,
      "fg={} chat={}".format(fg2, chat_hwnd))

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n自动输入集成验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
