# Build the native Rust image pipeline.
#
# Usage / 用法:
#     powershell -File scripts/build-native.ps1
#     powershell -File scripts/build-native.ps1 -DebugBuild
#     powershell -File scripts/build-native.ps1 -Install   # also copy into resources/
#
# `powershell` rather than `pwsh`: this script runs on the Windows PowerShell 5.1
# that ships with Windows, which is what this machine has. It uses no PowerShell 7
# features, so it also runs under `pwsh` on a machine that has it.
#
# 用 `powershell` 而非 `pwsh`：本脚本运行在 Windows 自带的 Windows PowerShell 5.1
# 上，也就是本机现有的版本。它不使用任何 PowerShell 7 特性，因此在装有 `pwsh` 的
# 机器上同样可以运行。
#
# WHY IT IS OPTIONAL / 为什么它是可选的
#
# `gifmanager.frontend.qt.images` loads this library through `ctypes` and returns
# None when it is absent, so the application runs without it: GIF playback falls
# back to the bundled C decoder (or `QMovie`), and thumbnails fall back to
# `QImage`. Nothing fails, and `python -c "from gifmanager.frontend.qt import
# images; print(images.describe())"` always reports which path is live.
#
# `gifmanager.frontend.qt.images` 经 `ctypes` 加载本库，缺失时返回 None，因此没有
# 它程序也能运行：GIF 播放回退到随包的 C 解码器（或 `QMovie`），缩略图回退到
# `QImage`。什么都不会坏，而
# `python -c "from gifmanager.frontend.qt import images; print(images.describe())"`
# 始终报告当前生效的是哪条路径。

[CmdletBinding()]
param(
    # Build the debug profile instead of release / 构建 debug 而非 release
    [switch]$DebugBuild,

    # Copy the artifact into resources/ so a packaged build carries it /
    # 把产物复制到 resources/，使打包版本携带它
    [switch]$Install,

    # Build for a different target triple / 为其他目标三元组构建
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

# The repository root is this script's parent's parent /
# 仓库根是本脚本父目录的父目录
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$crate = Join-Path $root "native"
$resources = Join-Path $root "resources"
$profile = if ($DebugBuild) { "debug" } else { "release" }

Write-Host "native pipeline build / 原生管线构建"
Write-Host "  crate   : $crate"
Write-Host "  profile : $profile"
if ($Target) { Write-Host "  target  : $Target" }

# Verify the toolchain before invoking cargo, so a missing Rust install produces a
# clear instruction instead of a shell error.
#
# The message is a plain array of lines rather than a here-string: Windows
# PowerShell 5.1 requires a here-string's terminator to sit at the very start of a
# line, which is fragile inside an indented block.
# 调用 cargo 前先确认工具链，使缺少 Rust 时给出明确指引而不是 shell 报错。
#
# 提示信息用普通字符串数组而非 here-string：Windows PowerShell 5.1 要求 here-string
# 的结束符位于行首，这在缩进块内很脆弱。
$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $cargo) {
    $lines = @(
        "cargo was not found on PATH.",
        "未在 PATH 上找到 cargo。",
        "",
        "Install Rust from https://rustup.rs and reopen the terminal.",
        "The application runs without this library; building it only enables the",
        "faster image path.",
        "请从 https://rustup.rs 安装 Rust 并重新打开终端。",
        "没有本库程序照样运行；构建它只是启用更快的图像路径。"
    )
    Write-Host ($lines -join [Environment]::NewLine) -ForegroundColor Red
    exit 1
}

Write-Host "  cargo   : $($cargo.Source)"
& cargo --version

Push-Location $crate
try {
    $arguments = @("build")
    if (-not $DebugBuild) { $arguments += "--release" }
    if ($Target) { $arguments += @("--target", $Target) }

    Write-Host ""
    Write-Host "running: cargo $($arguments -join ' ')"
    & cargo @arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Error "cargo build failed with exit code $LASTEXITCODE / cargo 构建失败"
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

# Locate the artifact. Cargo's `cdylib` naming differs per platform, and a
# `--target` build nests it one directory deeper.
# 定位产物。Cargo 的 `cdylib` 命名随平台不同，而 `--target` 构建会多嵌套一层目录。
$outputDir = if ($Target) {
    Join-Path $crate "target/$Target/$profile"
} else {
    Join-Path $crate "target/$profile"
}

$names = @("gifmanager_native.dll", "libgifmanager_native.dylib",
           "libgifmanager_native.so")
$artifact = $null
foreach ($name in $names) {
    $candidate = Join-Path $outputDir $name
    if (Test-Path $candidate) { $artifact = $candidate; break }
}

if (-not $artifact) {
    Write-Error "no library found in $outputDir / 在该目录未找到库文件"
    exit 1
}

$size = [math]::Round((Get-Item $artifact).Length / 1MB, 2)
Write-Host ""
Write-Host "built / 已构建: $artifact ($size MB)"

if ($Install) {
    if (-not (Test-Path $resources)) {
        New-Item -ItemType Directory -Path $resources -Force | Out-Null
    }
    $destination = Join-Path $resources (Split-Path -Leaf $artifact)
    Copy-Item $artifact $destination -Force
    Write-Host "installed / 已安装到: $destination"
    Write-Host ""
    Write-Host "A packaged build now carries the library. Note that a resource copy"
    Write-Host "must be refreshed by re-running this script after every Rust change."
    Write-Host "打包构建现在会携带本库。注意：Rust 代码每次改动后都必须重新运行本脚本"
    Write-Host "刷新资源目录里的副本。"
}
else {
    Write-Host ""
    Write-Host "The development build is picked up automatically from"
    Write-Host "native/target/$profile/ — no copy step needed. Pass -Install to also"
    Write-Host "place it in resources/ for packaging."
    Write-Host "开发构建会被 native/target/$profile/ 自动发现——无需复制步骤。"
    Write-Host "传 -Install 可同时放入 resources/ 供打包使用。"
}

Write-Host ""
Write-Host "verify / 验证:"
Write-Host "  python -c `"from gifmanager.frontend.qt import images; print(images.describe())`""
Write-Host "  python tests/smoke_native.py"
Write-Host "  python tests/bench_native.py"
