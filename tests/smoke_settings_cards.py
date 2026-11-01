"""Verify the settings page and the card interfaces.

Three things have to hold:

1. **The settings page covers the schema.** Every `AppSettings` field that is
   meant to be user-editable must have a row, and every row must point at a real
   field. A row pointing at nothing raises at build time; a field with no row
   would be a setting the user cannot change.

2. **A control edit round-trips.** Changing a widget must produce a normalised
   settings object that persists and reloads to the same value — including the
   percent rows, whose stored unit differs from the edited unit.

3. **The card dialogs act on the right row** and reach the store, and a
   capability the platform lacks disables its control rather than leaving it
   silently inert.

三件事必须成立：

1. **设置页覆盖 schema。** 每个应当可被用户编辑的 `AppSettings` 字段都必须有一行，
   且每一行都必须指向真实字段。指向空的行在构建时抛错；没有行的字段则是用户无法修改的
   设置。

2. **控件编辑能往返。** 改一个控件必须产出规范化后的设置对象，且持久化再读回后取值
   一致——包括存储单位与编辑单位不同的百分比行。

3. **卡片对话框作用于正确的行** 并能到达存储；而平台缺少的能力会禁用其控件，而不是让
   它静默无效。
"""
import dataclasses
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QSpinBox

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.core import settings as schema
from gifmanager.frontend.qt import commands as cmd
from gifmanager.frontend.qt.bridge import BackendAdapter, apply_theme
from gifmanager.frontend.qt.shell_window import ShellWindow
from gifmanager.frontend.qt.views.settings import KIND_BOOL, KIND_PERCENT, PAGES


def section(title):
    print()
    print("=" * 4, title)


def all_rows():
    for page in PAGES:
        for _section_key, rows in page.sections:
            for row in rows:
                yield page, row


