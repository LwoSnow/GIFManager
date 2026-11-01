<p align="center"><img src="assets/logo.png" width="128" alt="GIFManager logo"></p>

<h1 align="center">GIFManager</h1>

<p align="center"><b>你的表情包、贴纸与动图库 —— 一个快捷键，直达任何应用。</b></p>

<p align="center">
  <b>简体中文</b> ·
  <a href="README.md">English</a>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-2.0.0-4a4a55?style=flat-square">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square">
  <img alt="qt" src="https://img.shields.io/badge/Qt-6.11-41cd52?style=flat-square">
  <img alt="platforms" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-2ea44f?style=flat-square">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square">
</p>

<p align="center"><img src="https://count.getloli.com/@Lwogifmanagerreadnums?theme=moebooru" alt="ReadNums"></p>

GIFManager 管的是那些你一天要发上百遍的图 —— 反应动图、贴纸、普通 emoji，偶尔还有一句短
文案。它们都在你自己的硬盘上。按一下全局快捷键，点一张卡片，内容就已经在剪贴板里，等着你粘，
或者已经替你粘好了。

不用注册。素材库就是你文件旁边的一个 SQLite 数据库，发送链路上不发一个网络请求。

![素材库窗口](assets/screenshot.png)

## 它能做什么

一个自己整理的素材库。图片分组放图，文字分组放文字，两者从不混在一起，所以右边那栏是什么
永远不含糊。可以从文件导入，也可以整个文件夹递归导入。还不是 GIF 的图会在导入时自动转换（动画
源走 ffmpeg，静态图走 Pillow），于是一个装满 PNG 的文件夹直接变成 GIF 素材库，不需要第二个工具。
边打边搜当前分组。排序可以按导入时间、名称，或按你实际使用的次数；最后这个是真统计的，每发
一次加一。

不离开键盘就能发出去。快捷键可以是一个单独的键（`F10`），也可以是组合键（`Ctrl+Alt+F8`）。
允许单键是有意的：一个托盘小工具只有这一个快捷键，还要按修饰键，只会更难用，并不更安全。点一下，
图片本身或它的文件路径进剪贴板。路径是 QQ、微信能直接吃下的形式，用哪种是一个设置项。打开自动
粘贴后，粘贴按键会发回它出现之前你所在的那个窗口，于是整个交互就是：快捷键 → 点一下 → 已经在
聊天框里。托盘图标负责显示、隐藏、退出。Windows 上再启动一次只会提示已经有一份在跑；Linux 上
（快捷键归合成器管）它把 `--toggle`、`--show`、`--hide`、`--quit` 转给正在运行的那份。

整库编辑，不是一张张改。编辑模式把网格变成选择面：点一下切换一张，拖动涂抹选中一片，全选或
全不选，然后一次性删除或移动。卡片也能手动拖着排顺序。文字贴纸用来放那些"是一句话而不是一张
图"的东西，单行和多行各有独立的长度上限。

安静是默认的。深色、浅色主题在选中那一刻就生效：不重启，不弹确认框。HarmonyOS Sans SC 六个
字重随包发出，网格和对话框在任何机器上的度量都一致，而不是继承宿主恰好装了什么字体。配色故意
压低了对比：基础表面彼此只差几个百分点，只有选中的卡片是亮的。一个一天要开几十次的窗口没资格
吵。无边框，记住上次分组和窗口位置，可以置顶，可以随系统启动。

上千张贴纸也不卡。帧在工作线程池里解码，绝不在负责绘制的那条线程上，并按像素预算缓存。只有
屏幕上的动画在播，其余保持一帧静态。解码队列最新优先，已经滚过去的请求直接丢掉，所以在很大的
分组里快速滑动时，当前这一行不用排在你早就不看的那些行后面干等。

要真正播起来，得有一个原生解码器。`make native` 构建 `native/` 里的 Rust 解码器，给
`scripts/build-native.*` 加 `--install` 会把它复制进 `resources/`，打包版才能带上它；另一条路是从
`resources/gifdec.c` 编译出来的 C 帮手。两个都没有的时候，GIF 卡片显示首帧，不会动。

## 平台支持

| | Windows | Linux | macOS |
|---|---|---|---|
| 界面（Qt Quick） | ✅ | ✅ | ⚠️ 未测试 |
| 无边框窗口、圆角 | ✅ DWM | ✅ | ⚠️ 未测试 |
| 全局快捷键 | ✅ `RegisterHotKey` | ✅ X11 · Wayland 交给合成器绑定 | ❌ 未实现 |
| 剪贴板发送 + 自动粘贴 | ✅ `SendInput` | ⚠️ X11 要 `xdotool` · Wayland 禁止模拟输入 | ⚠️ 未测试 |
| 托盘图标 | ✅ | ✅ 需要 StatusNotifier 宿主 | ⚠️ 未测试 |
| 开机自启动 | ✅ 注册表 | ✅ XDG autostart | ⚠️ 未测试 |
| 阻止第二次启动 | ✅ 互斥量 | ✅ 套接字 | ❌ 会再开一个 |
| 第二次启动转发 `--toggle` | ❌ | ✅ | ❌ |

