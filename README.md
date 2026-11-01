# GIFManager Next

> 模块化重构版 GIFManager —— 前后端分离、平台隔离，为多平台支持做准备
>
> A modularised GIFManager: toolkit-free core, an explicit platform layer, and a
> front-end that talks to a backend instead of reaching into it.

---

## 这是什么

`GIFManager` 的完全模块化重构版本。原项目是一个 PySide6 写的 Windows 表情包管理器，
功能完整但有许多冗余

本项目将GIFManager的前后端彻底分开，以便后续的跨平台支持：

| 层            | 目录                     | 语言           | 说明                          |
| ------------ | ---------------------- | ------------ | --------------------------- |
| **core**     | `gifmanager/core/`     | Python（仅标准库） | 无 Qt、无系统专有模块                |
| **platform** | `gifmanager/platform/` | Python       | Windows 完整实现，macOS/Linux 骨架 |
| **backend**  | `gifmanager/backend/`  | Python       | 完成                          |
| **frontend** | `gifmanager/frontend/qml/` | **Python + QML** | 当前前端：外壳、设置页、表情库、卡片      |
|              | `gifmanager/frontend/qt/`  | Python + Qt Widgets | 替代前端，同一后端契约             |
| **native**   | `native/`              | **Rust**     | 图像管线：GIF 解码 + 缩略图缩放，可选      |
| **apps**     | `apps/`                | Python       | 两个启动器，每个前端一个                |

### 前端有两个，为什么

两个前端实现**同一份后端契约**，因此可以互相对照：

```bash
python apps/gifmanager_qml.py    # QML 前端（当前）
python apps/gifmanager_qt.py     # Qt Widgets 前端（替代）
```

同一数据目录、同一台机器、运行之间无需改文件，因此"某个界面行为是前端问题还是后端
问题"可以直接对比回答。

### QML 前端的三个关键事实

1. **QSS 对 Qt Quick Controls 不生效**。样式表是 Qt Widgets 的机制，因此
   `frontend/qt/theme/` 的两份样式表无法复用；调色板改由 Python 的 `ThemeBridge`
   承载并经 `theme` 上下文属性暴露。详见 [docs/QML_FRONTEND.md](docs/QML_FRONTEND.md)。
2. **设置页是 schema 驱动的**。`settings_model.py` 声明行，一个 QML 委托按 `kind`
   渲染全部控件——新增一项设置只需加一行。
3. **列表由 Python 模型驱动**。`QAbstractListModel` 上报变更，Qt Quick 原生虚拟化网格，
   因此无需手写卡片池与可视带计算。

### 为什么图像管线是 Rust

一句话：**只有图像解码与重采样值得换语言，而 Rust 是这台机器上唯一能可靠构建的
工具链。** 设备上的 C++ 是 GCC 4.9.2（2014 年，只支持 C++11），没有 cmake、没有
ninja；而 Rust 是 1.99。

实测（`python tests/bench_native.py`，16 逻辑核心）：

| 场景 | Rust | 对比 | 比值 |
|---|---|---|---|
| 缩略图 1200×900 → 76px | 5.3 ms | `QImage.scaled` 9.5 ms | **1.80×** |
| GIF 24 帧 → 缩放 | 12.0 ms | C 库 13.1 ms | **1.09×** |
| GIF 24 帧 → 不缩放 | 14.1 ms | C 库 12.9 ms | 0.92×（更慢） |

**GIF 解码并不比 C 快**，选 Rust 的理由是另外三个：正确性（C 解码器忽略 GIF 处置
方式，会留拖影与黑框）、可移植性（一份源码服务三平台，而 `gifdec.dll` 是 Windows
二进制）、以及并行逐帧缩放。详见 [docs/LANGUAGE_DIVISION.md](docs/LANGUAGE_DIVISION.md)。

**原生管线是可选的。** 没有 Rust 工具链时程序照常运行，按
`Rust → 随包 C 库 → QMovie` 逐级回退，且 `images.describe()` 始终报告当前生效的
是哪条路径。

---

## 快速开始

**完整运行说明（含各平台注意事项、环境变量、故障排查）见 [docs/RUNNING.md](docs/RUNNING.md)。**

### 一分钟版

```powershell
# Windows
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe apps\gifmanager_qml.py
```

```bash
# Linux / macOS
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python apps/gifmanager_qml.py
```

需要 Python **3.10+**（开发用 3.12.0）。**不需要 Rust**：原生图像管线可选，缺失时自动降级。

### 两个前端

| 命令 | 前端 |
|---|---|
| `python apps/gifmanager_qml.py` | **QML**（当前主推） |
| `python apps/gifmanager_qt.py` | Qt Widgets（替代） |

两者实现同一份后端契约，共用同一数据目录，因此可对比定位问题。

