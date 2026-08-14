"""Build gifdec.dll from gifdec.c with a MinGW gcc.

Usage / 用法:
    python build_gifdec.py                 # auto-detect gcc / 自动查找 gcc
    python build_gifdec.py C:\\path\\to\\gcc.exe

The DLL must be pure C (no libstdc++): the bundled MinGW g++ 4.9.2 builds
DLLs whose C++ runtime fails to initialize in modern processes.
DLL 必须为纯 C（不使用 libstdc++）：内置 MinGW g++ 4.9.2 构建的 DLL 其
C++ 运行时在现代进程中初始化失败。"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "gifdec.c")
OUT = os.path.join(HERE, "gifdec.dll")


def find_gcc():
    # Command-line argument first, then common install paths, then PATH
    # 优先命令行参数，其次常见安装路径，最后 PATH
    if len(sys.argv) > 1:
        return sys.argv[1]
    candidates = [
        r"C:\Program Files (x86)\Dev-Cpp\MinGW64\bin\gcc.exe",
        r"C:\TDM-GCC-64\bin\gcc.exe",
        r"C:\MinGW\bin\gcc.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    found = shutil.which("gcc")
    return found


def main():
    gcc = find_gcc()
    if not gcc:
        print("gcc not found; pass the compiler path as the first argument")
        return 1
    cmd = [gcc, "-O2", "-shared", "-o", OUT, SRC, "-s"]
    print("running:", " ".join(cmd))
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print("build failed")
        return proc.returncode
    print("built:", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
