"""GIFManager Next — modular, cross-platform emoji / sticker manager.

Layering (each layer may only import from the layers above it):

    core     pure Python domain logic; no Qt, no OS-specific calls
    platform OS abstraction + per-system implementations (windows/macos/linux)
    backend  application services, data store, and the front-end contract
    frontend user-interface shells; today only the Qt shell exists
    apps     thin, per-platform launchers

GIFManager Next —— 模块化、跨平台的表情包管理器。

分层（每层只允许导入它上面的层）：

    core     纯 Python 领域逻辑；不含 Qt、不含系统专有调用
    platform 系统抽象 + 各系统实现（windows/macos/linux）
    backend  应用服务、数据存储，以及前后端契约
    frontend 界面外壳；目前只有 Qt 外壳
    apps     各平台的极薄启动器
"""

# Single source of truth for the application version / 应用版本的唯一来源
#
# 2.0.0, which REVERSES the earlier decision to stay on 1.1.0.
#
# The reasoning for 1.1.0 was "this is a new line, not a successor to the original GIFManager's
# numbering, and reusing a number the original may reach makes the updater compare against the wrong
# thing". That concern is real but it was answered the wrong way: the shipped interface is no longer
# the 1.x one. The whole visual system was replaced (low-contrast palette, the `ui/*` component set,
# every secondary window rebuilt), the Linux front-end was made to actually run, and settings that
# were dead on every platform were fixed. A user comparing 1.1.0 with this build cannot tell them
# apart by number, and a version that does not move across changes of that size is worse than a
# number that collides - the collision is visible in an update manifest, a stale number is
# invisible.
#
# The number here is the one the update manifest and the packaged installer both carry.
# 2.0.0，它"推翻"了此前停留在 1.1.0 的决定。
#
# 选 1.1.0 的理由是"这是一条新产品线，不是原 GIFManager 编号的延续，而复用一个原项目可能达到的
# 版本号会让更新器与错误的对象比较"。那个顾虑是真实的，但处理方式错了：现在发布的界面已不是 1.x 的
# 那个。整套视觉系统被替换（低对比调色板、`ui/*` 组件集、每个二级窗口重建）、Linux 前端被做到真正
# 能跑、多个在所有平台上都失效的设置被修好。用户拿 1.1.0 与本次构建相比无法凭版本号区分，而一个在
# 如此规模的变更后仍不移动的版本号，比一个会碰撞的版本号更糟——碰撞在更新清单里看得见，过期的号码看不见。
#
# 此处的数字就是更新清单与打包安装器共同携带的那个。
__version__ = "2.0.0"

# Application identity, used for settings, logs and platform services /
# 应用标识，用于配置、日志与系统服务
APP_NAME = "GIFManager"

# The reverse-DNS-free application id that desktop integration keys off.
#
# # One id, three consumers
#
# On Wayland this single string decides three things that all failed independently until it
# existed:
#
#   * the compositor's `app_id` for the window, which is the ONLY handle a tiling compositor such
#     as niri can match a `window-rule` against - without it a frameless utility window is tiled
#     and cannot be made to float;
#   * the file name of the `.desktop` entry (`gifmanager.desktop`), which the XDG portal looks up
#     to obtain "app info";
#   * the id the portal must have before it will grant a `GlobalShortcuts` session. Measured on
#     Arch + niri: `CreateSession` answers
#         org.freedesktop.portal.Error.NotAllowed: An app id is required
#     and `Registry.Register` answers
#         Could not register app ID: App info not found for 'gifmanager'
#     until a matching `.desktop` file exists.
#
# It is deliberately lowercase and free of dots so it is a valid Wayland app id and a valid
# `.desktop` base name on every desktop.
#
# 桌面集成所依赖的应用 id（不含反向域名）。
#
# # 一个 id，三个消费者
#
# 在 Wayland 上，这一个字符串决定三件事，而在它存在之前这三件事各自独立地失败：
#
#   * 合成器看到的窗口 `app_id`，这是平铺合成器（如 niri）匹配 `window-rule` 的"唯一"把手——
#     没有它，一个无边框工具窗口会被平铺，且无法让它悬浮；
#   * `.desktop` 条目的文件名（`gifmanager.desktop`），XDG 门户靠查它来获得"应用信息"；
#   * 门户授予 `GlobalShortcuts` 会话之前必须持有的 id。在 Arch + niri 上实测：`CreateSession`
#     回答
#         org.freedesktop.portal.Error.NotAllowed: An app id is required
#     而 `Registry.Register` 回答
#         Could not register app ID: App info not found for 'gifmanager'
#     直到存在匹配的 `.desktop` 文件。
#
# 它刻意全小写且不含点，使其在每个桌面上都是合法的 Wayland app id 与合法的 `.desktop` 基名。
APP_ID = "gifmanager"

__all__ = ["APP_ID", "APP_NAME", "__version__"]
