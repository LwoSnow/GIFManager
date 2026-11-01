"""The one-command launcher.

A single entry point that keeps the layers straight: it enables development
imports when run from a checkout, then hands control to the Qt shell. Nothing
else in the project needs to know how it is started.

同一条启动命令。

单一入口，保持各层职责清晰：从源码目录运行时启用开发导入，随后把控制权交给 Qt 外壳。
项目其他部分无需知道它是如何被启动的。
"""
import os
import sys


def _enable_checkout_imports():
    # When run as `python apps/gifmanager_qt.py` from a checkout, the package
    # directory is the script's parent's parent. Installing it on `sys.path`
    # here is what makes a source run work without an editable install.
    # 在源码目录以 `python apps/gifmanager_qt.py` 运行时，包目录是脚本父目录的父
    # 目录。在此把它加入 `sys.path`，使源码运行无需可编辑安装即可工作。
    if __package__:
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main(argv=None):
    _enable_checkout_imports()
    from gifmanager.frontend.qt.shell import run

    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
