"""Check the environment before blaming the code.

# The failure this prevents

`PIL._imaging` is a compiled extension named for one Python version
(`_imaging.cp312-win_amd64.pyd`). Installing Pillow under 3.12 and then running an
interpreter that reports 3.14 produces:

    ImportError: cannot import name '_imaging' from 'PIL'

which names a file that is present and says nothing about the version mismatch. The same
shape of failure hits PySide6 and shiboken6. On this machine `python` on PATH is 3.14
while `py -3.12` is the interpreter the wheels are built for, so recreating `.venv` with
the wrong one silently breaks every check that touches an image — which is most of them.

This runs FIRST and reports the mismatch in one line, with the command that fixes it.

# 本脚本防止的失败

`PIL._imaging` 是为某个 Python 版本命名的编译扩展（`_imaging.cp312-win_amd64.pyd`）。在
3.12 下装好 Pillow，再用一个自称 3.14 的解释器运行，会得到：

    ImportError: cannot import name '_imaging' from 'PIL'

它点名了一个"存在"的文件，却对版本不匹配只字不提。PySide6 与 shiboken6 会遇到同一形态的失败。
本机上 PATH 里的 `python` 是 3.14，而 `py -3.12` 才是这些 wheel 对应的解释器，因此用错的那个
重建 `.venv` 会静默地弄坏每一个涉及图像的检查——而那几乎是全部。

本脚本"最先"运行，用一行报告不匹配，并给出修复命令。
"""
import os
import sys

# The interpreter the pinned wheels are built for. The project runs on 3.10+, but this is
# the version the lock file's wheels were verified against, so a mismatch is worth naming.
# 锁定的 wheel 所对应的解释器。项目可在 3.10+ 运行，但这是锁定文件的 wheel 经验证的版本，
# 因此不匹配值得点名。
EXPECTED_SERIES = (3, 12)

# The command that fixes a mismatch on Windows. Written out because "recreate the venv"
# is not actionable on its own — and `python -m venv` is exactly what goes wrong here.
# Windows 上修复不匹配的命令。写出来是因为"重建 venv"本身不可操作——而 `python -m venv`
# 正是这里出错的原因。
FIX_WINDOWS = (r"py -3.12 -m venv .venv"
               r" && .venv\Scripts\python.exe -m pip install -r requirements.txt")
FIX_POSIX = ("python3 -m venv .venv"
             " && .venv/bin/pip install -r requirements.txt")


def main():
    version = sys.version_info
    series = (version.major, version.minor)
    problems = []
    notes = []

    print(f"interpreter : {sys.executable}")
    print(f"version     : {version.major}.{version.minor}.{version.micro}")
    print(f"prefix      : {sys.prefix}")
    print(f"in a venv   : {sys.prefix != sys.base_prefix}")

    if series != EXPECTED_SERIES:
        notes.append(
            f"this is Python {series[0]}.{series[1]} but the pinned wheels are built for "
            f"{EXPECTED_SERIES[0]}.{EXPECTED_SERIES[1]}")

    # Import the two compiled dependencies and report WHICH one fails, because the
    # traceback names a submodule rather than the dependency.
    # 导入两个编译型依赖并报告"哪一个"失败，因为回溯点名的是子模块而不是该依赖。
    for module, label in (("PySide6.QtCore", "PySide6"),
                          ("PySide6.QtGui", "PySide6 QtGui"),
                          ("PySide6.QtQml", "PySide6 QtQml"),
                          ("PIL.Image", "Pillow (needs _imaging)")):
        try:
            __import__(module)
            print(f"{label:24} -> OK")
        except Exception as exc:
            print(f"{label:24} -> FAILED: {type(exc).__name__}: {exc}")
            problems.append(f"{label} cannot be imported ({exc})")

    # A concrete encode, because importing Pillow can succeed while its codecs are broken.
    # 一次真实编码，因为导入 Pillow 可能成功而它的编解码器是坏的。
    try:
        import tempfile

        from PIL import Image

        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            Image.new("RGB", (16, 16), (10, 20, 30)).save(path)
            with Image.open(path) as reopened:
                reopened.load()
                size = reopened.size
            print(f"{'Pillow round trip':24} -> {size}")
            if size != (16, 16):
                problems.append(f"the Pillow round trip changed the size to {size}")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    except Exception as exc:
        print(f"{'Pillow round trip':24} -> FAILED: {type(exc).__name__}: {exc}")
        problems.append(f"the Pillow round trip failed ({exc})")

    print()
    if problems:
        print("ENVIRONMENT CHECK FAILED / 环境检查未通过")
        for problem in problems:
            print("  " + problem)
        for note in notes:
            print("  " + note)
        print()
        print("  The compiled wheels do not match this interpreter. Rebuild the venv with")
        print("  the interpreter they were built for - NOT whichever `python` is on PATH:")
        print("  编译好的 wheel 与本解释器不匹配。请用它们对应的解释器重建 venv，")
        print("  而不要用 PATH 上的那个 `python`：")
        print()
        print(f"    Windows : {FIX_WINDOWS}")
        print(f"    POSIX   : {FIX_POSIX}")
        return 1

    if notes:
        # Not fatal: a different minor version can work if the wheels match it.
        # 不致命：只要 wheel 与之匹配，不同的小版本也可以工作。
        print("ENVIRONMENT CHECK OK (with a note) / 环境检查通过（附提示）")
        for note in notes:
            print("  " + note)
        return 0

    print("ENVIRONMENT CHECK OK / 环境检查通过")
    print("  interpreter, PySide6, Qt QML and Pillow all work")
    print("  解释器、PySide6、Qt QML 与 Pillow 均可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
