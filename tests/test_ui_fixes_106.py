"""Regression for the 1.0.6 UI fixes:
1. the elided name text really FITS the label (no double-sided clipping)
2. the All view reflows in BOTH directions (enlarge adds columns, shrink removes)
3. the settings dialog opens without the ~2 s GPU-detection freeze
4. the text-emoji dialog's buttons are localised (Chinese) in zh_CN
5. an EMPTY group's background is the theme colour, not black
1.0.6 UI 修复回归：
1. 名称截断文本确实放得下（不会左右两侧被裁切）
2. All 视图双向重排（放大增列、缩小减列）
3. 设置对话框打开不再有约 2 秒的显卡检测卡顿
4. 文字表情对话框按钮在中文下为中文
5. 空分组背景为主题色而非纯黑
"""
import collections
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="gifmgr_ui106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PIL import Image
from PySide6.QtWidgets import (QApplication, QScrollArea, QWidget, QVBoxLayout,
                               QPushButton)
from PySide6.QtGui import QFontMetrics
from PySide6.QtCore import Qt

from app.theme.dark_theme import QSS as DARK
from app.theme.light_theme import QSS as LIGHT
from app.models.data_manager import DataManager
from app.models.lang_manager import tr
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.emoji_item import EmojiItem

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


class _DM:
    def emoji_filepath(self, e):
        return None


# --- 1. elided text must FIT (no double-sided clipping) -----------------
app.setStyleSheet(DARK)
bad = []
for scale in (1.0, 1.25, 1.5):
    EmojiItem._card_scale = scale
    for nm in ("gm_conv_f4df2f6d", "gm_conv_6ed960f4",
               "超长表情包名称用于测试滚动显示功能abc",
               "WWWWWWWWWWWWWWW", "mixed混合name名称1234567890"):
        e = {"id": 1, "filename": "x.gif", "group_id": 1,
             "original_name": nm, "text_content": ""}
        c = EmojiItem(e, _DM(), show_name=True, hover_zoom=1.15,
                      hover_enabled=True)
        c.resize(c.card_size(), c.card_height(True))
        c.show()
        app.processEvents()
        lbl = c._name_label
        avail = c._name_available_width()
        shown = lbl.text()
        w = QFontMetrics(lbl.font()).horizontalAdvance(shown)
        if w > avail + 1:      # +1 px tolerance for rounding
            bad.append((scale, nm, w, avail, shown))
        # The shown text must also fit the label's REAL width: the derived
        # available width used to miss the card's stylesheet padding/border
        # (~10 px), so a centred elided text was clipped on both sides and
        # looked permanently truncated (gm_conv_6ed960f4).
        # 显示的文本还必须放得进标签的真实宽度：此前推导的可用宽度漏掉了卡片
        # 样式表的 padding/border（约 10px），居中显示的截断文本被左右裁切，
        # 看起来就是一直被截断（gm_conv_6ed960f4）。
        if lbl.width() > 0 and w > lbl.width() + 1:
            bad.append((scale, nm, w, lbl.width(), shown))
        c.deleteLater()
EmojiItem._card_scale = 1.0
check("截断文本一定放得下（左右不裁切）", not bad, bad[:2])

# --- 2. All view reflows both ways -------------------------------------
dm = DataManager()
gid = dm.create_group("G", "image")
for i in range(18):
    p = os.path.join(TMP, f"a{i}.png")
    Image.new("RGB", (64, 64), (i * 12 % 256, 120, 180)).save(p)
    dm.import_emoji(gid, p, auto_convert=False)

sa = QScrollArea()
sa.setWidgetResizable(True)
sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = None          # All view / All 视图
sa.setWidget(grid)
sa.resize(300, 500)
sa.show()
grid.load_emojis(dm.get_all_emojis(), "image")


def all_cols():
    rects, _tw, _th = grid._all_grid_data(grid._layout_usable())
    return len({r[0] for r in rects.values()})


def settle(w):
    sa.resize(w, 500)
    for _ in range(6):
        app.processEvents()


settle(300)
narrow = all_cols()
settle(900)
wide = all_cols()
settle(300)
back = all_cols()
settle(200)
tiny = all_cols()
check("All 放大增列", wide > narrow, f"{narrow} -> {wide}")
check("All 缩小减列", back == narrow, f"{narrow} -> {wide} -> {back}")
check("All 更窄仍继续减列", tiny <= narrow, f"tiny={tiny}")
check("All 无横向滚动条", sa.horizontalScrollBar().maximum() == 0,
      sa.horizontalScrollBar().maximum())
check("All 网格宽度跟随视口", abs(grid.width() - sa.viewport().width()) <= 4,
      f"grid={grid.width()} vp={sa.viewport().width()}")

