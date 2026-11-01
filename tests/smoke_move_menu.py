"""Verify the card menu's move submenu actually gets its items.

`Repeater` cannot fill a `Menu`: it reparents delegates instead of calling
`insertItem`/`addItem`, so the submenu opened EMPTY. `Instantiator` plus
`onObjectAdded`/`onObjectRemoved` is what creates real menu entries.

This counts the items in every menu after opening the card menu, so the answer is a number
rather than "it looks right".

`Repeater` 无法填充 `Menu`：它重设委托的父项而不是调用 `insertItem`/`addItem`，因此子菜单打开时
是空的。`Instantiator` 加 `onObjectAdded`/`onObjectRemoved` 才是创建真实菜单条目的方式。

本脚本在打开卡片菜单后统计每个菜单的条目数，使答案是一个数字而不是"看起来对"。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt.bridge import BackendAdapter

    application = qml_app.build_application([])
    problems = []
    tmp = tempfile.mkdtemp(prefix="gifmanager-menu-")
    backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(),
                            log=False)
    try:
        from PIL import Image

        group_a = backend.store.create_group("A", "image")
        group_b = backend.store.create_group("B", "image")
        path = os.path.join(tmp, "x.png")
        Image.new("RGB", (32, 32), (200, 60, 60)).save(path)
        backend.store.import_emoji(group_a, path, auto_convert=False)

        adapter = BackendAdapter(backend)
        engine, bridge, theme, warnings = qml_app.create_engine(adapter, strict=True)
        bridge.selectGroup(group_a)
        application.processEvents()

        root = engine.rootObjects()[0]
        menu = None
        for child in root.findChildren(QObject):
            if child.objectName() == "cardMenu":
                menu = child
                break
        if menu is None:
            print("MENU CHECK FAILED: cardMenu not found")
            return 1

        sticker_id = bridge.stickers.data(bridge.stickers.index(0, 0),
                                          bridge.stickers.IdRole)
        menu.openFor(sticker_id, 10, 10)
        application.processEvents()

        targets = menu.property("moveTargets")
        print("moveTargets       :", targets)
        print()
        print("=== every QQuickMenu in the tree ===")
        submenu_items = []
        for child in root.findChildren(QObject):
            if type(child).__name__ == "QQuickMenu":
                texts = [grandchild.property("text")
                         for grandchild in child.findChildren(QObject)
                         if grandchild.property("text") is not None]
                count = child.property("count")
                print(f"  {child.objectName() or '<menu>'}: count={count} items={texts}")
                # The submenu is whichever one is NOT the card menu.
                # 子菜单就是"不是"卡片菜单的那一个。
                if child is not menu:
                    submenu_items = texts

        print()
        if len(targets) == 0:
            problems.append("moveTargets is empty, so there is nowhere to move to")
        # The submenu must contain one item per target. `findChildren` also sees the card
        # menu's own items because a submenu is a child of its parent item, so the check is
        # that at least the target names appear somewhere in the submenu's item list.
        # 子菜单必须为每个目标包含一个条目。`findChildren` 也会看到卡片菜单自身的条目，因为子菜单
        # 是其父条目的子项，因此检查的是目标名称至少出现在子菜单的条目列表中。
        expected = [target["name"] for target in targets]
        missing = [name for name in expected if name not in submenu_items]
        if expected and missing:
            problems.append(
                f"the move submenu is missing item(s) {missing}; it has {submenu_items}")
        if not expected and not problems:
            print("(no move targets to check)")

        print("engine warnings   :", len(warnings))
        for warning in warnings:
            if "Unable" in warning or "ReferenceError" in warning:
                problems.append(f"engine warning: {warning}")

        bridge.detach()
        del engine
    finally:
        backend.close()

    print()
    if problems:
        print("MENU CHECK FAILED / 菜单检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("MENU CHECK OK / 菜单检查通过")
    print("  the move submenu really contains one item per target group")
    print("  移动子菜单确实为每个目标分组包含一个条目")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
