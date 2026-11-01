"""Isolate how far a context property reaches in QML, before changing any more QML.

Three attempts at passing the Python bridge into the pages failed with
"ReferenceError: app is not defined" or "Cannot read property of undefined". Rather
than guess again, this builds the smallest possible case and measures which of the
three access patterns actually work:

    A. the root document reads a value off the context property object itself;
    B. a child component created from ANOTHER FILE reads it;
    C. the same child reads a value passed in as an explicit property.

Whichever of B and C succeeds decides the design. Guessing wrong here costs
another full pass over five QML files.

在继续改动 QML 之前，先确定上下文属性在 QML 中能到达多远。

前面三次把 Python 桥传入页面的尝试都以 "ReferenceError: app is not defined" 或
"Cannot read property of undefined" 失败。与其再猜一次，本脚本构造最小可能的情形并测量
三种访问方式里哪一种真的可行：

    A. 根文档从上下文属性对象本身读取一个值；
    B. 从"另一个文件"创建的组件读取它；
    C. 同一子组件读取作为显式属性传入的值。

B 与 C 中哪一个成功，就决定了设计。在这里猜错的代价是再返工一遍五个 QML 文件。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Property, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

# A minimal object with one property, standing in for BackendBridge.
# 一个带单个属性的最小对象，代表 BackendBridge。
MINIMAL_OBJECT_QML = '''
import QtQuick

QtObject {
    property string marker: ""
}
'''

CHILD_QML = '''
import QtQuick

Item {
    // C: the value arrives as an explicit property.
    // C：取值作为显式属性传入。
    required property var injected
    property string cValue: injected ? injected.marker : "<no injected>"

    // B: the value is expected from the engine's root context.
    // B：取值预期来自引擎的根上下文。
    property string bValue: (typeof probe !== "undefined" && probe)
                            ? probe.marker : "<probe not visible>"
}
'''

ROOT_QML = '''
import QtQuick
import QtQuick.Controls

ApplicationWindow {
    width: 100
    height: 100
    visible: false

    // A: read straight off the context property.
    // A：直接从上下文属性读取。
    property string aValue: (typeof probe !== "undefined" && probe)
                            ? probe.marker : "<probe not visible>"

    Child {
        injected: probe
    }
}
'''


class Probe(QObject):
    @Property(str, constant=True)
    def marker(self):
        return "PROBE-OK"


def write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, "Probe.qml", MINIMAL_OBJECT_QML)
        write(tmp, "Child.qml", CHILD_QML)
        entry = write(tmp, "Root.qml", ROOT_QML)

        probe = Probe()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("probe", probe)
        engine.addImportPath(tmp)

        warnings = []
        engine.warnings.connect(lambda messages: warnings.extend(
            str(m) for m in messages))
        engine.load(QUrl.fromLocalFile(entry))
        app.processEvents()

        roots = engine.rootObjects()
        print("root objects:", len(roots))
        if not roots:
            print("--- engine warnings ---")
            for warning in warnings:
                print("  ", warning)
            return 1

        root = roots[0]
        results["A root reads context property"] = root.property("aValue")

        child = root.findChild(QObject, None) if False else None
        # The child is a direct child of the root; locate it by class name.
        # 子组件是根的直接子项；按类名定位它。
        for candidate in root.children():
            if "Child" in candidate.metaObject().className():
                child = candidate
                break
        if child is None:
            print("the child component was not found")
            return 1
        results["B child reads context property"] = child.property("bValue")
        results["C child reads injected property"] = child.property("cValue")

    print()
    for label, value in results.items():
        ok = value == "PROBE-OK"
        print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {value!r}")

    print()
    if results["C child reads injected property"] == "PROBE-OK":
        print("VERDICT: explicit property injection works; use `app: bridge`")
        print("结论：显式属性注入可行；使用 `app: bridge`")
    else:
        print("VERDICT: even injection failed, so the problem is elsewhere")
        print("结论：连注入都失败，说明问题在别处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
