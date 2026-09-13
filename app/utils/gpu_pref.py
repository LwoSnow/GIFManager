"""GPU preference helper (Windows).

Qt cannot select a specific adapter for a process, but Windows exposes a
per-application GPU preference (the same setting as Settings -> Display ->
Graphics) in the registry:

    HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences
        <full path to exe> = "GpuPreference=<n>;"

where <n> is 0 = let Windows decide, 1 = power saving, 2 = high performance.
This module reads/writes that value so the app can ask Windows to prefer the
integrated or the discrete GPU. Adapters are listed for information only.

GPU 首选项辅助（Windows）。Qt 无法为进程指定某块显卡，但 Windows 提供了
按应用的 GPU 首选项（与"设置 → 显示 → 图形设置"同一项），位于注册表：
    HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences
        <exe 完整路径> = "GpuPreference=<n>;"
其中 <n>：0 = 由 Windows 决定，1 = 省电，2 = 高性能。本模块读写该值，使应用
可以请求 Windows 优先使用核显或独显。适配器列表仅用于展示。
"""
import os
import subprocess
import sys

_REG_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"

# Preference values / 首选项取值
PREF_SYSTEM = 0     # let Windows decide / 由 Windows 决定
PREF_POWER = 1      # power saving (usually integrated) / 省电（通常核显）
PREF_HIGH = 2       # high performance (usually discrete) / 高性能（通常独显）

_VALID = (PREF_SYSTEM, PREF_POWER, PREF_HIGH)


def _winreg():
    try:
        import winreg
        return winreg
    except ImportError:
        return None


def apply_preference(exe_path, pref):
    # Write (or remove) the per-app GPU preference. Returns True on success.
    # 写入（或删除）按应用的 GPU 首选项，成功返回 True。
    reg = _winreg()
    if reg is None or os.name != "nt" or not exe_path:
        return False
    try:
        pref = int(pref)
    except (TypeError, ValueError):
        return False
    if pref not in _VALID:
        return False
    try:
        key = reg.CreateKeyEx(reg.HKEY_CURRENT_USER, _REG_PATH, 0,
                              reg.KEY_SET_VALUE)
        try:
            # Drop the legacy entry that used the script path as the key (it
            # never matched, so it only confused things). / 删除旧版用脚本路径
            # 作为键的残留项（它永远不会被匹配，只会造成误解）。
            legacy = legacy_exe()
            if legacy and legacy != exe_path:
                try:
                    reg.DeleteValue(key, legacy)
                except FileNotFoundError:
                    pass
            if pref == PREF_SYSTEM:
                # Remove our override so Windows decides again /
                # 删除覆盖项，交回 Windows 决定
                try:
                    reg.DeleteValue(key, exe_path)
                except FileNotFoundError:
                    pass
            else:
                reg.SetValueEx(key, exe_path, 0, reg.REG_SZ,
                               f"GpuPreference={pref};")
        finally:
            reg.CloseKey(key)
        return True
    except OSError:
        return False


def get_preference(exe_path):
    # Read back the stored preference (PREF_*), or None when unset/unknown.
    # 读回已存储的首选项（PREF_*），未设置/无法读取时返回 None。
    reg = _winreg()
    if reg is None or os.name != "nt" or not exe_path:
        return None
    try:
        key = reg.OpenKey(reg.HKEY_CURRENT_USER, _REG_PATH, 0, reg.KEY_READ)
        try:
            value, _typ = reg.QueryValueEx(key, exe_path)
        finally:
            reg.CloseKey(key)
    except OSError:
        return None
    text = str(value)
    for part in text.split(";"):
        part = part.strip()
        if part.lower().startswith("gpupreference="):
            try:
                n = int(part.split("=", 1)[1])
            except (IndexError, ValueError):
                return None
            return n if n in _VALID else None
    return None


def list_adapters():
    # Best-effort list of installed display adapters (informational only).
    # 尽力列出已安装的显示适配器（仅供参考）。
    if os.name != "nt":
        return []
    try:
        kwargs = {}
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        # Force UTF-8 on the PowerShell side. Without it a Chinese Windows
        # encodes the pipe as CP936, so a non-ASCII adapter name (e.g.
        # "微软基本显示适配器") decoded as UTF-8 became U+FFFD and the adapter
        # was then dropped as unclassifiable.
        # 强制 PowerShell 侧输出 UTF-8。否则中文 Windows 会用 CP936 编码管道，
        # 非 ASCII 的显卡名（如"微软基本显示适配器"）按 UTF-8 解码就变成 U+FFFD，
        # 该显卡随后因无法分类而被丢弃。
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, timeout=5, **kwargs)
        text = (out.stdout or b"").decode("utf-8", "replace")
        if not text.strip():
            # Fall back to the OEM code page if the console reset was ignored /
            # 若控制台编码设置未生效，回退到 OEM 代码页
            text = (out.stdout or b"").decode(
                "mbcs" if os.name == "nt" else "utf-8", "replace")
        names = [ln.strip().replace("\ufffd", "").strip()
                 for ln in text.splitlines()]
        return [n for n in names if n]
    except (OSError, subprocess.SubprocessError):
        return []


def current_exe():
    # Windows keys its per-app GPU preference on the PROCESS IMAGE, i.e. the
    # executable that is actually running — `python.exe` when started from
    # source, the packaged exe when frozen. Returning the script path (as an
    # earlier version did) wrote a registry entry Windows never matches, which
    # is why the discrete GPU was never selected even though the value was
    # present in the registry.
    # Windows 的按应用 GPU 首选项以"进程映像"（真正运行的可执行文件）为键——
    # 源码运行时是 python.exe，打包后是应用 exe。此前返回脚本路径，写进去的
    # 注册表项 Windows 根本不会匹配，所以即使注册表里有记录也从未切到独显。
    try:
        exe = sys.executable
    except Exception:
        exe = ""
    return os.path.abspath(exe) if exe else ""


