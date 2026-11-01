"""Launcher for the QML interface.

A separate entry point from `gifmanager_qt.py` on purpose. The two front-ends are
complete, independent implementations of the same backend contract, and keeping
one launcher each is what lets them be compared — against the same data directory,
on the same machine, without editing a file between runs. A single launcher with a
mode flag would make a comparison test's result depend on an environment variable.

It keeps the layers straight the same way: it enables development imports when run
from a checkout, then hands control to the QML shell.

QML 界面的启动器。

刻意与 `gifmanager_qt.py` 分开作为入口。两个前端是同一后端契约的两套完整、独立的实现，
各留一个启动器才能让它们被对比——同一数据目录、同一台机器、运行之间无需改文件。用带模式
开关的单一启动器会让对比测试的结果取决于一个环境变量。

它同样保持各层职责清晰：从源码目录运行时启用开发导入，随后把控制权交给 QML 外壳。
"""
import os
import sys


def _enable_checkout_imports():
    # When run as `python apps/gifmanager_qml.py` from a checkout, the package
    # directory is the script's parent's parent. Installing it on `sys.path` here
    # is what makes a source run work without an editable install.
    # 在源码目录以 `python apps/gifmanager_qml.py` 运行时，包目录是脚本父目录的父目录。
    # 在此把它加入 `sys.path`，使源码运行无需可编辑安装即可工作。
    if __package__:
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main(argv=None):
    _enable_checkout_imports()
    from gifmanager.frontend.qml.app import run

    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