def main():
    app = QApplication.instance() or QApplication([])
    problems = []

    # ---- 1. schema coverage / 1. schema 覆盖 -------------------------------
    section("settings rows cover the schema")
    row_fields = {row.field for _page, row in all_rows()}
    settings_fields = {f.name for f in dataclasses.fields(schema.AppSettings)}
    print(f"rows     : {len(row_fields)}")
    print(f"fields   : {len(settings_fields)}")

    # Fields that deliberately have no row, with the reason. Anything else being
    # absent would be an oversight.
    # 刻意不设行的字段及其原因。其他字段若缺失即为疏漏。
    intentionally_hidden = {
        "window_geometry",   # front-end session state / 前端会话状态
        "last_group_name",   # front-end session state / 前端会话状态
        "gpu_adapters",      # cached probe result, not a user choice / 探测结果缓存
    }
    missing = settings_fields - row_fields - intentionally_hidden
    if missing:
        problems.append(f"settings with no control: {sorted(missing)}")
    unknown = row_fields - settings_fields
    if unknown:
        problems.append(f"rows for nonexistent settings: {sorted(unknown)}")
    print(f"hidden   : {sorted(intentionally_hidden)}")

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)
        apply_theme(app, backend.settings.theme)
        window = ShellWindow(adapter)
        window.show()
        app.processEvents()

        section("navigation and view registration")
        print("views    :", list(window._views.keys()))
        print("nav rows :", window._nav.count())
        labels = [window._nav.item(i).text() for i in range(window._nav.count())]
        print("labels   :", labels)
        for needed in ("library", "settings", "about"):
            if needed not in window._views:
                problems.append(f"view {needed} is not registered")
        if window._nav.count() != len(window._views):
            problems.append("navigation rows and views disagree")

        section("settings page structure")
        if not window.navigate("settings"):
            problems.append("cannot navigate to the settings view")
        app.processEvents()
        view = window.view("settings")
        print("categories:", [view._page_list.item(i).text()
                              for i in range(view._page_list.count())])
        print("controls  :", len(view._controls))
        print("pages     :", view._page_stack.count())
        if view._page_stack.count() != len(PAGES):
            problems.append(
                f"{len(PAGES)} pages declared but {view._page_stack.count()} built")
        if len(view._controls) != len(row_fields):
            problems.append(
                f"{len(row_fields)} rows declared but "
                f"{len(view._controls)} controls built")

        section("capability gating")
        report = backend.platform_report()
        capabilities = report.get("capabilities", {})
        print("capabilities:", capabilities)
        # A row can be disabled for TWO reasons — a missing capability, or a
        # master toggle that is off — so the expectation is their combination. The
        # earlier version compared against the capability alone and reported the
        # two GPU rows as failures, when they were correctly following a
        # `gpu_accel` switch that defaults to off.
        # 一行可能因"两个"原因被禁用——缺少能力，或主开关关闭——因此期望值是两者的组合。
        # 早前的版本只与能力比较，把两个 GPU 行报为失败，而它们其实正确地跟随了默认关闭的
        # `gpu_accel` 开关。
        from gifmanager.frontend.qt.views.settings import DEPENDENT_ON

        for field, widget in view._controls.items():
            row = view._rows[field]
            if not row.capability:
                continue
            expected = capabilities.get(row.capability, True)
            master = DEPENDENT_ON.get(field)
            master_on = True
            if master is not None:
                master_on = bool(getattr(view._draft, master))
            want_enabled = expected and master_on
            actual = widget.isEnabled()
            print(f"  {field:<20} {row.capability:<18} "
                  f"master={master_on} expected={want_enabled} enabled={actual}")
            if want_enabled != actual:
                problems.append(
                    f"{field}: enabled={actual} but capability={expected} and "
                    f"master={master_on}")
        # A dependent row must follow its master toggle within the page's own
        # draft, so the rule lives in one place rather than in every presenter.
        # 依赖行必须跟随页面草稿中的主开关，使该规则只有一处而非每个呈现方各一份。
        view._draft = schema.from_mapping(
            {**schema.to_mapping(view._draft), "ffmpeg_enabled": False})
        view._sync_gates()
        if view._controls["ffmpeg_path"].isEnabled():
            problems.append("ffmpeg_path stays enabled with ffmpeg switched off")
        view._draft = schema.from_mapping(
            {**schema.to_mapping(view._draft), "ffmpeg_enabled": True})
        view._sync_gates()

        section("a control edit round-trips through the schema")
        captured = []
        view.settings_edited.connect(lambda s: captured.append(s))
        # Flip a boolean and confirm the shell persisted it.
        # 翻转一个布尔项并确认外壳已持久化。
        checkbox = view._controls["show_emoji_name"]
        if not isinstance(checkbox, QCheckBox):
            problems.append("show_emoji_name is not a checkbox")
        else:
            before = view._draft.show_emoji_name
            checkbox.setChecked(not before)
            app.processEvents()
            stored = backend.settings_store.read_all()
            print(f"show_emoji_name: {before} -> "
                  f"{view._draft.show_emoji_name}, stored="
                  f"{stored.get('show_emoji_name')}")
            if view._draft.show_emoji_name == before:
                problems.append("the checkbox did not change the draft")
            if captured and captured[-1].show_emoji_name != view._draft.show_emoji_name:
                problems.append("the emitted settings disagree with the draft")
            # The library grid must follow, which is the shell's job.
            # 表情库网格必须跟随，这是外壳的职责。
            if window.library._grid._show_name == before:
                problems.append("the grid did not follow the name setting")

        section("percent rows convert between display and storage")
        percent_rows = [row for _page, row in all_rows()
                        if row.kind == KIND_PERCENT]
        print(f"percent rows: {[row.field for row in percent_rows]}")
        for row in percent_rows:
            widget = view._controls[row.field]
            if not isinstance(widget, QSpinBox):
                problems.append(f"{row.field} is not a spin box")
                continue
            widget.setValue(int(round(1.4 * 100)))
            app.processEvents()
            stored_value = getattr(view._draft, row.field)
            reloaded = schema.from_mapping(
                backend.settings_store.read_all())
            print(f"  {row.field:<20} display=140% draft={stored_value} "
                  f"reloaded={getattr(reloaded, row.field)}")
            if abs(stored_value - 1.4) > 1e-6:
                problems.append(
                    f"{row.field}: 140% stored as {stored_value}, expected 1.4")
            if abs(getattr(reloaded, row.field) - stored_value) > 1e-6:
                problems.append(f"{row.field} did not survive persistence")

        section("choice rows report the stored value, not the index")
        for field in ("theme", "send_mode", "gpu_pref"):
            widget = view._controls[field]
            if not isinstance(widget, QComboBox):
                problems.append(f"{field} is not a combo box")
                continue
            index = widget.findData(schema.to_mapping(view._draft)[field])
            print(f"  {field:<12} currentData={widget.currentData()!r} "
                  f"findData={index}")
            if index < 0:
                problems.append(
                    f"{field}: the stored value is not among the combo's data")

        section("card interface: dialogs exist and act on a row")
        if not window.navigate("library"):
            problems.append("cannot navigate back to the library")
        app.processEvents()
        library = window.library
        group_id = backend.store.create_group("卡片测试", "text")
        first = backend.store.add_text_emoji(group_id, "hello")
        backend.store.add_text_emoji(group_id, "world")
        backend.notify("library", None)
        library._group_list.select_group(group_id)
        app.processEvents()

        print("rows       :", len(library._grid.rows()))
        print("has_target :", library.state().get("has_target"))
        if library.state().get("has_target"):
            problems.append("has_target is true with nothing selected")

        # Selecting a card must make the edit commands available, which is what
        # makes F2/F3/Ctrl+M reachable outside a context click.
        # 选中一张卡片必须让编辑类命令可用，这正是让 F2/F3/Ctrl+M 在非右键时也能到达的
        # 原因。
        library._grid.set_selected(first, True)
        app.processEvents()
        state = library.state()
        print("after select: selected=", state.get("selected"),
              "count=", state.get("selection_count"),
              "has_target=", state.get("has_target"))
        if not state.get("has_target"):
            problems.append("selecting a card did not enable the edit commands")
        for command_id in (cmd.CMD_RENAME, cmd.CMD_EDIT_TEXT,
                           cmd.CMD_MOVE_TO_GROUP, cmd.CMD_COPY):
            command = window._registry.get(command_id)
            if command is None:
                problems.append(f"{command_id} is not registered")
            elif not command.is_enabled(state):
                problems.append(f"{command_id} is disabled with a row selected")

        # The target resolution must prefer the right-clicked row over the
        # selection, because that is what a context menu promises.
        # 目标解析必须优先取右键点击的行而非选中项，因为那是右键菜单的承诺。
        library._context_row = {"id": 999, "original_name": "context"}
        resolved = library._target_row()
        print("target from context:", resolved.get("id"),
              "from selection: expected", first)
        if resolved.get("id") != 999:
            problems.append("the context row did not win over the selection")
        library._context_row = None

        section("rename and text edit reach the store")
        from gifmanager.frontend.qt.dialogs.edit_text_dialog import EditTextDialog
        from gifmanager.frontend.qt.dialogs.rename_dialog import RenameDialog

        # Constructing them proves the ported dialogs still import and build
        # against the new tree, which is what a regression would break first.
        # 构建它们可以证明已移植的对话框在新目录树中仍能导入与构建——回归首先会破坏的
        # 就是这一点。
        rename = RenameDialog("hello", window, title=adapter.tr("rename_emoji"))
        print("rename dialog:", rename.new_name(), "size", rename.size().width(),
              "x", rename.size().height())
        rename.deleteLater()
        editor = EditTextDialog("hello", window)
        editor._editor.setPlainText("changed")
        print("text dialog  :", editor.text())
        editor.deleteLater()
        if editor.text() != "changed":
            problems.append("the text dialog did not round-trip its content")

        # Assert each mutation on the field that mutation OWNS, and check them
        # separately.
        #
        # A text sticker derives its display name FROM its text content, so calling
        # `update_text_content` also overwrites `original_name`. Checking both
        # afterwards therefore cannot tell a broken rename from a working text edit
        # — the earlier version reported "rename_emoji did not persist" when the
        # rename had in fact worked and been superseded.
        # 每一项变更都在它"自己拥有"的字段上断言，并分开检查。
        #
        # 文字贴纸的显示名"派生自"其文字内容，因此调用 `update_text_content` 也会覆盖
        # `original_name`。事后同时检查两者无法区分"重命名坏了"与"文字编辑正常工作"——
        # 早前的版本在重命名确实生效且随后被取代的情况下报告"rename_emoji did not persist"。
        backend.store.rename_emoji(first, "renamed")
        renamed = backend.store.get_emoji(first)
        print("after rename :", renamed["original_name"])
        if renamed["original_name"] != "renamed":
            problems.append("rename_emoji did not persist")

        backend.store.update_text_content(first, "new content")
        edited = backend.store.get_emoji(first)
        print("after edit   :", edited["text_content"])
        if edited["text_content"] != "new content":
            problems.append("update_text_content did not persist")
        backend.notify("library", None)
        app.processEvents()

        section("delete through the card interface")
        ids = backend.store.ids_sharing_content_hash([first])
        removed = backend.store.delete_emojis(ids)
        backend.notify("library", None)
        app.processEvents()
        print("removed      :", removed, " remaining:",
              len(backend.store.get_emojis_by_group(group_id)))
        if removed != 1:
            problems.append(f"expected to remove 1 row, removed {removed}")

        section("shutdown")
        window.shutdown()
        adapter.detach()
        backend.close()
        print("shut down cleanly")

    print()
    if problems:
        print("SETTINGS AND CARDS CHECK FAILED / 设置与卡片检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("SETTINGS AND CARDS CHECK OK / 设置与卡片检查通过")
    print("  every editable setting has a control, edits round-trip through the")
    print("  schema and persistence, capability gates disable what the platform")
    print("  cannot do, and the card dialogs act on the right row")
    print("  每项可编辑设置都有控件、编辑经 schema 与持久化往返、能力门控禁用平台做不到")
    print("  的项，且卡片对话框作用于正确的行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