def legacy_exe():
    # The script path an older version wrongly used as the registry key; it is
    # removed when applying a preference so the stale entry does not linger.
    # 旧版本误用作注册表键的脚本路径；应用首选项时一并删除，避免残留。
    #
    # ONLY the app's own launcher qualifies. sys.argv[0] is whatever script the
    # interpreter was started with — a test file, or any script the user runs —
    # and deleting its GPU entry would silently discard a preference the user
    # created in Windows Settings for that program.
    # 只有程序自己的启动脚本才算。sys.argv[0] 是解释器启动时使用的任意脚本
    # （测试文件、用户自己的脚本），删除它的 GPU 项会静默丢弃用户在 Windows
    # 设置里为那个程序建立的偏好。
    if getattr(sys, "frozen", False):
        return ""
    try:
        script = sys.argv[0] if sys.argv else ""
    except Exception:
        script = ""
    if not script:
        return ""
    script = os.path.abspath(script)
    if os.path.basename(script).lower() not in (
            "main.py", "main.pyw", "gifmanager.py", "gifmanager.pyw"):
        return ""
    root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    if os.path.dirname(script) != root:
        return ""
    return script


# Classify a detected adapter so a name can be mapped onto the only two values
# Windows supports (1 = power saving / integrated, 2 = high performance /
# discrete). Windows itself only distinguishes those two classes.
# 将检测到的显卡名映射到 Windows 仅支持的两种取值（1 = 省电/集显，
# 2 = 高性能/独显）。Windows 本身也只区分这两类。
#
# Order matters: the DISCRETE list is checked FIRST. "Intel(R) Arc(TM) A770
# Graphics" contains "intel" but is a discrete card, and the old order returned
# PREF_POWER for it — an Arc owner asking for the discrete GPU was silently
# given the power-saving preference (the same value as a Radeon iGPU, so the
# drop-down could not tell them apart either).
# 顺序很重要：先查独显特征。"Intel(R) Arc(TM) A770 Graphics" 含 "intel" 却是
# 独显，旧顺序把它判为集显——选 Arc 独显的用户被静默写入省电偏好（与 Radeon
# 核显同值，下拉框也无法区分）。
_DISCRETE_HINTS = (
    "nvidia", "geforce", "rtx", "gtx", "quadro", "titan", "arc",
    "radeonrx", "radeonpro", "radeonvii", "fury", "nanopro",
)
# Integrated hints. Longer fragments are used wherever a bare vendor token would
# swallow a discrete model (see the ordering above). Newer AMD iGPUs
# ("Radeon 780M", "Radeon 680M") carry no "graphics"/"vega" token, so those
# 3-digit M-series names are listed explicitly — they used to return None and
# were then dropped from the settings UI entirely.
# 集显特征。凡裸厂商词会吞掉独显型号之处，均用更长的片段匹配（见上面的顺序）。
# 较新的 AMD 核显（"Radeon 780M"/"Radeon 680M"）不含 "graphics"/"vega" 字样，
# 因此显式列出这些 3 位数 M 系列名称——它们此前返回 None，随后在设置界面被整个
# 丢弃。
_INTEGRATED_HINTS = (
    "inteluhdgraphics", "intelhdgraphics", "inteliris", "irisxe",
    "uhdgraphics", "hdgraphics", "radeongraphics", "radeonvega", "vega",
    "integrated", "microsoftbasic", "basicdisplay", "llvmpipe", "swiftshader",
    "radeon610m", "radeon660m", "radeon680m", "radeon740m", "radeon760m",
    "radeon780m", "radeon880m", "radeon890m",
)


def _normalize(name):
    # Lower-case and strip vendor marks/punctuation so "Radeon(TM) Graphics"
    # matches the same tokens as "Radeon Graphics".
    # 转小写并去掉厂商标记与标点，使 "Radeon(TM) Graphics" 与
    # "Radeon Graphics" 命中同一批特征词。
    low = (name or "").lower()
    for junk in ("(tm)", "(r)", "(c)", "™", "®"):
        low = low.replace(junk, "")
    return "".join(ch for ch in low if ch.isalnum())


def classify_adapter(name):
    # PREF_HIGH for a discrete-looking adapter, PREF_POWER for an
    # integrated-looking one, None when unknown.
    # 独显特征 → PREF_HIGH；集显特征 → PREF_POWER；无法判断 → None。
    norm = _normalize(name)
    if not norm:
        return None
    # Strong discrete features first: Arc is an Intel discrete card, while
    # "Radeon Graphics" is an iGPU even though it contains "radeon" — the
    # longer fragments in _INTEGRATED_HINTS keep that distinction intact.
    # 先判强独显特征：Arc 是 Intel 独显；而 "Radeon Graphics" 虽含 "radeon" 却
    # 是核显——_INTEGRATED_HINTS 里更长的片段保住了这个区分。
    for hint in _DISCRETE_HINTS:
        if hint in norm:
            return PREF_HIGH
    for hint in _INTEGRATED_HINTS:
        if hint in norm:
            return PREF_POWER
    return None


def preferred_exe_display():
    # Human-readable target for the UI / 供界面显示的目标可执行文件
    exe = current_exe()
    return exe or "(unknown / 未知)"