### 建议：用项目自带的虚拟环境

`.venv/` 是项目自己的环境，不依赖任何外部项目，已在 `.gitignore` 中。所有工具与 make 目标
都应使用它：

```bash
make check PYTHON=.venv/Scripts/python.exe     # Windows
make check PYTHON=.venv/bin/python             # macOS / Linux
```

### 后端不依赖 Qt

`core` + `platform` + `backend` 三层可以在**不加载 Qt** 的情况下导入并运行：

```bash
.venv/Scripts/python.exe -c "import gifmanager.core, gifmanager.platform, gifmanager.backend; \
                             print('PySide6' in __import__('sys').modules)"   # -> False
```

---

## 目录结构

```
GIFManager_Next/
├── gifmanager/
│   ├── core/                      # 纯 Python，无 Qt、无系统专有模块
│   │   ├── constants.py           #   窗口与网格常量
│   │   ├── paths.py               #   数据/资源/日志目录解析（平台规则以注入方式提供）
│   │   ├── fileops.py             #   可移植文件操作（MD5、重命名、GIF 头升级）
│   │   ├── grid_layout.py         #   网格布局纯运算（分列、矩形、命中测试）
│   │   ├── settings.py            #   设置 schema、默认值、校验、迁移
│   │   ├── hotkeys.py             #   可移植热键绑定
│   │   ├── gpu.py                 #   GPU 首选项策略与显卡分类
│   │   ├── version.py             #   版本号解析与比较
│   │   ├── lang.py                #   多语言
│   │   ├── logging_setup.py       #   崩溃安全日志
│   │   ├── imaging/               #   格式嗅探（signatures）与转换（converter）
│   │   └── store/                 #   SQLite：表结构 + 四个仓储
│   ├── platform/                  # 唯一知道自己跑在哪个系统上的地方
│   │   ├── base.py                #   服务接口与注册表
│   │   ├── paths.py               #   按用户目录分发
│   │   ├── process.py             #   子进程启动（控制台抑制、编码）
│   │   ├── windows.py             #   注册表、DWM、SendInput、RegisterHotKey
│   │   ├── macos.py               #   LaunchAgent、Carbon、CGEvent
│   │   └── linux.py               #   XDG、X11 XGrabKey、DRI_PRIME
│   ├── backend/                   # 应用服务与前端契约
│   │   ├── app.py                 #   Backend 门面 + 变更通知
│   │   └── settings_store.py      #   JSON 设置存储（原子写入）
│   └── frontend/qt/               # Qt 外壳
│       ├── shell.py               #   进程设置、单实例、事件循环
│       ├── shell_window.py        #   主窗口：导航 + 菜单 + 快捷键 + 状态栏
│       ├── commands.py            #   命令注册表（一个操作，三条到达路径）
│       ├── views/                 #   页面：base 协议 + library 表情库
│       ├── bridge.py              #   后端 → Qt 队列信号
│       ├── images.py              #   Rust 原生管线的 ctypes 绑定 + 回退
│       ├── thumbnails.py          #   线程池缩略图加载 + 显式缓存
│       ├── animation.py           #   GIF 解码（Rust → C 库 → QMovie 三级回退）
│       ├── virtual.py             #   虚拟化窗口运算
│       ├── widgets/               #   网格、卡片、分组栏、搜索栏
│       ├── dialogs/               #   重命名、文字编辑、重复删除
│       └── theme/                 #   深色 / 浅色样式表
├── native/                        # Rust 图像管线（可选）
│   ├── Cargo.toml
│   └── src/lib.rs                 #   GIF 解码合成 + SIMD 缩放，C ABI
├── apps/gifmanager_qt.py          # 启动器
├── scripts/                       # 原生构建脚本（ps1 / sh）
├── resources/language/            # 翻译文件
├── tests/                         # 125 单元/集成测试 + 6 个冒烟检查 + 基准
├── tools/                         # 分层检查、风格检查、Makefile 检查
└── docs/                          # 架构、语言分工、重构报告
```

---

## 相比原项目改了什么

这份重构**不是为了改功能**，而是为了让功能可以被多个平台和多种界面复用。但过程中
确实修掉了一批真实缺陷：

