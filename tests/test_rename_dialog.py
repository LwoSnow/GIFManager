"""Verify the unified RenameDialog:
- transparent background on prompt + input row (no dark/black box)
- localised OK/Cancel buttons (Chinese)
- compact size matching the group-rename window
- group rename now uses RenameDialog (not the English QInputDialog)
验证统一 RenameDialog：
- 提示与输入行透明背景（无黑框）
- 本地化确定/取消按钮（中文）
- 紧凑尺寸与分组重命名窗口一致
- 分组重命名改用 RenameDialog（而非英文 QInputDialog）"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLineEdit, QLabel, QPushButton

from app.models.lang_manager import tr
from app.widgets.rename_dialog import RenameDialog

RES = []
def check(name, ok, detail=""):
    RES.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


def find_buttons(widget):
    buttons = []
    for w in widget.findChildren(QPushButton):
        buttons.append(w)
    return buttons


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet("""
        QDialog { background-color: #252525; }
        QLineEdit { background-color: #2B2B2B; border: 1px solid #3A3A3A; }
    """)

    dlg = RenameDialog("旧名称", None, title=tr("rename_group_dialog"))
    dlg.show()

    # 1. Compact size (matches group-rename window, not the old 360x160)
    check("尺寸紧凑(300x150)", dlg.width() == 300 and dlg.height() == 150,
          f"({dlg.width()}x{dlg.height()})")

    # 2. Localised OK/Cancel (Chinese) / 本地化确定/取消
    texts = [b.text() for b in find_buttons(dlg)]
    ok_chinese = tr("ok")
    cancel_chinese = tr("cancel")
    check("确定按钮本地化", ok_chinese in texts, f"texts={texts}")
    check("取消按钮本地化", cancel_chinese in texts, f"texts={texts}")

    # 3. Input row transparent (no dark box) / 输入行透明
    editors = dlg.findChildren(QLineEdit)
    check("存在输入框", len(editors) == 1, f"n={len(editors)}")
    ss = editors[0].styleSheet()
    check("输入框透明背景", "background: transparent" in ss, f"ss={ss[:60]}")

    # 4. Prompt label transparent / 提示标签透明
    labels = dlg.findChildren(QLabel)
    prompt_transparent = any(
        "background: transparent" in l.styleSheet() for l in labels
    )
    check("提示标签透明", prompt_transparent)

    # 5. new_name returns stripped text / 返回去除空白后的文本
    editors[0].setText("  新名字  ")
    check("new_name 去除空白", dlg.new_name() == "新名字",
          f"got={dlg.new_name()!r}")

    # 6. Group rename path uses RenameDialog (no QInputDialog for rename)
    import inspect
    import app.widgets.group_list as gl
    src = inspect.getsource(gl.GroupListWidget._rename_group)
    uses_dialog = "from app.widgets.rename_dialog import RenameDialog" in src
    no_qinput = "QInputDialog.getText" not in src
    check("分组重命名使用 RenameDialog", uses_dialog and no_qinput,
          f"uses_dialog={uses_dialog} no_qinput={no_qinput}")

    # 7. Light theme: title/editor use dark (readable) text, not white
    # / 亮色主题：标题/编辑框用深色可读文字，而非白色
    from PySide6.QtWidgets import QWidget
    host = QWidget()
    host._theme = "light"
    host.show()
    dlg_light = RenameDialog("名字", host)
    title_label = [l for l in dlg_light.findChildren(QLabel)
                   if l.text() == tr("rename")]
    check("亮色标题存在", len(title_label) == 1)
    title_ss = title_label[0].styleSheet() if title_label else ""
    check("亮色标题深色可读", "#222222" in title_ss and "#FFF" not in title_ss,
          f"ss={title_ss[:60]}")
    ed_light = dlg_light.findChildren(QLineEdit)[0].styleSheet()
    check("亮色编辑框深色文字", "#1E1E1E" in ed_light, f"ss={ed_light[:60]}")

    # 8. Dark theme: title/editor use light (readable) text
    # / 深色主题：标题/编辑框用浅色可读文字
    host_dark = QWidget()
    host_dark._theme = "dark"
    host_dark.show()
    dlg_dark = RenameDialog("名字", host_dark)
    title_dark = [l for l in dlg_dark.findChildren(QLabel)
                  if l.text() == tr("rename")]
    title_ss_d = title_dark[0].styleSheet() if title_dark else ""
    check("深色标题浅色可读", "#FFFFFF" in title_ss_d, f"ss={title_ss_d[:60]}")

    n_pass = sum(1 for _, ok, _ in RES if ok)
    print(f"\n重命名对话框验证: {n_pass}/{len(RES)} 通过")
    return 0 if n_pass == len(RES) else 1


if __name__ == "__main__":
    sys.exit(main())
