#!/usr/bin/env sh
# Build the native Rust image pipeline on macOS or Linux.
#
# Usage / 用法:
#     sh scripts/build-native.sh              # release build
#     sh scripts/build-native.sh --debug      # debug build
#     sh scripts/build-native.sh --install    # also copy into resources/
#
# WHY IT IS OPTIONAL / 为什么它是可选的
#
# `gifmanager.frontend.qt.images` loads this library through `ctypes` and returns
# None when it is absent, so the application runs without it: GIF playback falls
# back to the bundled C decoder (or `QMovie`), and thumbnails fall back to
# `QImage`. Nothing fails.
#
# `gifmanager.frontend.qt.images` 经 `ctypes` 加载本库，缺失时返回 None，因此没有
# 它程序也能运行：GIF 播放回退到随包的 C 解码器（或 `QMovie`），缩略图回退到
# `QImage`。什么都不会坏。
#
# This script exists because the Rust source is the ONLY part of the project that
# can give macOS and Linux a native GIF decoder: the bundled `gifdec.dll` is a
# Windows binary, and its C source would otherwise need a separate build and a
# separately shipped `.dylib`/`.so` per platform.
#
# 本脚本存在的原因是：Rust 源码是项目中"唯一"能让 macOS 与 Linux 获得原生 GIF
# 解码器的部分——随包的 `gifdec.dll` 是 Windows 二进制，而其 C 源码否则需要为每个平台
# 单独构建并单独发布 `.dylib`/`.so`。

set -eu

PROFILE="release"
INSTALL="no"
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --debug)   PROFILE="debug" ;;
        --install) INSTALL="yes" ;;
        --target=*) TARGET="${arg#--target=}" ;;
        -h|--help)
            sed -n '2,12p' "$0"
            exit 0
            ;;
        *)
            echo "unknown option / 未知选项: $arg" >&2
            exit 2
            ;;
    esac
done

# Repository root is this script's parent's parent /
# 仓库根是本脚本父目录的父目录
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(dirname -- "$SCRIPT_DIR")
CRATE="$ROOT/native"
RESOURCES="$ROOT/resources"

if ! command -v cargo >/dev/null 2>&1; then
    cat >&2 <<'EOF'
cargo was not found on PATH.
未在 PATH 上找到 cargo。

Install Rust from https://rustup.rs and reopen the terminal. The application runs
without this library; building it only enables the faster image path.
请从 https://rustup.rs 安装 Rust 并重新打开终端。没有本库程序照样运行；构建它只是
启用更快的图像路径。
EOF
    exit 1
fi

echo "native pipeline build / 原生管线构建"
echo "  crate   : $CRATE"
echo "  profile : $PROFILE"
cargo --version

cd "$CRATE"

if [ -n "$TARGET" ]; then
    echo "  target  : $TARGET"
    if [ "$PROFILE" = "release" ]; then
        cargo build --release --target "$TARGET"
    else
        cargo build --target "$TARGET"
    fi
    OUTPUT_DIR="$CRATE/target/$TARGET/$PROFILE"
else
    if [ "$PROFILE" = "release" ]; then
        cargo build --release
    else
        cargo build
    fi
    OUTPUT_DIR="$CRATE/target/$PROFILE"
fi

# Cargo's `cdylib` naming differs per platform / Cargo 的 `cdylib` 命名随平台不同
ARTIFACT=""
for name in libgifmanager_native.dylib libgifmanager_native.so \
            gifmanager_native.dll; do
    if [ -f "$OUTPUT_DIR/$name" ]; then
        ARTIFACT="$OUTPUT_DIR/$name"
        break
    fi
done

if [ -z "$ARTIFACT" ]; then
    echo "no library found in $OUTPUT_DIR / 在该目录未找到库文件" >&2
    exit 1
fi

SIZE=$(du -h "$ARTIFACT" | cut -f1)
echo ""
echo "built / 已构建: $ARTIFACT ($SIZE)"

if [ "$INSTALL" = "yes" ]; then
    mkdir -p "$RESOURCES"
    cp -f "$ARTIFACT" "$RESOURCES/"
    echo "installed / 已安装到: $RESOURCES/$(basename "$ARTIFACT")"
else
    echo ""
    echo "The development build is picked up automatically from"
    echo "native/target/$PROFILE/ — no copy step needed."
    echo "开发构建会被 native/target/$PROFILE/ 自动发现——无需复制步骤。"
fi

echo ""
echo "verify / 验证:"
echo "  python -c \"from gifmanager.frontend.qt import images; print(images.describe())\""
echo "  python tests/smoke_native.py"
echo "  python tests/bench_native.py"
