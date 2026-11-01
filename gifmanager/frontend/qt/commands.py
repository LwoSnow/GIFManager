"""Command registry: every user action as data, not as a menu lambda.

The previous releases wired actions inline — a `menu.addAction(...)` here, a
`lambda` connected there, the same operation reimplemented in a context menu, a
toolbar button and a keyboard handler. That made an action impossible to find,
impossible to rebind, and easy to implement three times with three different
behaviours.

Here an action is declared once as a `Command` and then *presented* wherever it
is wanted: the menu bar, a toolbar, a context menu, a keyboard shortcut or a
command palette all read the same registry. Adding an action to a new place
becomes a one-line call, and "what can this application do" has an actual answer.

命令注册表：把每个用户操作变成数据，而不是菜单里的 lambda。

此前版本内联接线——这里一个 `menu.addAction(...)`，那里一个 `lambda`，同一个操作在
右键菜单、工具栏按钮与键盘处理里各实现一遍。这让一个操作无法被找到、无法被重新绑定，
也很容易以三种不同行为实现三次。

在这里，操作只声明一次为 `Command`，然后在需要的地方被"呈现"：菜单栏、工具栏、右键
菜单、键盘快捷键或命令面板读取的都是同一份注册表。把某个操作加到新位置变成一行调用，
而"这个程序能做什么"终于有了确切答案。
"""
import dataclasses
import logging
from typing import Callable, Optional, Sequence, Tuple

log = logging.getLogger("GIFManager")

# Command identifiers. Plain strings, deliberately: they appear in translation
# keys, in settings and in diagnostics, so being human-readable is worth more
# than being an enum.
# 命令标识。刻意用普通字符串：它们会出现在翻译键、设置与诊断信息里，因此可读性比做成
# 枚举更有价值。
CMD_IMPORT = "library.import"
CMD_ADD_TEXT = "library.add_text"
CMD_SEARCH_FOCUS = "library.search_focus"
CMD_REFRESH = "library.refresh"
CMD_DELETE_SELECTED = "edit.delete"
CMD_COPY = "edit.copy"
CMD_RENAME = "edit.rename"
CMD_EDIT_TEXT = "edit.edit_text"
CMD_MOVE_TO_GROUP = "edit.move"
CMD_SELECT_ALL = "edit.select_all"
CMD_TOGGLE_EDIT_MODE = "edit.toggle_mode"
CMD_CARD_SCALE_UP = "view.scale_up"
CMD_CARD_SCALE_DOWN = "view.scale_down"
CMD_CARD_SCALE_RESET = "view.scale_reset"
CMD_TOGGLE_NAME = "view.toggle_name"
CMD_TOGGLE_THEME = "view.toggle_theme"
CMD_NAV_LIBRARY = "nav.library"
CMD_NAV_SETTINGS = "nav.settings"
CMD_NAV_ABOUT = "nav.about"
CMD_SETTINGS = "app.settings"
CMD_QUIT = "app.quit"
CMD_CLEAR_LOGS = "app.clear_logs"
CMD_CONVERT_LIBRARY = "app.convert_library"
CMD_SHOW_SHORTCUTS = "help.shortcuts"

# Where a command may appear. A command declares which surfaces it suits, so a
# presenter can filter without every call site deciding for itself.
# 命令可以出现的位置。命令声明它适合哪些界面，使呈现方无需每个调用点自行判断即可过滤。
SURFACE_MENU = "menu"
SURFACE_TOOLBAR = "toolbar"
SURFACE_CONTEXT = "context"
SURFACE_PALETTE = "palette"


@dataclasses.dataclass(frozen=True)
class Command:
    # One user action.
    #
    # `label_key` and `hint_key` are translation keys, not text: the registry is
    # built before a language is chosen, and a translated string captured here
    # would freeze whichever language happened to be active at import time.
    # 一个用户操作。
    #
    # `label_key` 与 `hint_key` 是翻译键而非文本：注册表在选定语言之前就构建，在此
    # 捕获已翻译字符串会把导入时恰好生效的语言固定下来。
    id: str
    label_key: str
    callback: Callable
    hint_key: str = ""
    icon: str = ""
    shortcut: str = ""
    surfaces: Tuple[str, ...] = (SURFACE_MENU, SURFACE_PALETTE)
    # True when the action changes the library, so the shell can skip a
    # `library_changed` round trip for a pure view change.
    # 操作会改动库时为 True，使外壳对纯视图变化跳过一轮 `library_changed`。
    mutates: bool = False
    # Optional predicate taking the view state and returning whether the action
    # is currently possible. Without one a command is always enabled.
    # 可选谓词，接收视图状态并返回该操作当前是否可行。缺省时命令始终可用。
    enabled_when: Optional[Callable] = None

    def is_enabled(self, state):
        if self.enabled_when is None:
            return True
        try:
            return bool(self.enabled_when(state))
        except Exception:
            # A broken predicate must not take the interface down; an action that
            # cannot be evaluated is safer disabled than crashing the menu.
            # 谓词出错不得拖垮界面；无法求值的操作"禁用"比让菜单崩溃更安全。
            log.exception("command %s: enabled_when failed", self.id)
            return False