发布出来的包只在 Windows 和 Arch + niri（Wayland）上跑过。Wayland 上有两个坑。合成器拥有全局
快捷键，程序没法自己注册，得把一个键绑到 `gifmanager --toggle`；`packaging/niri-binds.kdl` 里有
能用的例子，第二次启动的命令通道就是为这条路存在的，它也只出现在 Linux 上。另一个坑是桌面条目：
必须装成 `gifmanager.desktop`，XDG 门户靠这个名字找到应用，才肯发放 app id；
`scripts/install-desktop-entry.sh` 负责这件事。

macOS 后端是存在的，但一次都没跑过：CI 没有，人工也没有。所以第一次跑请当成测试，别当成日常
使用。Carbon 热键后端会直接说自己没实现，而不是假装能用。那边也没有单实例后端，第二次启动就是
再开一个。

## 安装

发布包由 `.github/workflows/build.yml` 手动构建，挂在 Release 页面上。

| 平台 | 文件 | 用法 |
|---|---|---|
| Windows | `GIFManager-Setup-<版本>.exe` | Inno Setup 安装器，默认按用户安装 |
| Windows | `GIFManager-<版本>-win64.zip` | 便携版：解压即用，数据留在可执行文件旁边 |
| Debian/Ubuntu | `gifmanager_<版本>_amd64.deb` | `sudo apt install ./gifmanager_*.deb` |
| 任意 Linux | `GIFManager-<版本>-linux-x86_64.AppImage` | `chmod +x` 后直接运行 |
| 任意 Linux | `GIFManager-<版本>-linux-x86_64.bin` | 自解压安装器，`--help` 看选项 |
| Arch | `gifmanager-<版本>-1-x86_64.pkg.tar.zst` | `sudo pacman -U` |
| Flatpak | `GIFManager-<版本>-x86_64.flatpak` | `flatpak install ./GIFManager-*.flatpak` —— *实验性，仅在主动要求时构建* |

从源码跑只需要虚拟环境、一个 requirements 文件和一个入口：

```bash
git clone https://github.com/LwoSnow/GIFManager.git
cd GIFManager

python -m venv .venv
# Windows：py -3.12 -m venv .venv   （用 3.12，别用 PATH 上的 python）
source .venv/bin/activate           # Windows：.venv\Scripts\activate

pip install -r requirements.txt
python -m gifmanager
```

要参与开发就换 `requirements-dev.txt`，它在运行依赖之上多一个 PyInstaller。`pip install -e .`
会装出 `gifmanager` 和 `gifmanager-qml` 两个命令；不装也能用 `python -m gifmanager` 或
`apps/gifmanager_qml.py`。

虚拟环境请用 3.12，虽然包本身只要 3.10：Pillow 的 wheel 是按 3.12 钉死的，从 PATH 上抓来的 3.14
会报一个 `_imaging` 导入错误，完全不提版本不对。PySide6 自己是 3.10+ 的 wheel，所以真正卡住 3.12
的是 Pillow。`make env` 会先把它查出来并给出修复命令。

`python -m gifmanager` 和 `gifmanager-qml` 都启动 QML 界面。不带后缀的 `gifmanager` 启动的是更早
的 Qt Widgets 外壳，留作对照，发布版跑的不是它。

播放是唯一可选的部件：`make native`（Windows 上是 `scripts/build-native.ps1`，其他系统是
`scripts/build-native.sh`）构建 Rust 解码器。没有它，程序照常打开、照常浏览，只是 GIF 卡片停在
首帧。

## 数据存放在哪

`emoji.db`、`emojis/<分组>/` 里的文件和 `settings.json` 放在同一个目录里。用哪个目录，看你
怎么启动程序：