# --- 3. settings dialog opens fast (no GPU detection on open) ----------
from app.widgets.settings_dialog import SettingsDialog
t0 = time.perf_counter()
sd = SettingsDialog()
elapsed = time.perf_counter() - t0
check("设置对话框打开 < 0.5s（无卡顿）", elapsed < 0.5, f"{elapsed:.3f}s")
check("显卡检测改为按钮触发", hasattr(sd, "_btn_gpu_probe")
      and sd._btn_gpu_probe.text() == tr("gpu_detect"),
      sd._btn_gpu_probe.text())

# --- 3b. send-mode options: radio dot aligns with its text ------------
# A word-wrapped label sizes its height from sizeHint (two lines even when the
# width fits one); the radio used to be top-aligned, so the dot looked offset
# from the text. Both are centred now.
# 自动换行标签的高度按 sizeHint 计算（宽度够一行时也可能留两行高度）；圆点此前
# 顶对齐，于是相对文字偏移。现在两者都垂直居中。
sd._cat_list.setCurrentRow(1)
for _ in range(8):
    app.processEvents()
_rf, _lf = sd._rb_file.geometry(), sd._label_file.geometry()
_ri, _li = sd._rb_image.geometry(), sd._label_image.geometry()
check("发送模式 第一项圆点与文字居中对齐",
      abs((_rf.y() + _rf.height() // 2) - (_lf.y() + _lf.height() // 2)) <= 1,
      f"radio_c={_rf.y() + _rf.height() // 2} label_c={_lf.y() + _lf.height() // 2}")
check("发送模式 第二项圆点与文字居中对齐",
      abs((_ri.y() + _ri.height() // 2) - (_li.y() + _li.height() // 2)) <= 1,
      f"radio_c={_ri.y() + _ri.height() // 2} label_c={_li.y() + _li.height() // 2}")
check("两项文字左边界一致", _lf.x() == _li.x(),
      f"{_lf.x()} vs {_li.x()}")
check("两项圆点左边界一致", _rf.x() == _ri.x(), f"{_rf.x()} vs {_ri.x()}")

# --- 3c. GPU switch drives parallel rendering --------------------------
from app.widgets.emoji_item import EmojiItem as _EI, _loader as _ld
_prev = _EI.parallel_render_enabled()
_EI.set_parallel_render(True)
_par_threads = _ld._pool.maxThreadCount()
_par_flag = _EI.parallel_render_enabled()
_EI.set_parallel_render(False)
_ser_threads = _ld._pool.maxThreadCount()
_ser_flag = _EI.parallel_render_enabled()
check("GPU 开关存在且默认关闭该对话框", hasattr(sd, "_cb_gpu_accel"))
check("开启后并行渲染线程数 > 串行",
      _par_threads > _ser_threads and _par_flag and not _ser_flag,
      f"parallel={_par_threads} serial={_ser_threads}")
_EI.set_parallel_render(_prev)
sd.close()

# --- 4. text dialog buttons localised ---------------------------------
host = QWidget()
host._theme = "dark"
host.show()
from app.widgets.edit_text_dialog import EditTextDialog
td = EditTextDialog("hello", host)
texts = [b.text() for b in td.findChildren(QPushButton)]
check("文字编辑对话框按钮本地化",
      tr("ok") in texts and tr("cancel") in texts and "OK" not in texts,
      texts)
td.close()

# --- 5. empty group background is the theme colour, not black ---------
for theme_name, qss, expect_dark in (("dark", DARK, True), ("light", LIGHT, False)):
    app.setStyleSheet(qss)
    gid2 = dm.create_group(f"empty_{theme_name}", "image")
    host2 = QWidget()
    host2.resize(400, 400)
    lay = QVBoxLayout(host2)
    lay.setContentsMargins(0, 0, 0, 0)
    sa2 = QScrollArea()
    sa2.setWidgetResizable(True)
    g2 = EmojiGridWidget()
    g2.set_data_manager(dm)
    g2.current_group_id = gid2
    g2.setObjectName("emojiGrid")
    sa2.setWidget(g2)
    lay.addWidget(sa2)
    host2.show()
    g2.load_emojis([], "image")        # empty / 空
    app.processEvents()
    img = host2.grab().toImage()
    hist = collections.Counter()
    for y in range(0, img.height(), 3):
        for x in range(0, img.width(), 3):
            c = img.pixelColor(x, y)
            hist[(c.red(), c.green(), c.blue())] += 1
    dominant = hist.most_common(1)[0][0]
    is_black = dominant == (0, 0, 0)
    lum = sum(dominant) / 3.0
    ok = (not is_black) and ((lum < 100) if expect_dark else (lum > 180))
    check(f"空分组背景为主题色({theme_name})", ok, f"dominant={dominant}")
    host2.deleteLater()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n1.0.6 UI 修复验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
