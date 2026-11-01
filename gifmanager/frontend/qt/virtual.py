"""Virtualisation arithmetic for the sticker grid.

These functions decide WHICH cards exist as widgets, given where the viewport is
and how tall the content is. They are pure functions of numbers, so they are
testable without a `QApplication` and reusable by a non-Qt front-end that
virtualises its own list.

One inconsistency is fixed here: the previous release used a 300 px buffer to
decide which cards to materialise but a hard-coded 150 px band to decide which
GIFs play. Those are different questions and now have different, named answers.

贴纸网格的虚拟化运算。

这些函数决定"哪些卡片作为控件存在"，依据是视口位置与内容高度。它们是数字的纯函数，
因此无需 `QApplication` 即可测试，也能被自行虚拟化列表的非 Qt 前端复用。

这里修正了一处不一致：上一版本用 300px 缓冲决定物化哪些卡片，却用硬编码的 150px
带来决定播放哪些 GIF。这是两个不同的问题，现在有了各自具名且不同的答案。
"""
import dataclasses

# Extra pixels above and below the viewport for which cards are materialised.
# Cards in this band exist but are not yet animating.
# 视口上下额外物化卡片的像素范围。此带内的卡片已存在但尚未播放动画。
DEFAULT_OVERSCAN = 300

# Extra pixels before a card is destroyed. Without the margin, a card sitting
# exactly on the boundary is destroyed and rebuilt on alternating scroll ticks.
# 销毁卡片前的额外像素。缺少该余量时，恰好位于边界上的卡片会在相邻滚动 tick 之间
# 反复销毁重建。
DEFAULT_HYSTERESIS = 100

# Band around the viewport in which animations run. Deliberately much smaller
# than the overscan: having a card READY is cheap, running its animation is not.
# 视口周围运行动画的范围。刻意远小于 overscan：让卡片"就绪"很便宜，运行其动画不是。
DEFAULT_ANIMATION_BAND = 150


@dataclasses.dataclass(frozen=True)
class GridMetrics:
    # The geometry facts a layout needs, injected rather than read from a
    # widget. A web front-end fills the same fields from CSS.
    # 布局所需的几何事实，以注入方式提供而非从控件读取。Web 前端用 CSS 填充同样的
    # 字段。
    card_width: int
    card_height: int
    spacing: int = 8
    margin: int = 0

    @property
    def stride_x(self):
        return max(1, int(self.card_width) + int(self.spacing))

    @property
    def stride_y(self):
        return max(1, int(self.card_height) + int(self.spacing))


def visible_window(scroll_top, viewport_height, overscan=DEFAULT_OVERSCAN):
    # Vertical range of the materialisation band as `(top, bottom)`.
    #
    # The band is clamped at the top edge because a negative top would make
    # every "is it above the band" comparison meaningless; the bottom is left
    # unclamped because the content height is not known here.
    # 物化带的垂直范围 `(上, 下)`。
    #
    # 上边缘做钳制，因为负的上界会让所有"是否在带上方"的比较失去意义；下边缘不钳制，
    # 因为此处并不知道内容高度。
    top = max(0, int(scroll_top) - max(0, int(overscan)))
    bottom = int(scroll_top) + max(0, int(viewport_height)) + max(0, int(overscan))
    return top, bottom


def visible_ids(rects, top, bottom):
    # Ids whose rectangle intersects the band, in the table's own order.
    # Returns a list rather than a set so a caller can preserve draw order.
    # 矩形与带相交的 id，按表自身的顺序。返回列表而非集合，使调用方可以保持绘制顺序。
    return [
        emoji_id for emoji_id, rect in rects.items()
        if rect[1] <= bottom and rect[1] + rect[3] >= top
    ]


def outside_ids(rects, top, bottom, hysteresis=DEFAULT_HYSTERESIS):
    # Ids far enough outside the band that their widgets can be destroyed /
    # 离带足够远、其控件可以销毁的 id
    margin = max(0, int(hysteresis))
    return [
        emoji_id for emoji_id, rect in rects.items()
        if rect[1] > bottom + margin or rect[1] + rect[3] < top - margin
    ]


def animation_window(scroll_top, viewport_height, band=DEFAULT_ANIMATION_BAND):
    # Vertical range in which animations run / 运行动画的垂直范围
    top = max(0, int(scroll_top) - max(0, int(band)))
    bottom = int(scroll_top) + max(0, int(viewport_height)) + max(0, int(band))
    return top, bottom


def animation_candidates(rects, scroll_top, viewport_height,
                         band=DEFAULT_ANIMATION_BAND):
    # Animatable ids inside the animation band, ordered by distance from the
    # viewport centre so the most central sticker decodes first.
    #
    # Returns a list of `(distance, emoji_id)` sorted ascending. The distance is
    # what a priority queue needs; the caller maps it onto whatever its decoder
    # calls a priority.
    # 动画带内可播放的 id，按到视口中心的距离排序，使最靠中心的表情最先解码。
    #
    # 返回按升序排列的 `(距离, 表情 id)` 列表。距离正是优先队列需要的量；调用方把它
    # 映射到自己的解码器所称的优先级上。
    top, bottom = animation_window(scroll_top, viewport_height, band)
    centre = int(scroll_top) + max(0, int(viewport_height)) // 2
    scored = []
    for emoji_id, rect in rects.items():
        if rect[1] > bottom or rect[1] + rect[3] < top:
            continue
        rect_centre = rect[1] + rect[3] // 2
        scored.append((abs(rect_centre - centre), emoji_id))
    scored.sort(key=lambda item: item[0])
    return scored


def animation_limit(configured, visible_count, parallel, parallel_floor=64):
    # How many animations may run at once.
    #
    # With parallel rendering enabled the limit is raised to "everything
    # visible, but bounded", because a machine that opted into parallel
    # thumbnails can afford to keep a whole screen animating. Without it the
    # configured number is honoured exactly.
    # 同时可运行多少个动画。
    #
    # 启用并行渲染时上限提升为"全部可见，但有界"，因为选择了并行缩略图的机器可以承受
    # 整屏动画。未启用时严格按配置的数。
    limit = max(1, int(configured))
    if not parallel:
        return limit
    floor = max(limit, int(parallel_floor))
    return max(0, min(int(visible_count), floor))


def animation_selection(scored, limit):
    # Ids that should be animating, given a scored candidate list and a limit.
    # Returns a list ordered by priority so the caller can use the index as the
    # decode priority directly.
    # 给定带评分的候选列表与上限，应该正在播放动画的 id。返回按优先级排序的列表，
    # 使调用方可以直接用下标作为解码优先级。
    count = max(0, int(limit))
    return [emoji_id for _distance, emoji_id in scored[:count]]


def needs_relayout(previous_usable, usable, tolerance=0):
    # Whether a width change is large enough to be worth a relayout. A window
    # resize emits many sub-pixel width changes; ignoring them is what keeps
    # resizing from thrashing the layout.
    # 宽度变化是否大到值得重新布局。缩放窗口会产生大量亚像素级宽度变化；忽略它们正是
    # 避免缩放时反复重排的关键。
    if previous_usable is None:
        return True
    return abs(int(usable) - int(previous_usable)) > max(0, int(tolerance))


__all__ = [
    "DEFAULT_ANIMATION_BAND",
    "DEFAULT_HYSTERESIS",
    "DEFAULT_OVERSCAN",
    "GridMetrics",
    "animation_candidates",
    "animation_limit",
    "animation_selection",
    "animation_window",
    "needs_relayout",
    "outside_ids",
    "visible_ids",
    "visible_window",
]
