"""Focused regression for the settings-dialog fixes (bugs 1-3 from the
roadmap): language-switch text refresh, category list alignment, and the
gs combos following the active theme.
设置页修复的专项回归（后期计划 Bug1-3）：语言切换文字刷新、分类列表对齐、
排序下拉框跟随主题。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_settings_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from app.widgets.settings_dialog import SettingsDialog
from app.models.lang_manager import set_language, current_language, tr

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dlg = SettingsDialog(parent=None)

# Bug 3: the category list must have 7 items and refresh with the correct
# keys ("Update" at index 5, "About" at index 6) / 分类列表 7 项、键位正确
expected_keys = ("cat_general", "cat_send", "cat_hotkey", "cat_text",
                 "cat_perf", "cat_update", "cat_about")
texts_zh = [dlg._cat_list.item(i).text() for i in range(7)]
check("A 分类列表 7 项", dlg._cat_list.count() == 7, dlg._cat_list.count())
check("A2 中文下第5项为 更新", texts_zh[5] == tr("cat_update"), texts_zh[5])
check("A3 中文下第6项为 关于", texts_zh[6] == tr("cat_about"), texts_zh[6])

# switch to English and refresh / 切英文并刷新
set_language("en_US")
dlg.refresh_translations()
texts_en = [dlg._cat_list.item(i).text() for i in range(7)]
check("B 英文下第5项为 Update", texts_en[5] == tr("cat_update"), texts_en[5])
check("B2 英文下第6项为 About", texts_en[6] == tr("cat_about"), texts_en[6])
check("B3 标题为 Settings", dlg._title_label.text() == tr("settings"), dlg._title_label.text())
check("B4 排序依据为 Sort by", dlg._label_gs_by.text() == tr("global_sort_by"),
      dlg._label_gs_by.text())
check("B5 排序方向为 Direction", dlg._label_gs_dir.text() == tr("global_sort_dir"),
      dlg._label_gs_dir.text())
# the gs labels are proper QLabel widgets (were anonymous before) / 控件可访问
check("B6 gs 标签存在", dlg._label_gs_by is not None and dlg._label_gs_dir is not None)

# switch back to Chinese and refresh (the reported "Update shows About" bug)
# 切回中文并刷新（原报告"更新"误显"关于"）
set_language("zh_CN")
dlg.refresh_translations()
texts_zh2 = [dlg._cat_list.item(i).text() for i in range(7)]
check("C 切回中文 更新 正确", texts_zh2[5] == "更新", texts_zh2[5])
check("C2 切回中文 关于 正确", texts_zh2[6] == "关于", texts_zh2[6])

# Bug 2: gs combos must NOT carry an inline dark stylesheet so the theme
# QSS applies / 排序下拉框无内联暗色样式（跟随主题）
check("D gs 下拉无内联样式", dlg._combo_gs_by.styleSheet() == ""
      and dlg._combo_gs_dir.styleSheet() == "",
      dlg._combo_gs_by.styleSheet())

dlg.deleteLater()
n_pass = sum(1 for _, ok in RES if ok)
print(f"\n设置页修复验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
