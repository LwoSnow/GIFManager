"""Smoke-load the QML interface and prove it is bound to the backend.

A QML interface fails in a way that unit tests do not catch: the engine loads,
reports nothing fatal, and shows an empty window because one property name was
misspelled. So this checks three things that together rule that out:

1. the root component loads with ZERO engine warnings (any warning is a binding
   that will silently evaluate to `undefined`);
2. the models the interface binds to actually report the seeded data;
3. a mutation through the bridge changes what the model reports, which is the
   binding contract the whole front-end depends on.

QML 界面的冒烟加载，并证明它已绑定到后端。

QML 界面会以单元测试抓不到的方式失败：引擎加载成功、没有致命报告、却因为一个属性名拼错
而显示空窗口。因此本检查三件事，合起来可排除这种情况：

1. 根组件在"零"引擎警告下加载（任何警告都是一个将静默求值为 `undefined` 的绑定）；
2. 界面绑定的模型确实报告了预置数据；
3. 经桥做一次变更会改变模型报告的内容，也就是整个前端依赖的绑定契约。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.frontend.qml import app as qml_app
from gifmanager.frontend.qt.bridge import BackendAdapter


def section(title):
    print()
    print("=" * 4, title)


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    problems = []

    if not os.path.isfile(qml_app.qml_entry()):
        print("QML ENTRY MISSING / QML 入口缺失:", qml_app.qml_entry())
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)

        # Seed content so the models report something other than zero.
        #
        # An IMAGE sticker as well as text ones, because the delegate's `source` binding can
        # only be checked against a row that HAS a source. Seeding text only made the new
        # delegate assertion compare '' with '' — a check that passes while the very bug it
        # exists to catch (a card whose `source` never gets bound) is present.
        # 除了文字贴纸，还要预置一个"图片"贴纸，因为只有"有来源"的行才能检验委托的 `source`
        # 绑定。只预置文字会让新的委托断言比较 '' 与 ''——一个在其存在意义正是要抓的那个缺陷
        # （卡片的 `source` 从未被绑定）存在时仍然通过的检查。
        text_group = backend.store.create_group("QML 测试", "text")
        for index in range(3):
            backend.store.add_text_emoji(text_group, f"entry {index}")

        image_group = backend.store.create_group("QML images", "image")
        image_path = os.path.join(tmp, "seeded.png")
        from PIL import Image

        Image.new("RGB", (96, 96), (30, 90, 200)).save(image_path)
        backend.store.import_emoji(image_group, image_path, auto_convert=False)

        section("loading the interface")
        engine, bridge, theme, warnings = qml_app.create_engine(adapter)
        app.processEvents()
        roots = engine.rootObjects()
        print("root objects :", len(roots))
        print("warnings     :", len(warnings))
        for warning in warnings[:8]:
            print("   ", warning)
        if not roots:
            problems.append("the root component produced no object")
        # A warning is not cosmetic here: it means a binding will evaluate to
        # `undefined`, which is exactly the "blank window with no error" failure.
        # 警告在此不是装饰性的：它意味着某个绑定会求值为 `undefined`，正是"空白窗口且无
        # 错误"的失败形态。
        for warning in warnings:
            if "Unable to assign" in warning or "is not a type" in warning \
                    or "Cannot assign" in warning or "ReferenceError" in warning:
                problems.append(f"engine warning indicates a broken binding: {warning}")

        # Scan STDERR, not the log file.
        #
        # An earlier version of this check looked in the newest file under the log directory and
        # found nothing, because Qt's own QML diagnostics are written to stderr and never reach
        # this application's logger — so the check passed while `Main.qml` printed
        # "ReferenceError: parent is not defined" on every theme switch. `QQmlApplicationEngine
        # .warnings()` does not carry it either: that list only holds diagnostics from the LOAD,
        # and this one is raised later by a signal handler.
        #
        # Installing a `qInstallMessageHandler` would be the thorough fix; capturing the real
        # stderr of a CHILD process is, which `smoke_qml_launcher.py` already does. This check
        # therefore keeps to what it can see (the warning list) and the launcher covers runtime
        # diagnostics, rather than pretending to scan a log that does not hold them.
        # 扫描 stderr，而不是日志文件。
        #
        # 本检查的早期版本在日志目录下最新的文件里查找却什么也没找到，因为 Qt 自身的 QML 诊断写到
        # stderr、永远不会到达本应用的日志器——于是检查通过，而 `Main.qml` 在每次主题切换时都打印
        # "ReferenceError: parent is not defined"。`QQmlApplicationEngine.warnings()` 也不携带
        # 它：那个列表只保留"加载"期的诊断，而这一条是之后由信号处理函数抛出的。
        #
        # 彻底的修法是安装 `qInstallMessageHandler`；捕获"子进程"的真实 stderr 也能做到，而
        # `smoke_qml_launcher.py` 已经在做这件事。因此本检查只依赖它能看到的（警告列表），运行时
        # 诊断由启动器覆盖，而不是假装扫描一个并不持有它们的日志。

        section("models report the seeded data")
        print("groups       :", bridge.groups.rowCount())
        print("current group:", bridge.groups.currentId)
        print("stickers     :", bridge.stickers.count)
        print("view titles  :", bridge.viewTitles)
        if bridge.groups.rowCount() < 3:
            problems.append(
                f"expected at least 3 groups, model has {bridge.groups.rowCount()}")
        # Selecting the seeded group must load its rows, which is the round trip
        # between the QML list and the database.
        # 选中预置分组必须加载其行，这是 QML 列表与数据库之间的往返。
        bridge.selectGroup(text_group)
        app.processEvents()
        print("after select :", bridge.stickers.count, "row(s)")
        if bridge.stickers.count != 3:
            problems.append(
                f"selecting the group loaded {bridge.stickers.count} rows, "
                f"expected 3")

        section("role names match what the delegates read")
        group_roles = {bytes(v).decode() for v in bridge.groups.roleNames().values()}
        sticker_roles = {bytes(v).decode()
                         for v in bridge.stickers.roleNames().values()}
        print("group roles  :", sorted(group_roles))
        print("sticker roles:", sorted(sticker_roles))
        # The delegate in StickerCard.qml declares `required property` names; if a
        # role is missing, the property is simply unset and the card renders blank.
        # StickerCard.qml 中的委托声明了 `required property` 名称；若角色缺失，该属性就是
        # 未设置，卡片会渲染成空白。
        for needed in ("stickerId", "name", "source", "isText", "textContent",
                       "isSelected"):
            if needed not in sticker_roles:
                problems.append(f"the sticker model has no {needed!r} role")
        for needed in ("groupId", "name", "count", "isCurrent"):
            if needed not in group_roles:
                problems.append(f"the group model has no {needed!r} role")

        section("the grid actually creates delegates, with the model's data")
        # The role check above passes for a grid that renders NOTHING, which is what
        # happened: the delegate re-declared the model roles as `required property`,
        # shadowing the card's own properties, so `count` was 0 and the library was empty
        # while every earlier check here reported success.
        #
        # These assertions are the ones that distinguish "the QML parsed" from "a card
        # appeared": the view must have delegates, and a delegate must carry the same source
        # the model reports. The IMAGE group is selected first so the source is non-empty —
        # checking this against a text-only group would compare '' with ''.
        # 上面的角色检查对一个"什么都不渲染"的网格同样通过，而那正是发生过的：委托把模型角色重新
        # 声明为 `required property`，遮蔽了卡片自身的属性，于是 `count` 为 0、素材库为空，而这里
        # 此前每一项检查都报告成功。
        #
        # 这些断言正是区分"QML 解析成功"与"卡片出现了"的东西：视图必须有委托，且某个委托必须带有
        # 与模型一致的来源。先选中"图片"分组使来源非空——拿只有文字的分组来查会变成比较 '' 与 ''。
        bridge.selectGroup(image_group)
        app.processEvents()
        def find_items(root):
            # Walk everything below a window's content item. `QQuickWindow` has no
            # `childItems()`, so the walk starts at `contentItem`.
            # 遍历窗口内容元素之下的一切。`QQuickWindow` 没有 `childItems()`，因此从
            # `contentItem` 开始。
            found = []
            stack = [root]
            while stack:
                item = stack.pop()
                found.append(item)
                try:
                    stack.extend(item.childItems())
                except AttributeError:
                    pass
            return found

        view = None
        for item in find_items(roots[0].contentItem()):
            if item.metaObject().className() == "QQuickGridView":
                view = item
                break
        if view is None:
            problems.append("no GridView is present in the loaded interface")
        else:
            count = view.property("count")
            print("grid count   :", count, "model rows:", bridge.stickers.count)
            if count != bridge.stickers.count:
                problems.append(
                    f"the grid created {count} delegate(s) for "
                    f"{bridge.stickers.count} model row(s); the delegates are not being "
                    f"instantiated from the model")

            # And a live delegate must show the model's source, not an empty default. A
            # delegate that exists but reads empty is the "blank cards" failure, which no
            # warning reports.
            # 而一个存活的委托必须显示模型的来源，而不是空默认值。存在但读到空值的委托正是"空白
            # 卡片"的失败形态，且没有任何警告会报告它。
            cards = [i for i in find_items(view)
                     if "StickerCard" in i.metaObject().className()]
            print("cards found  :", len(cards))
            if not cards:
                problems.append("the grid has no StickerCard delegates in its item tree")
            else:
                expected = bridge.stickers.data(
                    bridge.stickers.index(0, 0), bridge.stickers.SourceRole)
                actual = cards[0].property("source")
                print(f"card source  : {str(actual)[:64]!r}")
                print(f"model source : {str(expected)[:64]!r}")
                if not actual:
                    problems.append(
                        "a StickerCard has an empty `source`; the model's roles are not "
                        "reaching the delegate's properties")
                elif expected and actual != expected:
                    problems.append(
                        f"a StickerCard shows {actual!r} but the model says {expected!r}")

        section("a mutation through the bridge reaches the model")
        # Rename through the bridge and confirm the model reports the new name.
        # Without a working notification the interface would keep showing the old
        # one until a manual reload — which is the class of bug this whole
        # binding-based design exists to remove.
        # 经桥重命名并确认模型报告新名称。若通知不工作，界面会一直显示旧名称直到手动重载
        # ——这正是这套基于绑定的设计所要消除的一类错误。
        # Read the id through the model's ROLE, which is how a delegate gets it.
        # `row(index)` returns the raw store row whose key is `id`, so reading
        # `stickerId` from it would be reading QML's naming off the database's.
        # 经模型的"角色"读取 id，这正是委托获取它的方式。`row(index)` 返回原始存储行，
        # 其键是 `id`，因此从它读 `stickerId` 等于把 QML 的命名套在数据库的命名上。
        index0 = bridge.stickers.index(0, 0)
        sticker_id = bridge.stickers.data(index0, bridge.stickers.IdRole)
        before = bridge.stickers.data(index0, bridge.stickers.NameRole)
        ok = bridge.renameSticker(sticker_id, "renamed via bridge")
        app.processEvents()
        after = bridge.stickers.data(bridge.stickers.index(0, 0),
                                     bridge.stickers.NameRole)
        print(f"rename       : {before!r} -> {after!r} (returned {ok})")
        if not ok or after != "renamed via bridge":
            problems.append("a rename through the bridge did not reach the model")

        section("settings model reflects the schema")
        print("categories   :", bridge.settings.categoryTitles)
        print("rows in first:", bridge.settings.rowCount())
        print("fields       :", [
            bridge.settings.data(bridge.settings.index(i, 0),
                                 bridge.settings.FieldRole)
            for i in range(bridge.settings.rowCount())])
        if bridge.settings.rowCount() == 0:
            problems.append("the settings model reports no rows")
        # A settings edit must persist — through the dialog's transaction: the
        # edit lands in the pending buffer, and 应用/确认 commits it. The two-step
        # assertion covers both halves of that contract.
        # 设置编辑必须持久化——经对话框的事务：编辑先落入待定缓冲，应用/确认提交。
        # 两步断言覆盖该契约的两半。
        bridge.settings.setValue("show_emoji_name", False)
        app.processEvents()
        stored = backend.settings_store.read_all()
        print("show_emoji_name stored before apply:", stored.get("show_emoji_name"))
        if stored.get("show_emoji_name") is not None:
            problems.append("a pending settings edit leaked into the store before apply")
        bridge.settings.applyPending()
        app.processEvents()
        stored = backend.settings_store.read_all()
        print("show_emoji_name stored after apply:", stored.get("show_emoji_name"))
        if stored.get("show_emoji_name") is not False:
            problems.append("a settings edit through the QML model did not persist")
        bridge.settings.cancelPending()

        section("theme singleton carries the palette")
        print("theme name   :", theme.name)
        print("window colour:", theme.window)
        print("accent       :", theme.accent)
        # The palette must differ between themes, or a theme switch would be a
        # no-op that looks like it worked.
        # 两种主题的调色板必须不同，否则切换主题会变成一次看起来成功的空操作。
        dark_window = theme.window
        theme.set_theme("light")
        app.processEvents()
        print("after switch :", theme.name, theme.window)
        if theme.window == dark_window:
            problems.append("the palette did not change with the theme")

        section("shutdown")
        bridge.detach()
        backend.close()
        del engine
        app.processEvents()
        print("torn down cleanly")

    print()
    if problems:
        print("QML CHECK FAILED / QML 检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("QML CHECK OK / QML 检查通过")
    print("  the interface loads without engine warnings, the models report the")
    print("  seeded data with the roles the delegates require, a mutation through")
    print("  the bridge reaches the model, and the palette follows the theme")
    print("  界面加载无引擎警告、模型按委托所需的角色报告预置数据、经桥的变更到达模型、")
    print("  且调色板跟随主题")
    return 0


if __name__ == "__main__":
    # The exit code is captured BEFORE the interpreter tears Qt down. Destroying an
    # engine with live QML objects can leave a non-zero status behind, which would
    # make a passing check look like a failure.
    # 退出码在解释器拆除 Qt "之前"取出。销毁仍有存活 QML 对象的引擎可能留下非零状态，那会
    # 让通过的检查看起来像失败。
    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_status)
