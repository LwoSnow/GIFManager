"""Regression for the 1.0.6 settings features:
1. rename dialogs auto-select the existing text
2. FFmpeg can be disabled and can point at a user-chosen binary
3. Animated-GIF render concurrency: automatic (by cores) or a custom count
4. all new settings persist across a restart
1.0.6 设置功能回归：
1. 重命名对话框自动全选原文字
2. FFmpeg 可停用，并可指定用户自定义可执行文件
3. 动态 GIF 渲染并发：自动（按核心数）或自定义数量
4. 新设置可跨重启持久化
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="gifmgr_set106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtCore import QSettings

app = QApplication(sys.argv)
# isolate QSettings so the real user config is never touched /
# 隔离 QSettings，避免影响真实用户配置
# NOTE: setDefaultFormat(IniFormat) + setPath() do NOT isolate anything --
# QSettings("Org","App") keeps using the native registry format, so this test
# used to write ffmpeg / GIF-render values into the user's real key.
# 注意：setDefaultFormat(IniFormat) + setPath() 并不能隔离——QSettings("Org",
# "App") 仍使用原生注册表格式，本测试以前会把 ffmpeg / GIF 渲染取值写进用户
# 真实键。
from tests._iso import isolate_all, drain_and_exit  # noqa: E402

isolate_all()

from app.utils import gif_converter
from app.widgets.rename_dialog import RenameDialog
from app.widgets.settings_dialog import SettingsDialog
from app.models.data_manager import DataManager
import app.main_window as mw

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


# --- 1. rename auto-select ------------------------------------------------
dlg = RenameDialog("原有名称文字")
dlg.show()
app.processEvents()
ed = dlg.findChildren(QLineEdit)[0]
check("重命名自动全选", ed.selectedText() == "原有名称文字",
      f"selected={ed.selectedText()!r}")
check("全选起始位置为 0", ed.selectionStart() == 0, ed.selectionStart())
dlg.close()

# --- 2. ffmpeg config ----------------------------------------------------
check("默认启用 ffmpeg", gif_converter.ffmpeg_enabled() is True)
gif_converter.set_ffmpeg_config(enabled=False)
check("停用后 ffmpeg_path 为 None", gif_converter.ffmpeg_path() is None,
      gif_converter.ffmpeg_path())
gif_converter.set_ffmpeg_config(enabled=True)
_bundled = gif_converter.ffmpeg_path()
check("启用后恢复内置路径", bool(_bundled), _bundled)
# a user-chosen path wins / 用户指定路径优先
_fake = os.path.join(TMP, "my_ffmpeg.exe")
with open(_fake, "wb") as f:
    f.write(b"x")
gif_converter.set_ffmpeg_config(path=_fake)
check("自定义路径优先", gif_converter.ffmpeg_path() == _fake,
      gif_converter.ffmpeg_path())
# a missing custom path falls back to the bundled binary / 路径失效时回退内置
gif_converter.set_ffmpeg_config(path=os.path.join(TMP, "nope.exe"))
check("失效路径回退内置", gif_converter.ffmpeg_path() == _bundled,
      gif_converter.ffmpeg_path())
gif_converter.set_ffmpeg_config(path="")
# probe reports a usable binary / 探测可用性
if _bundled:
    _ok, _info = gif_converter.ffmpeg_probe(_bundled)
    check("ffmpeg 探测成功", _ok, _info[:60])
_bad_ok, _bad_info = gif_converter.ffmpeg_probe(os.path.join(TMP, "nope.exe"))
check("ffmpeg 探测失败有原因", _bad_ok is False and bool(_bad_info),
      _bad_info[:60])

# --- 3. settings dialog getters -----------------------------------------
sd = SettingsDialog(ffmpeg_enabled=False, ffmpeg_path="C:/x/ffmpeg.exe",
                    gif_render_mode="manual", gif_render_count=9,
                    gpu_accel=True, gpu_pref=2)
check("设置回显 ffmpeg", sd.ffmpeg_enabled() is False
      and sd.ffmpeg_path() == "C:/x/ffmpeg.exe",
      f"{sd.ffmpeg_enabled()} {sd.ffmpeg_path()}")
# "Use a specific GPU" is now expressed by the adapter choice itself /
# "是否使用指定显卡"现在由适配器选择本身表达
check("设置回显 GIF 渲染", sd.gif_render_mode() == "manual"
      and sd.gif_render_count() == 9 and sd.gpu_render() is True,
      f"{sd.gif_render_mode()} {sd.gif_render_count()} {sd.gpu_preference()}")
check("默认值为自动模式", SettingsDialog().gif_render_mode() == "auto")
check("停用 ffmpeg 时路径控件禁用",
      not sd._edit_ffmpeg_path.isEnabled())
sd.close()

# --- 4. gif render concurrency drives the grid limit --------------------
w = mw.MainWindow()
w.data_manager = DataManager()
w.show()
app.processEvents()
w._gif_render_mode = "auto"
w._gif_render_count = 0
w._apply_thread_count()
_auto_limit = w.emoji_grid._gif_limit
check("自动模式按核心数分配", _auto_limit >= 8, _auto_limit)
w._gif_render_mode = "manual"
w._gif_render_count = 5
w._apply_thread_count()
check("自定义模式使用指定数量", w.emoji_grid._gif_limit == 5,
      w.emoji_grid._gif_limit)

# --- 5. persistence round-trip ------------------------------------------
w._ffmpeg_enabled = False
w._ffmpeg_path = "C:/custom/ffmpeg.exe"
w._gif_render_mode = "manual"
w._gif_render_count = 11
w._gpu_pref = 2
w._save_settings()
w2 = mw.MainWindow()
w2.data_manager = DataManager()
check("持久化 ffmpeg 设置",
      w2._ffmpeg_enabled is False and w2._ffmpeg_path == "C:/custom/ffmpeg.exe",
      f"{w2._ffmpeg_enabled} {w2._ffmpeg_path}")
check("持久化 GIF 渲染设置",
      w2._gif_render_mode == "manual" and w2._gif_render_count == 11
      and w2._gpu_pref == 2,
      f"{w2._gif_render_mode} {w2._gif_render_count} {w2._gpu_pref}")
check("停用状态同步到 gif_converter",
      gif_converter.ffmpeg_enabled() is False,
      gif_converter.ffmpeg_enabled())
# restore for other tests / 恢复，避免影响其他测试
gif_converter.set_ffmpeg_config(enabled=True, path="")

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n1.0.6 设置功能验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