class CommandRegistry:
    # The set of commands an application exposes.
    #
    # Registration is by id and is idempotent-by-replacement, so a plugin or a
    # test can override one action without rebuilding the registry.
    # 应用暴露的命令集合。
    #
    # 按 id 注册，重复注册即替换，因此插件或测试可以覆盖单个操作而无需重建注册表。
    def __init__(self):
        self._commands = {}
        self._order = []

    def register(self, command):
        if command.id in self._commands:
            # Keep the original position so a replacement does not jump to the
            # end of every menu.
            # 保留原位置，使替换不会跳到每个菜单的末尾。
            self._commands[command.id] = command
        else:
            self._commands[command.id] = command
            self._order.append(command.id)
        return command

    def register_all(self, commands):
        for command in commands:
            self.register(command)
        return self

    def get(self, command_id):
        return self._commands.get(command_id)

    def __contains__(self, command_id):
        return command_id in self._commands

    def __len__(self):
        return len(self._commands)

    def ids(self):
        return tuple(self._order)

    def all(self):
        return tuple(self._commands[cid] for cid in self._order)

    def for_surface(self, surface):
        # Commands declaring this surface, in registration order /
        # 声明了该界面的命令，按注册顺序
        return tuple(c for c in self.all() if surface in c.surfaces)

    def invoke(self, command_id, state=None):
        # Run a command, honouring its availability predicate.
        #
        # Returns True when it ran. A missing command or a disabled one returns
        # False rather than raising: a menu item and the shortcut that mirrors it
        # must fail the same quiet way when the action is not applicable.
        # 运行命令，遵守其可用性谓词。
        #
        # 运行时返回 True。命令不存在或被禁用时返回 False 而不抛异常：当一个操作不
        # 适用时，菜单项与镜像它的快捷键必须以同样安静的方式失败。
        command = self._commands.get(command_id)
        if command is None:
            log.warning("command %s is not registered", command_id)
            return False
        if state is not None and not command.is_enabled(state):
            return False
        try:
            command.callback()
        except Exception:
            log.exception("command %s failed", command_id)
            return False
        return True

    def search(self, text):
        # Substring match over ids and translation keys, for a command palette.
        #
        # Keys rather than translated labels because the palette is built before
        # a language is bound; the presenter translates the results it displays.
        # 对 id 与翻译键做子串匹配，供命令面板使用。
        #
        # 用键而非已翻译标签，因为面板在语言绑定之前构建；呈现方翻译它显示的结果。
        needle = (text or "").strip().lower()
        if not needle:
            return self.for_surface(SURFACE_PALETTE)
        return tuple(
            c for c in self.for_surface(SURFACE_PALETTE)
            if needle in c.id.lower() or needle in c.label_key.lower())


def define(command_id, label_key, callback, **kwargs):
    # Terse constructor used by the shell when wiring its own actions /
    # 外壳接线自身操作时使用的简洁构造器
    return Command(id=command_id, label_key=label_key, callback=callback, **kwargs)


def labels_for(registry, translate, surface=None):
    # (command, label) pairs for presentation. Kept separate from the registry so
    # the registry itself never imports the language layer.
    # 供呈现使用的 (命令, 标签) 对。与注册表分开，使注册表本身不导入语言层。
    commands = registry.for_surface(surface) if surface else registry.all()
    return tuple((c, translate(c.label_key)) for c in commands)


__all__ = [
    "CMD_ADD_TEXT",
    "CMD_CARD_SCALE_DOWN",
    "CMD_CARD_SCALE_RESET",
    "CMD_CARD_SCALE_UP",
    "CMD_CLEAR_LOGS",
    "CMD_CONVERT_LIBRARY",
    "CMD_COPY",
    "CMD_DELETE_SELECTED",
    "CMD_EDIT_TEXT",
    "CMD_IMPORT",
    "CMD_MOVE_TO_GROUP",
    "CMD_NAV_ABOUT",
    "CMD_NAV_LIBRARY",
    "CMD_NAV_SETTINGS",
    "CMD_REFRESH",
    "CMD_RENAME",
    "CMD_SEARCH_FOCUS",
    "CMD_SELECT_ALL",
    "CMD_SETTINGS",
    "CMD_SHOW_SHORTCUTS",
    "CMD_TOGGLE_EDIT_MODE",
    "CMD_TOGGLE_NAME",
    "CMD_TOGGLE_THEME",
    "Command",
    "CommandRegistry",
    "SURFACE_CONTEXT",
    "SURFACE_MENU",
    "SURFACE_PALETTE",
    "SURFACE_TOOLBAR",
    "define",
    "labels_for",
]
