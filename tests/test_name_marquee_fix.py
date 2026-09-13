"""Regression: some long names never scrolled.
Root cause: the "does the name fit?" test used the name label's own width,
which around layout time is unreliable (0, or a bogus default such as 640
before the card is laid out). With that bogus wide value the check wrongly
concluded the name fit, so the marquee never started for those cards — some
long names scrolled, others did not.
回归：部分长名称从不滚动。
根因："名称是否放得下"的判断用了名称标签自身宽度，而该宽度在布局前后不可靠
（未布局时可能是 0 或假值，如 640）。用这个偏大的假值会误判为"放得下"，
导致这些卡片从不启动跑马灯——于是部分长名称能滚动、部分不能。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontMetrics

from app.widgets.emoji_item import EmojiItem

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


class _DM:
    def emoji_filepath(self, e):
        return None


def make_card(name, font=10):
    EmojiItem.set_name_font_size(font)
    e = {"id": 1, "filename": "x.gif", "group_id": 1,
         "original_name": name, "text_content": ""}
    return EmojiItem(e, _DM(), show_name=True, hover_zoom=1.15,
                     hover_enabled=True)


LONG = "averyveryverylongstickername"

# 1. The reported case: the fit check runs while the label still reports a
#    bogus (unlaid-out) width — the marquee must still start.
# 报告的场景：判断发生在标签仍报告假宽度（未布局）时——必须仍启动跑马灯。
card = make_card(LONG)
_lbl = card._name_label
check("复现前提：未布局时标签宽度失真", _lbl.width() != card._name_available_width(),
      f"lbl={_lbl.width()} avail={card._name_available_width()}")
card._start_name_scroll()
check("未布局卡片仍启动跑马灯", card._name_scroll_timer is not None,
      f"lblw={_lbl.width()}")
card._stop_name_scroll()

# 2. The derived width must match the real laid-out label width once shown.
card2 = make_card(LONG)
card2.resize(100, 120)
card2.show()
app.processEvents()
check("推导可用宽度等于实际标签宽度",
      card2._name_available_width() == card2._name_label.width(),
      f"avail={card2._name_available_width()} lbl={card2._name_label.width()}")

# 3. Sweep lengths x fonts: every overflowing name must start AND its rendered
#    window must never exceed the available width (no clipping).
# 扫描长度 × 字号：所有溢出的名称都必须启动，且渲染窗口不得超过可用宽度。
bad_start = []
bad_overflow = []
for font in (10, 12, 14, 16, 20):
    for n in range(13, 31):
        nm = "".join(chr(ord("a") + (i % 26)) for i in range(n))
        c = make_card(nm, font)
        c.resize(100, 120)
        c.show()
        app.processEvents()
        avail = c._name_available_width()
        fm = QFontMetrics(c._name_label.font())
        overflows = fm.horizontalAdvance(nm) > avail
        c._start_name_scroll()
        started = c._name_scroll_timer is not None
        if overflows and not started:
            bad_start.append((font, n))
        if started:
            c._tick_name_scroll()
            win_w = fm.horizontalAdvance(c._name_label.text())
            if win_w > avail:
                bad_overflow.append((font, n, win_w, avail))
        c._stop_name_scroll()
        c.deleteLater()
check("所有溢出名称均启动跑马灯", not bad_start, f"missing={bad_start[:5]}")
check("滚动窗口不超出标签宽度", not bad_overflow, f"overflow={bad_overflow[:3]}")

# 4. Ticks must actually change the text (it scrolls, not just truncates).
c3 = make_card(LONG)
c3.resize(100, 120)
c3.show()
app.processEvents()
c3._start_name_scroll()
seen = set()
for _ in range(12):
    c3._tick_name_scroll()
    seen.add(c3._name_label.text())
check("滚动文本逐帧变化", len(seen) > 1, f"distinct={len(seen)}")
c3._stop_name_scroll()
check("停止后恢复省略号", c3._name_label.text().endswith("…"))

# 5. A short name (fits) must NOT start the marquee.
c4 = make_card("短名")
c4.resize(100, 120)
c4.show()
app.processEvents()
c4._start_name_scroll()
check("短名称不启动跑马灯", c4._name_scroll_timer is None)

# 6. Consistency across card scales using the user's real reported name:
#    a name that FITS must be shown in FULL and not scroll; a name that
#    OVERFLOWS must be elided and scroll. (The static text used to be
#    truncated by a fixed 12-char limit even when it fit, so a fitting name
#    appeared permanently truncated and never scrolled.)
#    用用户实际报告的名称验证各缩放下的自洽性：放得下就完整显示且不滚动，
#    溢出就截断并滚动。（旧实现按固定 12 字截断，放得下时也显示截断且不滚动。）
REAL_NAME = "gm_conv_f4df2f6d"
bad = []
for _scale in (1.0, 1.25, 1.5, 1.75, 2.0):
    EmojiItem._card_scale = _scale
    c5 = make_card(REAL_NAME)
    c5.resize(c5.card_size(), c5.card_height(True))
    c5.show()
    app.processEvents()
    _lbl5 = c5._name_label
    _avail = c5._name_available_width()
    _full = QFontMetrics(_lbl5.font()).horizontalAdvance(REAL_NAME)
    c5._hovered = True
    c5._start_name_scroll()
    _scrolls = c5._name_scroll_timer is not None
    _fits = _full <= _avail
    if _fits:
        _ok = (_lbl5.text() == REAL_NAME) and not _scrolls
    else:
        _ok = (_lbl5.text() != REAL_NAME) and _scrolls
    if not _ok:
        bad.append((_scale, _avail, _full, _lbl5.text(), _scrolls))
    c5._stop_name_scroll()
EmojiItem._card_scale = 1.0
check("各缩放下列表截断与滚动自洽", not bad, bad[:3])

# 7. Hover watchdog restarts the marquee without relying on underMouse().
c6 = make_card(REAL_NAME)
c6.resize(100, 120)
c6.show()
app.processEvents()
c6._stop_name_scroll()   # clear anything started by the implicit enter
c6._hovered = False
c6._ensure_name_scroll()
check("未悬停时看门狗不启动", c6._name_scroll_timer is None)
c6._hovered = True
c6._ensure_name_scroll()
check("悬停时看门狗启动跑马灯", c6._name_scroll_timer is not None)
c6._stop_name_scroll()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n长名称跑马灯修复验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
