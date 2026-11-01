"""Find WHICH reference keeps a context property alive across `load()`.

`tests/probe_qml_ownership.py` showed that a context property is collected when the
object has no live Python reference. That fix did not work in `app.py`, so this
narrows down which reference actually counts, testing the candidates in one run:

    A. a local variable in the calling function
    B. an attribute on the engine
    C. an attribute on the engine's root context wrapper
    D. no reference at all, as the control

`tests/probe_qml_ownership.py` 表明上下文属性在对象没有存活 Python 引用时会被回收。
那个修法在 `app.py` 中无效，因此本脚本在一次运行中收窄到哪一个引用才算数：

    A. 调用函数中的局部变量
    B. 引擎上的属性
    C. 引擎根上下文包装器上的属性
    D. 完全没有引用，作为对照
"""
import gc
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Property, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

ROOT = """
import QtQuick

QtObject {
    property string value: (typeof probe !== "undefined" && probe)
                           ? probe.marker : "<null-or-undefined>"
}
"""


class Marker(QObject):
    def __init__(self, label):
        super().__init__()
        self._label = label

    @Property(str, constant=True)
    def marker(self):
        return self._label


def run(tmp, name, strategy):
    path = os.path.join(tmp, f"{name}.qml")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(ROOT)

    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    marker = strategy(engine, context)
    engine.load(QUrl.fromLocalFile(path))
    QGuiApplication.instance().processEvents()
    roots = engine.rootObjects()
    value = roots[0].property("value") if roots else "<no root>"
    return engine, context, marker, value


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        # A: the object is a local of this function AND the caller holds it.
        # A：对象是本函数的局部变量，且调用方持有它。
        def strategy_a(engine, context):
            holder = Marker("OK-local")
            context.setContextProperty("probe", holder)
            return holder

        # B: only an attribute on the engine.
        # B：只有引擎上的属性。
        def strategy_b(engine, context):
            context.setContextProperty("probe", Marker("OK-engine-attr"))
            return None

        # C: only an attribute on the context wrapper.
        # C：只有上下文包装器上的属性。
        def strategy_c(engine, context):
            context._keep = Marker("OK-context-attr")
            context.setContextProperty("probe", context._keep)
            return None

        # D: control, nothing kept.
        # D：对照，什么都不保留。
        def strategy_d(engine, context):
            context.setContextProperty("probe", Marker("OK-nothing"))
            return None

        for label, strategy in (("A local variable", strategy_a),
                                ("B engine attribute", strategy_b),
                                ("C context attribute", strategy_c),
                                ("D no reference", strategy_d)):
            engine, context, marker, value = run(
                tmp, label.split()[0], strategy)
            results[label] = value
            # Keep the returned objects alive until after the measurement, then
            # release everything so the next case starts clean.
            # 在测量之后才释放返回的对象，使下一个用例从干净状态开始。
            del engine, context, marker
            gc.collect()

    print("reference strategy -> value seen inside the document")
    print("引用策略 -> 文档内看到的取值")
    print()
    for label, value in results.items():
        ok = isinstance(value, str) and value.startswith("OK-")
        print(f"  [{'OK ' if ok else 'FAIL'}] {label:<24} {value!r}")

    print()
    working = [k for k, v in results.items()
               if isinstance(v, str) and v.startswith("OK-")]
    if working:
        print("The reference must be:", ", ".join(working))
        print("引用必须是：", ", ".join(working))
    else:
        print("Nothing works in isolation; the cause is elsewhere.")
        print("隔离测试下都不可行；原因在别处。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
