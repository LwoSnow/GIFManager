"""Check where an import goes from the All view, and that All is never a move target.

Two separate rules, both about "全部" being an AGGREGATION rather than a place:

  1. importing while the All view is selected must land in the DEFAULT group, not in whatever
     group the store happens to list first;
  2. "全部" must never appear as a destination in the move picker, because nothing can be
     stored into an aggregation.

Both are checked with a group named "AAA" created FIRST, so "the first image group" and "the
default group" are different groups and a wrong implementation cannot pass by coincidence.

两条彼此独立的规则，都关于"全部"是"聚合"而不是存放地：

  1. 在"全部"视图下导入必须落到"默认"分组，而不是存储恰好列在第一位的那个分组；
  2. "全部"绝不能作为移动选取器里的目的地出现，因为没有任何东西能存进一个聚合。

两条检查都用"最先"创建的名叫 "AAA" 的分组，使"第一个图片分组"与"默认分组"是不同分组，错误的实现
无法侥幸通过。
"""
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt.bridge import BackendAdapter

    application = qml_app.build_application([])
    problems = []
    tmp = tempfile.mkdtemp(prefix="gifmanager-import-target-")
    backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(),
                            log=False)
    try:
        # Created FIRST, so it precedes the default group in `groups()`.
        # 最先创建，因此它在 `groups()` 中排在默认分组之前。
        first_group = backend.store.create_group("AAA", "image")
        path = os.path.join(tmp, "x.png")
        Image.new("RGB", (32, 32), (200, 60, 60)).save(path)
        backend.store.import_emoji(first_group, path, auto_convert=False)

        adapter = BackendAdapter(backend)
        engine, bridge, theme, warnings = qml_app.create_engine(adapter, strict=True)

        default_id = backend.store.default_group_id()
        default_group = backend.store.get_group(default_id)
        print("first image group  :", "AAA", f"(id={first_group})")
        print("default group      :", default_group["name"], f"(id={default_id})")
        print("all group id       :", backend.store._all_group_id())
        print()

        # ---- rule 1: where an All-view import lands / rule 1：全部视图的导入落点 ----
        bridge.selectGroup(-1)
        application.processEvents()
        target = bridge._import_target_group()
        chosen = target["name"] if target else None
        print("All-view import target :", chosen)
        if chosen != default_group["name"]:
            problems.append(
                f"importing from the All view targets {chosen!r}, but the default group is "
                f"{default_group['name']!r}; the first image group is the wrong answer")

        # ---- rule 2: All is not a destination / rule 2：全部不是目的地 ----
        bridge.selectGroup(first_group)
        application.processEvents()
        sticker_id = bridge.stickers.data(bridge.stickers.index(0, 0),
                                          bridge.stickers.IdRole)
        names = [entry["name"] for entry in bridge.groupsForSticker(sticker_id)]
        print("move targets           :", names)
        all_name = bridge.groupDisplayName(backend.store._all_group_id())
        if all_name in names:
            problems.append(
                f"the All view ({all_name!r}) is offered as a move target, but nothing can be "
                f"stored into an aggregation")
        if not names:
            problems.append("no move targets at all, so the feature would be unreachable")

        # ---- and a move into All must be refused / 且移入全部必须被拒绝 ----
        moved = bridge.moveSticker(sticker_id, backend.store._all_group_id())
        print("move into All returned :", moved)
        if moved:
            problems.append("moveSticker accepted the All view as a destination")

        # ---- rule 3: the same must hold for the EDIT-MODE selection ---------
        #
        # This is the path the user actually caught: `moveTargetsForSelection` skipped whichever
        # group was CURRENT, and while the All view is selected `currentId` is -1, so the stored
        # "全部" row never matched and was offered as a destination. Checking it from the All
        # view is what makes the bug reproducible, so that is where the check runs.
        # 这是用户实际抓到的路径：`moveTargetsForSelection` 跳过的是"当前"分组，而在"全部"视图被
        # 选中时 `currentId` 是 -1，因此存储里的"全部"行永远匹配不上并被当作目的地提供。从"全部"
        # 视图检查它才能让该缺陷可复现，因此检查就在这里运行。
        bridge.selectGroup(-1)
        application.processEvents()
        bridge.stickers.selectAll()
        application.processEvents()
        selection_names = [entry["name"]
                           for entry in bridge.moveTargetsForSelection()]
        print("selection targets from All :", selection_names)
        if all_name in selection_names:
            problems.append(
                f"moveTargetsForSelection offers {all_name!r} while the All view is selected; "
                f"it skips the CURRENT group, and the All view's currentId is -1, so the stored "
                f"All row is never excluded")
        if not selection_names:
            problems.append("moveTargetsForSelection returned nothing for a real selection")

        # The dialog that shows these must scroll when the list overflows, which is a property
        # of the component rather than of this data, so it is asserted from the source.
        # 展示这些的对话框在列表溢出时必须可滚动，那是组件属性而不是数据属性，因此从源码断言。
        qml_root = (pathlib.Path(__file__).resolve().parent.parent
                    / "gifmanager" / "frontend" / "qml")
        dialog_source = (qml_root / "components" / "MoveDialog.qml").read_text(
            encoding="utf-8")
        for needle, label in (("ScrollBar.vertical", "a vertical scroll bar"),
                              ("clip: true", "clipping on the list")):
            if needle not in dialog_source:
                problems.append(f"MoveDialog.qml has no {label}")

        print()
        print("engine warnings        :", len(warnings))

        bridge.detach()
        del engine
    finally:
        backend.close()

    print()
    if problems:
        print("IMPORT TARGET CHECK FAILED / 导入目标检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("IMPORT TARGET CHECK OK / 导入目标检查通过")
    print("  the All view imports into the default group, and is never a move destination")
    print("  \"全部\"视图导入到默认分组，且绝不是移动目的地")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
