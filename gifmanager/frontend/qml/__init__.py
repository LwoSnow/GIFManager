"""QML front-end: declarative interface bound to the toolkit-free backend.

# Why QML rather than Qt Widgets

The backend already exposes what a declarative interface needs: typed settings, a
row list, and change notifications. Qt Widgets required rebuilding that on every
change by hand — the previous release pushed a grid refresh from twenty separate
call sites because nothing could observe the data. QML binds to it instead, so a
setting or a library change reaches the interface without anyone calling a refresh
method.

# What QML costs

QSS does NOT apply to Qt Quick Controls: style sheets are a Qt Widgets mechanism.
The two `frontend/qt/theme/*` style sheets therefore cannot be reused, and the
palette lives in `Theme.qml` (a singleton) driven by `ThemeBridge`. That is a real
rewrite of the theming, not a port, and it is the main reason the QML front-end is
a new subtree rather than a modification of the existing one.

# Layout

    qml/
      app.py            process bootstrap: engine, context, window
      bridge.py         BackendBridge — the one object QML sees
      models.py         list models for groups and stickers
      settings_model.py schema-driven settings model
      theme.py          palette bridge backing Theme.qml
      theme/Theme.qml   colours, metrics, typography
      shell/            navigation shell, menu, status bar
      views/            settings, library
      components/       sticker card, hover preview, dialogs

QML 前端：绑定到无工具包后端的声明式界面。

# 为什么用 QML 而非 Qt Widgets

后端已经暴露了声明式界面所需的一切：带类型的设置、行列表，以及变更通知。Qt Widgets
要求每次变更都手工重建这些——上一版本从二十个调用点分别推送网格刷新，因为没有任何东西
能观察数据。QML 改为绑定，因此设置或库的变更无需任何人调用刷新方法就能到达界面。

# QML 的代价

QSS 对 Qt Quick Controls "不生效"：样式表是 Qt Widgets 的机制。因此
`frontend/qt/theme/*` 的两份样式表无法复用，调色板改由 `Theme.qml`（单例）承载、由
`ThemeBridge` 驱动。这是对主题的"重写"而非移植，也正是 QML 前端是一个新子树、而不是对
既有前端的修改的主要原因。

# 目录

    qml/
      app.py            进程引导：引擎、上下文、窗口
      bridge.py         BackendBridge——QML 看到的唯一对象
      models.py         分组与贴纸的列表模型
      settings_model.py schema 驱动的设置模型
      theme.py          支撑 Theme.qml 的调色板桥
      theme/Theme.qml   颜色、尺寸、字体
      shell/            导航外壳、菜单、状态栏
      views/            设置、表情库
      components/       贴纸卡片、悬停预览、对话框
"""

__all__ = []
