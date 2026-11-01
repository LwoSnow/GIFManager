"""Check the REAL `create_engine` for the reference that keeps QML working.

The lifetime probe found that a local variable and an attribute on the context
wrapper both work, while an attribute on the engine alone does not. The real
`create_engine` returns the bridge to its caller, which ought to be enough — so
this measures the real code instead of a model of it, and reports the reference
counts and the actual property values together.

生命周期探测发现：局部变量与上下文包装器上的属性都可行，而"仅"放在引擎上的属性不可行。
真实的 `create_engine` 会把桥返回给调用方，这本应足够——因此本脚本测量真实代码而非它的
模型，并同时报告引用计数与实际属性取值。
"""
import gc
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.frontend.qml import app as qml_app
from gifmanager.frontend.qt.bridge import BackendAdapter


def main():
    app = QGuiApplication.instance() or QGuiApplication([])

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)

        engine, bridge, theme, warnings = qml_app.create_engine(adapter)
        app.processEvents()
        gc.collect()
        app.processEvents()

        print("refcount(bridge) after gc :", sys.getrefcount(bridge))
        print("refcount(theme)  after gc :", sys.getrefcount(theme))
        print("engine._dsh_bridge is bridge:",
              getattr(engine, "_dsh_bridge", None) is bridge)
        print("engine._dsh_context         :",
              type(getattr(engine, "_dsh_context", None)).__name__)
        print("context property app present:",
              engine.rootContext().contextProperty("app") is not None)

        root = engine.rootObjects()[0]
        # Read a property that the document derives from the context property, so
        # the answer reflects what QML actually resolved rather than what Python
        # installed.
        # 读取文档从上下文属性派生的属性，使答案反映 QML 实际解析到的内容，而不是 Python
        # 安装了什么。
        print()
        print("what QML resolved:")
        for name in ("title", "width"):
            print(f"  root.{name} = {root.property(name)!r}")

        # Walk into a page and read its `app` property, which is the binding
        # `app: app` and is exactly what was failing.
        # 走进一个页面并读取其 `app` 属性，那正是 `app: app` 绑定，也是此前失败的地方。
        from PySide6.QtCore import QObject

        pages = [c for c in root.findChildren(QObject)
                 if "Page" in c.metaObject().className()]
        print(f"  pages found: {len(pages)}")
        for page in pages:
            bound = page.property("app")
            print(f"    {page.metaObject().className():<28} app="
                  f"{type(bound).__name__}")

        # Force a collection with the returned tuple dropped, which is the closest
        # model of a caller that only keeps the engine.
        # 在丢弃返回元组的情况下强制回收，这是"调用方只保留引擎"的最接近模型。
        print()
        print("after dropping the returned bridge reference:")
        engine_kept = engine
        del engine, bridge, theme, warnings, root, pages
        gc.collect()
        app.processEvents()
        root2 = engine_kept.rootObjects()[0]
        print("  root.title =", root2.property("title"))
        pages2 = [c for c in root2.findChildren(QObject)
                  if "Page" in c.metaObject().className()]
        for page in pages2:
            print(f"    {page.metaObject().className():<28} app="
                  f"{type(page.property('app')).__name__}")

        adapter.detach()
        backend.close()
        del engine_kept, root2, pages2
        gc.collect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
