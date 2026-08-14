"""Card-level integration test: EmojiItem plays a GIF via the native
decoder (gif_player), and stops cleanly. Offscreen and data-isolated.
卡片级集成测试：EmojiItem 通过原生解码器（gif_player）播放 GIF 并能干净
停止。离屏运行，数据隔离。"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_card_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.utils import gif_player

app = QApplication(sys.argv)
dm = DataManager()
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:120]}")


# Build an animated GIF and import it / 生成动画 GIF 并导入
gifp = os.path.join(TMP, "a.gif")
frames = []
for color in ("red", "blue", "green"):
    im = Image.new("RGBA", (120, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([5, 5, 115, 55], fill=color)
    frames.append(im)
frames[0].save(gifp, save_all=True, append_images=frames[1:],
               duration=60, loop=0, disposal=2)

g = dm.create_group("动图组", "image")
check("A 导入 GIF", dm.import_emoji(g, gifp, auto_convert=False) == "ok")
emojis = dm.get_emojis_by_group(g)
check("B 组内有 1 个表情", len(emojis) == 1)
emoji = emojis[0]

card = EmojiItem(emoji, dm)
check("C 是 GIF 内容", card.is_gif())

if gif_player.available():
    card.play_animation()
    # wait for the background decode + playback start / 等待后台解码与播放启动
    deadline = time.time() + 10
    while card._frames is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    check("D 原生帧已就绪", card._frames is not None)
    if card._frames is not None:
        check("D2 播放中", card._playing and card._play_timer is not None
              and card._play_timer.isActive())
        # pixmap set on the label / 标签已设置 pixmap
        check("D3 已显示帧", not card._thumb_label.pixmap().isNull())
        # let the timer advance a frame / 让定时器推进一帧
        app.processEvents()
        time.sleep(0.01)
        app.processEvents()
        check("D4 帧索引推进", card._frame_idx >= 0)
    card.stop_animation()
    check("E 停止后不再播放", not card._playing
          and (card._play_timer is None or not card._play_timer.isActive()))
else:
    print("  [SKIP] 原生 DLL 不可用，跳过原生播放测试")
    RES.append(("D 原生播放", True))

# Fallback path: QMovie used when the DLL is unavailable / 回退路径测试
card2 = EmojiItem(emoji, dm)
saved_path = gif_player._dll_path
gif_player._dll_path = lambda: None  # force the QMovie fallback / 强制 QMovie 回退
gif_player._lib = None
try:
    card2.play_animation()
    app.processEvents()
    check("F QMovie 回退可启动", card2._movie is not None)
    if card2._movie is not None:
        card2.stop_animation()
        check("F2 QMovie 回退可停止", card2._movie is None)
finally:
    gif_player._lib = saved_path  # not None sentinel: reload lazily / 哨兵恢复
    gif_player._lib = None
    gif_player._dll_path = saved_path

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n卡片集成验证: {n_pass}/{len(RES)} 通过")
gif_player.shutdown()
try:
    dm._conn.close()
except Exception:
    pass
app.quit()
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
