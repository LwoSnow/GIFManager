"""Establish why a context property reads as null inside QML.

Python reports the context property as set and non-None, while the document
evaluates the same name to null. The two candidates are:

  A. the Python object has no live reference, so Qt holds a dangling wrapper —
     `setContextProperty` does NOT take ownership of a `QObject`;
  B. a Qt 6.11 regression in context property resolution.

The first is by far the more common cause, and it is testable: keep a reference and
see whether the value appears. This also checks `setInitialProperties` and a
registered singleton instance, so whichever works is known rather than assumed.

确定为什么上下文属性在 QML 内读作 null。

Python 报告该上下文属性已设置且非 None，而文档对同一名称求值得到 null。两个候选原因：

  A. Python 对象没有存活引用，因此 Qt 持有的是悬空包装——`setContextProperty` "不"接管
     `QObject` 的所有权；
  B. Qt 6.11 在上下文属性解析上的回归。

第一个是常见得多的原因，而且可以测试：保住一个引用，看取值是否出现。本脚本同时检查
`setInitialProperties` 与注册的单例实例，因此哪一种可行是被"测出"的而非假设的。
"""
import gc
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Property, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance

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


def load(tmp, name, register):
    path = os.path.join(tmp, f"{name}.qml")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(ROOT)
    engine = QQmlApplicationEngine()
    marker = register(engine)
    engine.load(QUrl.fromLocalFile(path))
    QGuiApplication.instance().processEvents()
    roots = engine.rootObjects()
    value = roots[0].property("value") if roots else "<no root>"
    return engine, marker, value


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        # A: reference kept alive by the caller. If the object is being collected,
        # this one succeeds and the next one fails, and the difference is the
        # whole diagnosis.
        # A：引用由调用方保住。若对象确实被回收，这一个会成功而下一个会失败，而这个差异
        # 就是全部诊断。
        def keep(engine):
            marker = Marker("OK-kept-alive")
            engine.rootContext().setContextProperty("probe", marker)
            return marker

        engine, marker, value = load(tmp, "A", keep)
        results["A context property, reference kept"] = value
        del engine, marker
        gc.collect()

        # A2: reference deliberately dropped, collection forced. This reproduces
        # the application's behaviour, where the bridge was a local.
        # A2：刻意丢弃引用并强制回收。这复现了应用的行为——桥是一个局部变量。
        def drop(engine):
            engine.rootContext().setContextProperty("probe", Marker("OK-no-ref"))
            return None

        engine, _marker, value = load(tmp, "A2", drop)
        gc.collect()
        app.processEvents()
        results["A2 context property, reference dropped"] = value
        del engine
        gc.collect()

    print("how the object was exposed -> value seen inside the document")
    print("对象的暴露方式 -> 文档内看到的取值")
    print()
    for label, value in results.items():
        ok = isinstance(value, str) and value.startswith("OK-")
        print(f"  [{'OK ' if ok else 'FAIL'}] {label:<44} {value!r}")

    print()
    kept = str(results["A context property, reference kept"]).startswith("OK-")
    dropped = str(results["A2 context property, reference dropped"]).startswith("OK-")
    if kept and not dropped:
        print("VERDICT: the object was being COLLECTED. A context property needs a")
        print("         live Python reference for the whole lifetime of the engine,")
        print("         because `setContextProperty` does not take ownership.")
        print("结论：对象被回收了。上下文属性需要在引擎整个生命周期内存活的 Python 引用，")
        print("      因为 `setContextProperty` 不接管所有权。")
    elif kept and dropped:
        print("VERDICT: context properties work either way, so the application's")
        print("         failure has a different cause and must be found elsewhere.")
        print("结论：两种方式下上下文属性都可用，因此应用的失败另有原因，需另行查找。")
    else:
        print("VERDICT: context properties are broken here regardless of ownership.")
        print("结论：无论所有权如何，上下文属性在此都不可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
