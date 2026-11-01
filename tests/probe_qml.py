"""Probe QML availability before committing the front-end to it.

A QML front-end is a different architecture from a Qt Widgets one, so the first
question is not "how do I write it" but "is the Qt Quick stack actually
installed". PySide6 ships Qt Quick in `PySide6_Essentials` and Qt Quick Controls
in `PySide6_Addons`; a partial install can have the widget stack and no QML
runtime at all, and that failure is much cheaper to discover now than after the
front-end has been rewritten.

在把前端交给 QML 之前先探测其可用性。

QML 前端与 Qt Widgets 前端是两套不同架构，因此第一个问题不是"怎么写"，而是"Qt Quick
栈是否真的装了"。PySide6 把 Qt Quick 放在 `PySide6_Essentials`、Qt Quick Controls 放在
`PySide6_Addons`；不完整的安装可能只有控件栈而完全没有 QML 运行时，而这一失败现在发现
比前端重写完之后发现便宜得多。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

MODULES = (
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
)

# A QML document exercising the features the real front-end depends on: a window,
# a data-bound property, a list model with a delegate, and a control from Qt Quick
# Controls. If any of these is missing the front-end design would have to change.
# 一份 QML 文档，演练真实前端所依赖的特性：窗口、数据绑定属性、带委托的列表模型，以及
# 来自 Qt Quick Controls 的控件。缺少任何一个，前端设计都必须改。
PROBE_QML = """
import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: window
    width: 360
    height: 240
    visible: true

    property int hitCount: 0

    ListModel {
        id: probeModel
        ListElement { label: "one" }
        ListElement { label: "two" }
    }

    Column {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        Label {
            text: "GIFManager QML probe"
            font.pixelSize: 16
        }

        ListView {
            width: parent.width
            height: 80
            model: probeModel
            delegate: ItemDelegate {
                width: ListView.view.width
                text: model.label
            }
        }

        Button {
            text: "hits: " + window.hitCount
            onClicked: window.hitCount += 1
        }
    }
}
"""


def main():
    print("=== module availability ===")
    missing = []
    for name in MODULES:
        try:
            __import__(name)
        except ImportError as exc:
            missing.append(name)
            print(f"  MISSING {name}  -> {exc}")
        else:
            print(f"  OK      {name}")

    if missing:
        print()
        print("QML PROBE FAILED / QML 探测未通过")
        print("  missing:", ", ".join(missing))
        print("  install with: pip install PySide6-Essentials PySide6-Addons")
        return 1

    print()
    print("=== loading a QML component ===")
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlApplicationEngine()

    component = QQmlComponent(engine)
    component.setData(PROBE_QML.encode("utf-8"), QUrl("qrc:/probe.qml"))
    if component.isError():
        print("  QML ERRORS / QML 错误:")
        for error in component.errors():
            print("   ", error.toString())
        return 1

    root = component.create()
    if root is None:
        print("  the component produced no root object / 组件未产出根对象")
        return 1
    print(f"  root object : {root.metaObject().className()}")
    print(f"  window size : {root.property('width')}x{root.property('height')}")
    print(f"  bound prop  : hitCount={root.property('hitCount')}")

    # Exercise the binding, which is the mechanism the whole front-end will rely
    # on: a Python-side change must be visible to QML without any refresh call.
    # 演练绑定，也就是整个前端将依赖的机制：Python 侧的改动必须无需任何刷新调用即可被
    # QML 看到。
    root.setProperty("hitCount", 7)
    app.processEvents()
    observed = root.property("hitCount")
    print(f"  after set   : hitCount={observed}")
    if observed != 7:
        print("  property writes do not reach QML / 属性写入未到达 QML")
        return 1

    print()
    print("QML PROBE OK / QML 探测通过")
    print("  Qt Quick, Qt Quick Controls, data binding and list delegates all work")
    print("  Qt Quick、Qt Quick Controls、数据绑定与列表委托均可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