| # | 问题 | 处理 |
|---|---|---|
| 1 | `hotkey_manager.py` 在模块级执行 `ctypes.windll.user32`，且被 `main_window` 模块级导入 —— **macOS/Linux 上程序完全无法启动** | 热键移入 `platform/windows.py`，注册在专用线程上跑自己的消息循环；非 Windows 分配到明确的"不支持"实现 |
| 2 | 同一段 DWM 圆角代码在 4 个文件里重复，各带一份 `sys.platform` 判断 | 统一为 `platform.window().apply_rounded_corners()` |
| 3 | `_last_move_error` 只被赋值、从未初始化，也从未被读取 —— 移动表情失败时用户看不到任何提示 | `last_move_error` 正式声明并暴露 |
| 4 | `delete_emoji()` 恒返回 `None`，导致 `main_window` 里的成功分支是死代码 | 返回布尔值，删除行数可查 |
| 5 | 分组目录以分组名命名，而重名检查是大小写敏感的 SQL 比较；Windows/macOS 默认文件系统大小写不敏感 —— `Test` 与 `test` 会共用目录，删除其一毁掉另一个 | 新增大小写不敏感目录冲突检查 |
| 6 | `settings_dialog.py` 完全没有 `QSettings` 代码，33 个键在 `_load_settings`、`_save_settings` 和 35 个构造函数参数里各写一遍，且互不一致（`theme`、`language`、`gpu_adapters` 漏了 `type=`） | 一份 dataclass schema 派生键清单、校验、序列化、差分与能力门控 |
| 7 | 线程池异常从未被记录（只装了 `sys.excepthook`） | 补上 `threading.excepthook` |
| 8 | 全局 `QPixmapCache` 当返回通道用，让网格与卡片之间的依赖藏在一个字符串键后面 | 显式注入的 `ThumbnailCache` |
| 9 | 卡顿计数器：`_update_visible_gifs` 用硬编码 150px 带，`_ensure_visible` 用 300px 缓冲，两者不一致 | `virtual.py` 中两个具名常量，各回答各的问题 |
| 10 | `gif_player` 硬编码 `gifdec.dll` 与 `sys.frozen` 候选路径 | 按平台解析库名（`.dll`/`.dylib`/`.so`） |

---

## 平台支持现状

`python -c "from gifmanager.platform import describe; print(describe())"` 会打印当前
系统实际提供哪些服务。这张表也驱动设置界面的能力门控：**做不到的功能会被禁用，
而不是显示一个静默无效的控件**。

| 服务 | Windows | macOS | Linux (X11) | Linux (Wayland) |
|---|---|---|---|---|
| 数据目录 | `%APPDATA%` / `%LOCALAPPDATA%` | `~/Library/Application Support` | `$XDG_DATA_HOME` | 同左 |
| 单实例 | 命名互斥量 | 未实现 | 未实现 | 未实现 |
| 窗口圆角 | DWM | 系统自带，直接报告成功 | 合成器负责 | 合成器负责 |
| 全局热键 | `RegisterHotKey`（专用线程） | Carbon 骨架，需辅助功能授权 | `XGrabKey` | **XDG Portal `GlobalShortcuts`** |
| 全局滚动 | 低级鼠标钩子 | `CGEventTap` 骨架 | XInput2 骨架 | **无等价物** |
| 输入注入 | `SendInput` + `WM_PASTE` | `CGEventPost`（需授权） | `xdotool` | **平台禁止** |
| GPU 首选项 | 注册表 | 系统自动，不提供 | PRIME，不提供 | 同左 |
| 开机自启 | `HKCU\...\Run` | LaunchAgent plist | XDG `.desktop` | 同左 |
| 系统托盘 | ✅ 真机验证 | 未验证 | 未验证 | 未验证 |
| 更新安装 | 启动安装器 | 打开包 | 下载并告知（包管理器拥有文件） | 同左 |

### Wayland 上的全局热键与 X11 语义不同

这是**平台限制而非缺陷**，三条差异都会影响用户预期：

1. 应用**不能选择**组合键。可以建议一个，但**合成器弹出自己的对话框并决定**；门户回报实际
   绑定值，界面显示的是那个实际值而不是请求值。
2. 应用**不拥有**该绑定，**会话**拥有。关闭会话即释放，崩溃也不会永久占住一个组合键。
3. 应用**不能消费**按键，合成器改为投递 `Activated` 信号。

针对**门户**而非 `zwp_global_shortcuts_v1` 实现：那个 wlroots 协议在 Sway 与 Hyprland 上可用、
在 GNOME 与 KDE 上毫无作用，而门户是跨桌面接口。缺 `xdg-desktop-portal` 时后端**如实报告
不可用并给出原因**，设置页禁用该控件。

**macOS / Linux 尚未端到端验证过。** Wayland 门户的协议逻辑有测试覆盖
（`tests/smoke_wayland.py` 用伪 D-Bus 传输层驱动状态机），但**没有任何 Linux 机器运行过它**；
macOS 的热键与输入注入仍是骨架。请把首次运行视为验证而非使用。

---

## 开发

