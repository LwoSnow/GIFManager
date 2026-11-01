"""Determine whether a QML MouseArea keeps receiving moves once the pointer leaves it.

The drag-sweep needs this fact and guessing it wrong has already produced two broken designs:

  * a `MouseArea` overlay on the grid (enabled in edit mode) SWALLOWED every click, so basic
    single-click selection stopped working entirely;
  * a per-card implementation can only work if the card that received the press keeps receiving
    `onPositionChanged` while the pointer crosses its neighbours. If it does, the sweep can be
    driven by the one card that owns the gesture; if it does not, the sweep must be driven by
    whichever card is under the pointer, which is a different design.

This measures it rather than assuming, by synthesising presses and moves through
`QTest`-style event delivery to two adjacent items and counting the callbacks each receives.

拖拽扫选需要这个事实，而猜错它已经产出过两个坏设计：

  * 网格上的 `MouseArea` 覆盖层（编辑模式下启用）"吞掉"了每一次点击，于是基础的单机选中完全失效；
  * 逐卡片的实现只有在"接收按下的那张卡片在指针越过邻卡时仍收到 `onPositionChanged`"时才可行。
    若可行，扫选可由拥有该手势的那一张卡片驱动；若不可行，扫选必须由指针下当时的那张卡片驱动，
    那是另一种设计。

本脚本实测而不是假设：向两个相邻元素合成按下与移动事件，并统计各自收到的回调次数。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOCUMENT = """
import QtQuick

Item {
    id: root
    width: 200
    height: 100

    property int leftMoves: 0
    property int rightMoves: 0
    property int leftPresses: 0
    property int leftReleases: 0

    Rectangle {
        id: left
        x: 0; y: 0; width: 100; height: 100
        color: "red"
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onPressed: root.leftPresses += 1
            onReleased: root.leftReleases += 1
            onPositionChanged: root.leftMoves += 1
        }
    }
    Rectangle {
        id: right
        x: 100; y: 0; width: 100; height: 100
        color: "blue"
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            onPositionChanged: root.rightMoves += 1
        }
    }
}
"""


def main():
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    component.setData(DOCUMENT.encode("utf-8"), "probe")
    root = component.create()
    if root is None:
        print("COMPONENT FAILED")
        for error in component.errors():
            print("  ", error.toString())
        return 1

    window = QQuickWindow()
    window.setWidth(200)
    window.setHeight(100)
    root.setParentItem(window.contentItem())
    window.setVisible(True)

    def pump(seconds=0.1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.005)

    pump(0.3)
    _ = Qt

    def send(kind, x, y, buttons=Qt.MouseButton.LeftButton):
        # `QMouseEvent` with a scene position; the window forwards it to the grabber, which is
        # how a real drag behaves.
        # 带场景坐标的 `QMouseEvent`；窗口把它转发给抓取者，这正是真实拖拽的行为。
        point = QPointF(x, y)
        event = QMouseEvent(kind, point, window.contentItem().mapToScene(point),
                            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
        application.sendEvent(window, event)

    # Press inside the LEFT item, then move rightwards ACROSS into the right item.
    # 在"左"元素内按下，然后向右移动"越过"进入右元素。
    send(QMouseEvent.Type.MouseButtonPress, 50, 50)
    pump(0.1)
    for x in range(60, 160, 20):
        send(QMouseEvent.Type.MouseMove, x, 50)
        pump(0.05)
    send(QMouseEvent.Type.MouseButtonRelease, 150, 50, Qt.MouseButton.NoButton)
    pump(0.1)

    left_presses = root.property("leftPresses")
    left_moves = root.property("leftMoves")
    right_moves = root.property("rightMoves")
    left_releases = root.property("leftReleases")
    print(f"left presses          : {left_presses}")
    print(f"left moves            : {left_moves}")
    print(f"right moves           : {right_moves}")
    print(f"left releases         : {left_releases}")
    print()

    # The pointer crossed from 50 to 150, so half the moves were inside each item. If the press
    # owner kept receiving them, `left_moves` accounts for ALL of them.
    # 指针从 50 移到 150，因此一半的移动发生在各元素内。若按下者持续收到它们，`left_moves` 会涵盖
    # 全部移动。
    total_moves = left_moves + right_moves
    print(f"total moves seen      : {total_moves}")
    if left_presses and left_releases and left_moves >= total_moves:
        print()
        print("RESULT: the press owner keeps receiving every move, so a PER-CARD sweep works")
        print("结论：按下者持续收到每一次移动，因此\"逐卡片\"扫选可行")
        return 0
    print()
    print("RESULT: moves are delivered to the item under the pointer, so the press owner does")
    print("        NOT see the whole gesture. A per-card sweep cannot work; the sweep must be")
    print("        driven by whichever card is under the pointer.")
    print("结论：移动被投递给指针下的元素，因此按下者\"看不到\"整个手势。逐卡片扫选不可行；扫选必须")
    print("      由指针下当时的那张卡片驱动。")
    _ = QPoint
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
