"""Report what the loaded QML root actually sees, property by property.

The warning stream says `page.app` is undefined, but the isolated probe showed that
a context property IS visible from a component in another file. Those two facts
cannot both be true of the same mechanism, so this reads the values straight off the
loaded objects rather than reasoning from error text.

警告流说 `page.app` 是 undefined，但隔离探测表明上下文属性"确实"对另一个文件中的组件
可见。同一机制不可能同时满足这两件事，因此本脚本直接从已加载的对象上读取取值，而不是从
错误文本推断。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.frontend.qml import app as qml_app
from gifmanager.frontend.qt.bridge import BackendAdapter


def dump(obj, label, indent=0):
    pad = " " * indent
    meta = obj.metaObject()
    print(f"{pad}{label}: {meta.className()}")
    for name in ("app", "theme"):
        try:
            value = obj.property(name)
        except Exception as exc:
            print(f"{pad}  .{name}: <error {exc}>")
            continue
        print(f"{pad}  .{name}: {type(value).__name__} = {value}")
    return meta


def main():
    app = QGuiApplication.instance() or QGuiApplication([])

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)

        # Capture the warnings without letting them become noise.
        # 捕获警告，但不让它们变成噪声。
        engine, bridge, theme, warnings = qml_app.create_engine(adapter)
        app.processEvents()

        print("=== context object ===")
        print("engine root context has app  :",
              engine.rootContext().contextProperty("app") is not None)
        print("engine root context has theme:",
              engine.rootContext().contextProperty("theme") is not None)
        print("bridge object                :", type(bridge).__name__)
        print("theme object                 :", type(theme).__name__)

        print()
        print("=== root object tree ===")
        roots = engine.rootObjects()
        root = roots[0]
        dump(root, "root")
        for child in root.children():
            name = child.metaObject().className()
            if "Page" in name or "QQuickItem" not in name:
                pass
        # Children of the StackLayout are the pages.
        # StackLayout 的子项就是各页面。
        for child in root.findChildren(QObject):
            name = child.metaObject().className()
            if "Page" in name:
                dump(child, "page", indent=2)

        # Count warnings by kind so the summary is not lost in the stream.
        # 按类别统计警告，使摘要不被信息流淹没。
        print()
        print("=== warning summary ===")
        kinds = {}
        for warning in warnings:
            if "ReferenceError" in warning:
                key = "ReferenceError"
            elif "TypeError" in warning:
                key = "TypeError"
            elif "Connections" in warning:
                key = "Connections"
            elif "style does not support" in warning:
                key = "style customization"
            elif "overrides a member" in warning:
                key = "property shadowing"
            else:
                key = "other"
            kinds[key] = kinds.get(key, 0) + 1
        for key, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>3}  {key}")

        print()
        print("=== distinct messages (first 6) ===")
        seen = []
        for warning in warnings:
            # Strip the file prefix to group by the real complaint.
            # 去掉文件前缀，按真正的抱怨内容分组。
            tail = warning.split(".qml:", 1)[-1]
            if tail not in seen:
                seen.append(tail)
        for tail in seen[:6]:
            print("  ", tail[:150])

        bridge.detach()
        backend.close()
        del engine
    return 0


if __name__ == "__main__":
    sys.exit(main())
