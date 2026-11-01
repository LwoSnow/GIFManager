"""Test whether the context property NAME is what breaks resolution.

`engine.rootContext().contextProperty("app")` returns the bridge, but evaluating
`app` inside the document yields nothing. The cheapest explanation left is the name
itself, so this compares several names in one load: some that ought to be
unremarkable, and the two the application actually tried (`app`, `theme`).

`engine.rootContext().contextProperty("app")` 返回桥，但在文档内求值 `app` 得不到任何
东西。剩下最省事的解释就是这个名称本身，因此本脚本在一次加载中比较多个名称：一些理应平淡
无奇的，以及应用实际试过的两个（`app`、`theme`）。

The result decides the naming, and the naming decides whether five QML files need
another pass over them.

结果决定命名，而命名决定五个 QML 文件是否需要再返工一遍。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Property, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

# Names to compare. `app` and `theme` are what the application used; the others are
# ordinary identifiers that should have no meaning to QML.
# 要比较的名称。`app` 与 `theme` 是应用用过的；其余是对 QML 应当毫无意义的普通标识符。
NAMES = ("app", "theme", "bridge", "backend", "gifmanager", "ctx")

ROOT_TEMPLATE = """
import QtQuick

QtObject {{
    property string value: (typeof {name} !== "undefined" && {name})
                           ? {name}.marker : "<undefined>"
}}
"""


class Marker(QObject):
    def __init__(self, label):
        super().__init__()
        self._label = label

    @Property(str, constant=True)
    def marker(self):
        return self._label


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        for name in NAMES:
            entry = os.path.join(tmp, f"Root_{name}.qml")
            with open(entry, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(ROOT_TEMPLATE.format(name=name))

            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty(name, Marker(f"OK-{name}"))
            warnings = []
            engine.warnings.connect(
                lambda messages: warnings.extend(str(m) for m in messages))
            engine.load(QUrl.fromLocalFile(entry))
            app.processEvents()

            roots = engine.rootObjects()
            if not roots:
                results[name] = f"<load failed: " \
                                f"{warnings[0][:60] if warnings else 'no warning'}>"
            else:
                results[name] = roots[0].property("value")
            del engine

    print("context property name -> value seen inside the document")
    print("上下文属性名 -> 文档内看到的取值")
    print()
    for name in NAMES:
        value = results[name]
        ok = isinstance(value, str) and value.startswith("OK-")
        print(f"  [{'OK ' if ok else 'FAIL'}] {name:<12} {value!r}")

    print()
    working = [n for n in NAMES if str(results[n]).startswith("OK-")]
    broken = [n for n in NAMES if not str(results[n]).startswith("OK-")]
    print("working:", working or "none")
    print("broken :", broken or "none")
    if working and broken:
        print()
        print("VERDICT: the NAME decides. Rename the context property to one that")
        print("         resolves, and leave the QML documents as they are.")
        print("结论：由名称决定。把上下文属性改名为可解析的名称，QML 文档保持不变。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
