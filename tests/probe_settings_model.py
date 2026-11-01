"""Find why the settings model reports no rows through the QML bridge.

The QML-side `load()` call appears not to populate the model, while the same model
works when driven from Python in `tests/smoke_settings_cards.py`. The difference
must be in how the call arrives, so this drives the model directly and prints the
state after each step, then compares against the QML path.

QML 侧的 `load()` 调用看起来未能填充模型，而同一模型在
`tests/smoke_settings_cards.py` 中由 Python 驱动时正常。差异必然在于调用如何到达，因此
本脚本直接驱动模型并在每一步后打印状态，再与 QML 路径对照。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.frontend.qml.settings_model import (
    CATEGORIES,
    SettingsRowModel,
)
from gifmanager.frontend.qt.bridge import BackendAdapter


def main():
    app = QGuiApplication.instance() or QGuiApplication([])

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)

        model = SettingsRowModel(adapter)
        print("=== directly, from Python ===")
        print("rowCount before load      :", model.rowCount())
        print("categoryId                :", model.categoryId)
        print("groups for that category  :",
              [g.title_key for g in model._groups_for_category()])
        stored = adapter.load_settings()
        print("loaded settings type      :", type(stored).__name__)
        print("theme from load           :", getattr(stored, "theme", "<none>"))

        model.load()
        app.processEvents()
        print("rowCount after load       :", model.rowCount())
        print("categoryTitles            :", model.categoryTitles)
        print("categoryIds               :", model.categoryIds)

        if model.rowCount():
            index = model.index(0, 0)
            for role_name, role in (("field", model.FieldRole),
                                    ("kind", model.KindRole),
                                    ("label", model.LabelRole),
                                    ("value", model.ValueRole),
                                    ("enabled", model.EnabledRole)):
                print(f"  row0.{role_name:<8} = {model.data(index, role)!r}")

        # The QML path calls `setCategory` then `load`; check that the category
        # switch keeps the rows rather than clearing them.
        # QML 路径会先调用 `setCategory` 再调用 `load`；检查切换分类是否保留行而不是清空。
        print()
        print("=== after switching category ===")
        for category in CATEGORIES[1:]:
            model.setCategory(category.category_id)
            app.processEvents()
            print(f"  {category.category_id:<12} rows={model.rowCount()}")

        # And back to the first, which is what the page shows initially.
        # 再切回第一个，也就是页面初始显示的。
        model.setCategory(CATEGORIES[0].category_id)
        model.load()
        app.processEvents()
        print(f"  back to {CATEGORIES[0].category_id:<7} rows={model.rowCount()}")

        # Whether the slots are exposed at all is the other candidate, since a slot
        # with an unresolvable return type is silently not registered.
        # 槽是否被暴露是另一个候选原因，因为返回类型无法解析的槽会被静默地不注册。
        print()
        print("=== meta-object exposure ===")
        meta = model.metaObject()
        for name in ("load", "reload", "setCategory", "setValue", "categoryIds",
                     "categoryTitles", "categoryId", "revision"):
            found = meta.indexOfMethod(name.encode()) >= 0 \
                or meta.indexOfProperty(name.encode()) >= 0
            print(f"  {name:<16} {'exposed' if found else 'NOT EXPOSED'}")

        adapter.detach()
        backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
