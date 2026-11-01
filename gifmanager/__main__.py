"""Run the QML interface as `python -m gifmanager`.

# Why this module has to exist

Two things needed it and both were broken without it:

  * `packaging/gifmanager.desktop` launches `python -m gifmanager`, which failed with
        No module named gifmanager.__main__; 'gifmanager' is a package and cannot be
    directly executed
  * `pyproject.toml` declares `gifmanager = "gifmanager.frontend.qt.shell:main"`, i.e. the Qt
    WIDGETS shell. The QML interface — the rebuilt front-end, and the one this repository is
    about — had no installed entry point at all, only `apps/gifmanager_qml.py` run by path.

So the QML front-end is now reachable three ways that agree: `python -m gifmanager`, the
`gifmanager-qml` console script, and `apps/gifmanager_qml.py`.

# 以 `python -m gifmanager` 运行 QML 界面。

# 为什么本模块必须存在

有两处需要它，而缺少它时两者都是坏的：

  * `packaging/gifmanager.desktop` 以 `python -m gifmanager` 启动，而它失败于
        No module named gifmanager.__main__; 'gifmanager' is a package and cannot be
    directly executed
  * `pyproject.toml` 声明的 `gifmanager = "gifmanager.frontend.qt.shell:main"` 是 Qt "Widgets"
    外壳。而 QML 界面——重建后的前端、也是本仓库的主题——根本没有任何已安装的入口点，只有按路径
    运行的 `apps/gifmanager_qml.py`。

因此 QML 前端现在有三种彼此一致的到达方式：`python -m gifmanager`、`gifmanager-qml` 控制台
脚本，以及 `apps/gifmanager_qml.py`。
"""
import sys


def main(argv=None):
    # Delegate to the QML shell's own bootstrap, so the ORDER of startup lives in one place.
    # 委托给 QML 外壳自身的引导过程，使启动"顺序"只存在于一处。
    from gifmanager.frontend.qml.app import run

    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