| 怎么启动 | Windows | Linux | macOS |
|---|---|---|---|
| 从源码跑 | `%APPDATA%\GIFManager` | `~/.local/share/GIFManager` | `~/Library/Application Support/GIFManager` |
| 打包版 | 可执行文件旁的 `data\` | 可执行文件旁的 `data/` | 可执行文件旁的 `data/` |

打包版把素材库放在可执行文件旁边；那个位置只读时（AppImage 挂载点、装到系统目录的情况），
退回到上表那一行的按用户目录。Windows 安装器默认装到 `%LOCALAPPDATA%\Programs\GIFManager`，
所以它的素材库落在 `…\GIFManager\data`。日志不跟着动：Windows 是
`%LOCALAPPDATA%\GIFManager\logs`，Linux 是 `~/.cache/GIFManager/logs`，macOS 是
`~/Library/Logs/GIFManager`。

`GIFMANAGER_DATA_DIR` 覆盖素材库目录，日志不受影响，想并行跑两套配置或塞进 U 盘就靠它。素材库
放在按用户目录里，卸载不会动它；放在安装目录里，删掉那个文件夹时也就一起没了。

## 构建安装包

```bash
make build-qml      # 在 dist/GIFManager 生成 PyInstaller onedir 包
```

这是 QML 前端。`make build` 构建的是已退役的 Qt Widgets 包，它的 spec 排除了 Qt Quick，能跑，
但界面不是这份文档说的那个。

发布构建只能手动触发：每次推送都出一个安装包只是噪音，跑一轮还要大半个小时。版本号从
`gifmanager/__init__.py` 读，产物永远不会被标上一个代码并未携带的号码；每个平台只构建一次包，
再把它包成上表里的全部格式。勾上 `create_release` 就会带着这些产物发一个 draft release。

把这个工作目录推上去不等于发布：里面有虚拟环境、Rust 构建产物、PyInstaller 输出，还有几个测试
留下的杂项文件，加起来约 1.1 GB，没人需要。`make-archive.bat` 用 `git archive` 生成干净的 zip，
只导出被跟踪的文件，并跳过脚本里列出的六样不该上传的东西。上传 zip 的内容，不是这个文件夹的内容。

## 参与开发

```bash
make check      # 环境、分层、风格、翻译、批处理文件、单元测试
make smoke      # 离屏冒烟测试套件；需要先装好 Qt
make run-qml    # 从源码运行界面
```

虚拟环境没激活时要把解释器传进去：`make check PYTHON=.venv/Scripts/python.exe`，其他系统是
`.venv/bin/python`。

`make check` 不是装饰，每一项都拦下一种具体的错：

| 检查 | 它拒绝什么 |
|---|---|
| `tools/check_environment.py` | 一个连不起来的 Pillow；解释器不是 wheel 验证过的 3.12 时给警告 |
| `tools/check_layers.py` | `core` 导入 Qt，或前端逻辑向下泄漏 |
| `tools/check_style.py` | 超过 100 列的行、制表符、行尾空白、注释块里没有中文 |
| `tools/sync_language_keys.py` | 某张翻译表缺少另一张表已有的键 |
| `tools/check_batch_encoding.py` | 不是 ASCII + CRLF 的 `.bat` |
| `make test` | 坏掉的导入或丢了一行数据；125 个单元与集成测试，Qt 走离屏 |

CI 在打包任何东西之前跑分层、风格、翻译和单元测试，外加 `tests/smoke_qml.py`。
`make probe-services` 单独拎出来，因为它要真实桌面：离屏平台没有托盘，也没有热键可注册。

`make` 指的是 GNU Make，Windows 上要 MSYS2 或 Git Bash，因为配方用的是 POSIX shell 语法
（`QT_QPA_PLATFORM=offscreen python …`），`cmd.exe` 跑不了。每个目标都是 `Makefile` 里的一条命令；
`check` 和 `smoke` 只是把其他目标依次跑一遍。

`docs/` 里放着更长的说明：分层和 QML 前端怎么搭的（`ARCHITECTURE.md`、`QML_FRONTEND.md`）、
各平台怎么配和怎么排查（`RUNNING.md`）、还差什么（`COMPLETION_CHECKLIST.md`）。

界面提供英文与简体中文，在 *设置 → 通用 → 语言* 里切换，不用重启。翻译就是 `resources/language/`
下的普通 JSON 表；要加一种语言，把 `en_US.json` 复制成 `<区域>.json`，只翻译值，不改键，然后运行
`python tools/sync_language_keys.py`。文件名就是设置页提供的区域标识，新文件立刻就能选到。

注释、提交和 PR 的约定写在 `CONTRIBUTING.md`。

## 许可与致谢

**MIT**，见 [LICENSE](LICENSE)。可以随意使用、fork、发布。

HarmonyOS Sans SC 六个字重随包放在 `resources/fonts/`，按其字体自身的许可条款再分发；许可文本
没有随包，fork 里要重新分发这些字体，得自己补上一份。组件集参考
[SWB-QML-UI](https://github.com/xxmzwf/SWB-QML-UI)（MIT）与 shadcn 的观感，采用移植而不是链接的
方式，因为 PySide6 不自带 Qt 的 CMake 包。交互细节来自 Apple 的 *Designing Fluid Interfaces* 与
Emil Kowalski 关于界面打磨的写作：按下即反馈、可中断的运动、用对比度表达状态、字体的光学字距。
