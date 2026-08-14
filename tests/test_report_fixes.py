"""Regression for the Report.md bug fixes: builtin-group role identity
(Bug1), import-menu connections after language switch (Bug2), move_emoji
column reset (Bug3), hotkey-capture keeps the old hotkey (Bug5), translation
format safety (Bug11), thread_count 0 semantics (Bug12), merge_columns_into
target_cols (Bug13).
Report.md 修复的回归：内置分组角色识别（Bug1）、语言切换后导入菜单连接
（Bug2）、move_emoji 列重置（Bug3）、热键捕获保留旧值（Bug5）、翻译 format
安全（Bug11）、thread_count 0 语义（Bug12）、merge_columns_into target_cols
（Bug13）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_report_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from app.models.data_manager import DataManager
from app.models.lang_manager import LangManager
from app.widgets.settings_dialog import SettingsDialog, recommended_thread_count
from app.models.lang_manager import set_language, tr

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()

# --- Bug1: builtin role survives reorder + rename + re-init / 角色识别
dft_id = dm.default_group_id()
all_id = dm._all_group_id()
dm.rename_group(dft_id, "我的默认")
dm.create_group("组A", "image")
dm.create_group("组B", "image")
dm.reorder_group(dft_id, 2)
check("A Bug1 重排后默认组仍可识别", dm.default_group_id() == dft_id)
dm._init_tables()  # simulate restart / 模拟重启
check("A2 Bug1 重启后无重复默认组",
      dm.default_group_id() == dft_id
      and dm.get_group(dft_id)["name"] == "我的默认")
cnt = dm._conn.execute(
    "SELECT COUNT(*) FROM groups WHERE builtin_role='default'").fetchone()[0]
check("A3 Bug1 default 角色唯一", cnt == 1, cnt)

# --- Bug3: move_emoji resets the column state / 移动后重置列
g_src = dm.create_group("源文组", "text")
g_txt = dm.create_group("目标文组", "text")
ids = [dm.add_text_emoji(g_src, f"m{i}") for i in range(4)]
# give the moved card a far column in the source group / 给源组一个远端列
dm.set_emoji_column(ids[0], 5, 2)
dm.move_emoji(ids[0], g_txt)
row = dm.get_emojis_by_group(g_txt)[0]
check("B Bug3 移动后重置 user_sorted", row["user_sorted"] == 0, row["user_sorted"])
check("B2 Bug3 移动后重置 col_index", row["col_index"] == 0, row["col_index"])
# target text group has no orphan columns / 目标文字组无孤列
txt_rows = dm.get_emojis_by_group(g_txt)
cols = {int(e["col_index"]) for e in txt_rows}
check("B3 Bug3 无孤列", cols == {0}, cols)

# --- Bug5: hotkey capture keeps the old hotkey when no key pressed /
# 点击热键框但不按键时保留原热键
from app.widgets.settings_dialog import HotkeyCapture
hc = HotkeyCapture()
hc._mods = 1
hc._vk = 0x79  # F10
hc.setText("F10")
hc._start_capture()
hc._stop_capture()  # no key pressed / 未按键
check("C Bug5 未按键保留原热键", hc._mods == 1 and hc._vk == 0x79,
      f"{hc._mods},{hc._vk}")
check("C2 Bug5 文本保留", hc.text() == "F10", hc.text())
# ESC still clears / ESC 仍清空
hc._start_capture()
from PySide6.QtCore import Qt as _Qt, QEvent as _QEvent
from PySide6.QtGui import QKeyEvent
hc.keyPressEvent(QKeyEvent(
    _QEvent.Type.KeyPress, _Qt.Key.Key_Escape, _Qt.KeyboardModifier.NoModifier))
check("C3 Bug5 ESC 清空", hc._mods == 0 and hc._vk == 0)

# --- Bug11: malformed translation string does not crash / 翻译串异常不崩
lm = LangManager()
lm._texts = {"bad1": "no brace {", "bad2": "empty {}", "bad3": "{missing}"}
check("D Bug11 未配对花括号", lm.t("bad1", x=1) == "no brace {")
check("D2 Bug11 空占位", lm.t("bad2") == "empty {}")
check("D3 Bug11 未知键", lm.t("bad3", x=1) == "{missing}")

# --- Bug12: thread_count keeps 0=automatic / thread_count 0 语义
dlg = SettingsDialog(thread_count=0)
rec = recommended_thread_count()
check("E Bug12 自动时返回 0", dlg.thread_count() == 0, dlg.thread_count())
dlg._spin_threads.setValue(rec)
check("E2 Bug12 等于推荐值时返回 0", dlg.thread_count() == 0)
dlg._spin_threads.setValue(rec + 1)
check("E3 Bug12 其他值返回具体值", dlg.thread_count() == rec + 1)
dlg.deleteLater()

# --- Bug13: merge_columns_into respects target_cols / 按 target_cols 轮转
g13 = dm.create_group("合并组", "text")
ids = [dm.add_text_emoji(g13, f"t{i}") for i in range(8)]
for i, eid in enumerate(ids):
    dm.set_emoji_column(eid, i % 3, i // 3)  # 3 columns / 3 列
# merge cols 1,2 into col 0 / 把列 1、2 并入列 0
dm.merge_columns_into(g13, [1, 2], [0])
rows13 = dm.get_emojis_by_group(g13)
cols13 = {int(e["col_index"]) for e in rows13}
check("F Bug13 全部并入目标列 0", cols13 == {0}, cols13)

# --- Bug2: language switch rebuilds menu with connected actions / 语言切换后菜单连接
from app.main_window import MainWindow
w = MainWindow()
w.show()
app.processEvents()
set_language("en_US")
w._reload_language()
# PySide6 does not count Python slots via receivers(); verify by triggering
# the action with stubbed handlers / PySide6 的 receivers() 不统计 Python 槽；
# 用 stub 处理器触发 action 验证连接
fired = {"folder": 0, "files": 0}
w._import_from_folder = lambda: fired.__setitem__("folder", fired["folder"] + 1)
w._import_from_files = lambda: fired.__setitem__("files", fired["files"] + 1)
w._act_import_folder.trigger()
w._act_import_files.trigger()
check("G Bug2 语言切换后文件夹导入有连接", fired["folder"] == 1, fired)
check("G2 Bug2 语言切换后文件导入有连接", fired["files"] == 1, fired)
set_language("zh_CN")
w._reload_language()
w._import_from_folder = lambda: fired.__setitem__("folder", fired["folder"] + 1)
w._act_import_folder.trigger()
check("G3 Bug2 切回中文后仍有连接", fired["folder"] == 2, fired)
w._real_quit()
app.processEvents()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\nReport 修复验证: {n_pass}/{len(RES)} 通过")
try:
    dm._conn.close()
except Exception:
    pass
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
