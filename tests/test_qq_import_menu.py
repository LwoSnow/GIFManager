"""Regression for: settings dialog must not open twice, and QQ emoji
one-click import (multi-account scan under Documents\\Tencent Files).
回归测试：设置对话框不可重复打开；QQ 表情一键导入（扫描 Documents\\
Tencent Files 下多账号）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_qq_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QMessageBox
from app.main_window import MainWindow
from app.models.lang_manager import tr

# Modal message boxes would block the offscreen test; swallow them.
# 模态提示框会阻塞离屏测试，直接吞掉
QMessageBox.information = lambda *a, **k: QMessageBox.StandardButton.Ok
QMessageBox.warning = lambda *a, **k: QMessageBox.StandardButton.Ok
QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


# --- build a fake Tencent Files tree with two accounts / 构造两个账号的假目录
tf = os.path.join(TMP, "Tencent Files")
for qq, n in (("123456789", 3), ("987654321", 2)):
    ori = os.path.join(tf, qq, "nt_qq", "nt_data", "Emoji", "personal_emoji", "Ori")
    os.makedirs(ori, exist_ok=True)
    for i in range(n):
        p = os.path.join(ori, f"sticker{i}.jpg")
        Image.new("RGB", (40, 40), (i * 40, 100, 200)).save(p)
# a non-digit folder must be skipped / 非数字文件夹应被跳过
os.makedirs(os.path.join(tf, "All Users"), exist_ok=True)
with open(os.path.join(tf, "All Users", "junk.txt"), "w") as f:
    f.write("x")

w = MainWindow()
w.show()
app.processEvents()

# 1. settings dialog must not open twice / 设置不可重复打开
w._open_settings()
first = w._settings_dialog
check("A 设置已打开", first is not None)
w._open_settings()
check("A2 重复点击不新建", w._settings_dialog is first, f"same={w._settings_dialog is first}")
# close it and verify reopening works / 关闭后可再次打开
w._settings_dialog.reject()
app.processEvents()
check("A3 关闭后置空", w._settings_dialog is None)
w._open_settings()
check("A4 关闭后可重开", w._settings_dialog is not None
      and w._settings_dialog is not first)
if w._settings_dialog is not None:
    w._settings_dialog.reject()
    app.processEvents()

# 2. QQ account scan / QQ 账号扫描
w._qq_emoji_base = lambda: tf
accounts = w._scan_qq_accounts()
print("  扫描结果:", accounts)
check("B 扫描到 2 个账号", len(accounts) == 2, len(accounts))
check("B2 跳过非数字目录", all(a["qq"].isdigit() for a in accounts))
check("B3 数量正确", {a["qq"]: a["count"] for a in accounts} ==
      {"123456789": 3, "987654321": 2})
check("B4 翻译键存在", tr("import_qq") != "import_qq")

# 3. import from one account into the library / 从账号导入表情
g = w.data_manager.create_group("QQ导入组", "image")
w.current_group_id = g
acc = next(a for a in accounts if a["qq"] == "123456789")
w._import_from_qq(acc["path"])
app.processEvents()
rows = w.data_manager.get_emojis_by_group(g)
check("C 导入 3 个表情", len(rows) == 3, f"rows={len(rows)}")
check("C2 全部存为 gif", all(r["filename"].endswith(".gif") for r in rows))

# 4. empty QQ dir -> message path (no crash) / 空目录不崩溃
empty_ori = os.path.join(TMP, "empty_ori")
os.makedirs(empty_ori, exist_ok=True)
w._import_from_qq(empty_ori)
check("D 空目录不崩溃", True)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\nQQ 导入/设置防重验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