```bash
# 全量测试（含离屏 Qt，无需显示器）
python -m unittest discover -s tests -t . -p "test_*.py"

# 层约束检查：core 不得导入 Qt / ctypes / winreg，不得判断 sys.platform
python tools/check_layers.py

# 代码规范检查（PEP8 + 双语注释 + 行宽）
python tools/check_style.py gifmanager apps tests tools

# 六个冒烟检查
python tests/smoke_core.py
QT_QPA_PLATFORM=offscreen python tests/smoke_qt.py
QT_QPA_PLATFORM=offscreen python tests/smoke_launcher.py
QT_QPA_PLATFORM=offscreen python tests/smoke_shell.py
QT_QPA_PLATFORM=offscreen python tests/smoke_native.py
QT_QPA_PLATFORM=offscreen python tests/smoke_native_contract.py

# 构建可选的原生管线，并测量它与纯 Qt 路径的差距
powershell -File scripts/build-native.ps1     # Windows
sh scripts/build-native.sh                    # macOS / Linux
python tests/bench_native.py
```

`make check` 会依次跑分层检查、风格检查与测试；`make smoke` 跑全部六个冒烟检查。

### 当前验证状态

| 检查 | 结果 |
|---|---|
| `python -m compileall` | 通过 |
| `tools/check_layers.py` | 通过 —— core 无 Qt、无系统专有模块、无 `sys.platform` |
| `tools/check_style.py` | 通过（行宽 ≤100、注释双语、三引号仅在文件头） |
| `tools/check_makefile.py` | 通过 —— 编码干净、配方以制表符缩进 |
| `unittest` | 125 个测试全部通过 |
| `smoke_core.py` | 退出码 0 —— 分层与平台服务 |
| `smoke_qt.py` | 退出码 0 —— 构建窗口、加载、搜索、切主题 |
| `smoke_launcher.py` | 退出码 0 —— 真实启动器：单实例 → 后端 → 窗口 → 有序退出 |
| `smoke_shell.py` | 退出码 0 —— 导航、生命周期、命令注册表、快捷键、谓词 |
| `smoke_native.py` | 退出码 0 —— 与 Pillow 对照的像素正确性 |
| `smoke_native_contract.py` | 退出码 0 —— 20/20 符号、指针返回类型、隐藏库后仍可回退 |

`core` + `platform` + `backend` 三层可以在**不加载 Qt** 的情况下导入并运行，
这正是多平台支持的基础：

```bash
python -c "import gifmanager.core, gifmanager.platform, gifmanager.backend; \
           print('PySide6' in __import__('sys').modules)"   # -> False
```

---

## 代码规模

| 层 | 行数 | 最大单文件 |
|---|---|---|
| core | 5093 | `settings.py` 609 行 |
| platform | 3255 | `windows.py` 1187 行（纯平台代码） |
| backend | 582 | `app.py` 约 350 行 |
| frontend/qml | ~3400 | 桥 + 模型 + 导入器 + 动画器 + 9 个 QML 文件 |
| frontend/qt | 3953 | Qt Widgets 替代前端 |

对比原项目：`main_window.py` 2452 行、`emoji_grid.py` 1941 行、
`settings_dialog.py` 1781 行、`data_manager.py` 1601 行。

---

## 尚未实现的功能

前端**可用**且已覆盖日常操作，但还不是功能完整的。以下功能已有明确的后端接口，缺的是界面：

| 功能 | 将要调用的接口 | 缺口 |
|---|---|---|
| 拖拽排序 | `core.grid_layout` 的列/序算术 | QML 的 `Drag`/`DropArea` |
| 分组管理（新建/重命名/删除） | `store.create_group` / `rename_group` / `delete_group` | QML 分组栏目前只读 |
| 新建文字表情 | `store.add_text_emoji` | 一个输入对话框 |
| 多选（框选/Shift 点选） | `stickers.selectAll` / `clearSelection` | QML 交互 |
| ffmpeg 路径浏览 | `QFileDialog` | 设置页按钮当前只弹提示 |
| GPU 适配器列表 | `platform.gpu_preference()`、`core.gpu.classify_adapter()` | 展示列表 |
| 自动粘贴到聊天窗口 | `platform.input_backend()` 的四个方法 | 发送路径接线 |
| 就地更新 | `core.version`、`core.settings.installer_asset_name()` | 下载传输待定 |
| macOS / Linux 后端 | `platform/macos.py` / `platform/linux.py` | 骨架，**从未在真机运行** |

完整的逐项完成度与证据见 [docs/COMPLETION_CHECKLIST.md](docs/COMPLETION_CHECKLIST.md)。
| 文件/文件夹导入对话框 | `store.import_emojis_batch()`（流水线已完整） |
| GIF 播放驱动 | `frontend.qt.animation` + `frontend.qt.virtual.animation_candidates()` |
| 拖拽重排、编辑模式 | `core.grid_layout` 的矩形运算（接缝已标注） |

每一处都在源码里标注了具体位置，见 `main_window.py` 与 `widgets/emoji_grid.py` 末尾。

---

## 许可

MIT，与原项目一致。
