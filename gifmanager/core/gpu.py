"""Per-application GPU preference policy, independent of any operating system.

The operating systems expose wildly different controls here:

* Windows has a per-application preference with exactly two classes (power
  saving / high performance) in the registry;
* macOS chooses the adapter itself and offers no per-application override;
* Linux leaves it to the driver (PRIME / DRI_PRIME) or the vendor panel.

So the *classifier* — mapping a detected adapter name onto one of those two
classes — is the part worth sharing, and it is pure string work. The registry or
driver write lives in `gifmanager.platform`.

按应用的 GPU 首选项策略，与操作系统无关。

各系统在这里提供的控制差异极大：

* Windows 在注册表里提供按应用的首选项，且只区分两类（省电 / 高性能）；
* macOS 自行选择适配器，不提供按应用覆盖；
* Linux 交给驱动（PRIME / DRI_PRIME）或厂商控制面板。

因此值得共用的是"分类器"——把检测到的适配器名映射到这两类之一，而这纯粹是字符串
处理。注册表或驱动写入位于 `gifmanager.platform`。
"""
import logging

log = logging.getLogger("GIFManager")

# Preference values. These are the portable meaning; each backend maps them onto
# whatever its system understands.
# 首选项取值。这是可移植的含义；各后端把它映射到自己的系统能理解的形式。
PREF_SYSTEM = 0   # let the OS decide / 由系统决定
PREF_POWER = 1    # power saving, usually integrated / 省电，通常核显
PREF_HIGH = 2     # high performance, usually discrete / 高性能，通常独显

VALID_PREFERENCES = (PREF_SYSTEM, PREF_POWER, PREF_HIGH)

# Registry value format Windows expects: "GpuPreference=<n>;" /
# Windows 期望的注册表值格式："GpuPreference=<n>;"
WINDOWS_VALUE_TEMPLATE = "GpuPreference={};"

# Discrete-card hints. Order matters: this list is checked FIRST.
#
# "Intel(R) Arc(TM) A770 Graphics" contains "intel" but is a discrete card, and
# checking the integrated list first returned PREF_POWER for it — an Arc owner
# asking for the discrete GPU was silently given the power-saving preference,
# which is the same value as a Radeon iGPU, so the drop-down could not tell them
# apart either.
# 独显特征词。顺序很重要：本列表"先"检查。
#
# "Intel(R) Arc(TM) A770 Graphics" 含 "intel" 却是独显，先查集显列表会把它判为
# PREF_POWER——选 Arc 独显的用户被静默写入省电偏好，而该值与 Radeon 核显相同，
# 下拉框也无法区分。
DISCRETE_HINTS = (
    "nvidia", "geforce", "rtx", "gtx", "quadro", "titan", "arc",
    "radeonrx", "radeonpro", "radeonvii", "fury", "nanopro",
)

# Integrated hints. Longer fragments are used wherever a bare vendor token would
# swallow a discrete model (see the ordering above). Newer AMD iGPUs
# ("Radeon 780M", "Radeon 680M") carry no "graphics"/"vega" token, so those
# three-digit M-series names are listed explicitly — they used to classify as
# None and were then dropped from the settings UI entirely.
# 集显特征词。凡裸厂商词会吞掉独显型号之处，均用更长的片段匹配（见上面的顺序）。
# 较新的 AMD 核显（"Radeon 780M"/"Radeon 680M"）不含 "graphics"/"vega" 字样，
# 因此显式列出这些三位数 M 系列名称——它们此前分类为 None，随后在设置界面被整个
# 丢弃。
INTEGRATED_HINTS = (
    "inteluhdgraphics", "intelhdgraphics", "inteliris", "irisxe",
    "uhdgraphics", "hdgraphics", "radeongraphics", "radeonvega", "vega",
    "integrated", "microsoftbasic", "basicdisplay", "llvmpipe", "swiftshader",
    "radeon610m", "radeon660m", "radeon680m", "radeon740m", "radeon760m",
    "radeon780m", "radeon880m", "radeon890m",
)

# Vendor marks stripped before matching, so "Radeon(TM) Graphics" hits the same
# hints as "Radeon Graphics". / 匹配前剥离的厂商标记，使 "Radeon(TM) Graphics"
# 与 "Radeon Graphics" 命中同一批特征词。
_VENDOR_MARKS = ("(tm)", "(r)", "(c)", "\u2122", "\u00ae")


def normalize_adapter_name(name):
    # Lower-case and strip vendor marks and punctuation so a name matches its
    # hint tokens. / 转小写并去掉厂商标记与标点，使名称能命中特征词。
    lowered = (name or "").lower()
    for mark in _VENDOR_MARKS:
        lowered = lowered.replace(mark, "")
    return "".join(ch for ch in lowered if ch.isalnum())


def classify_adapter(name):
    # PREF_HIGH for a discrete-looking adapter, PREF_POWER for an
    # integrated-looking one, None when the name is unknown or empty.
    # 独显特征 → PREF_HIGH；集显特征 → PREF_POWER；名称未知或为空 → None。
    normalized = normalize_adapter_name(name)
    if not normalized:
        return None
    # Strong discrete features first: Arc is an Intel discrete card, while
    # "Radeon Graphics" is an iGPU even though it contains "radeon" — the longer
    # fragments in INTEGRATED_HINTS keep that distinction intact.
    # 先判强独显特征：Arc 是 Intel 独显；而 "Radeon Graphics" 虽含 "radeon" 却是
    # 核显——INTEGRATED_HINTS 里更长的片段保住了这个区分。
    for hint in DISCRETE_HINTS:
        if hint in normalized:
            return PREF_HIGH
    for hint in INTEGRATED_HINTS:
        if hint in normalized:
            return PREF_POWER
    return None


def clamp_preference(value):
    # Coerce a stored value to a valid preference, defaulting to PREF_SYSTEM /
    # 把存储值强制为合法首选项，非法时回退 PREF_SYSTEM
    try:
        number = int(value)
    except (TypeError, ValueError):
        return PREF_SYSTEM
    return number if number in VALID_PREFERENCES else PREF_SYSTEM


def parse_windows_value(text):
    # Read the preference back out of a Windows registry string such as
    # "GpuPreference=2;". Returns None when the value is absent or unknown.
    # 从 "GpuPreference=2;" 这类 Windows 注册表字符串读回首选项。值缺失或未知时
    # 返回 None。
    for part in str(text or "").split(";"):
        part = part.strip()
        if part.lower().startswith("gpupreference="):
            try:
                number = int(part.split("=", 1)[1])
            except (IndexError, ValueError):
                return None
            return number if number in VALID_PREFERENCES else None
    return None


def wants_override(enabled, preference):
    # Whether a GPU preference should be written at all.
    #
    # With acceleration off the answer is no: writing a preference for a process
    # that does no GPU work would silently erase a system-level setting the user
    # may have made in their OS settings, and would have nothing to route.
    # 是否应该写入 GPU 首选项。
    #
    # 加速关闭时答案为否：为一个不做 GPU 工作的进程写首选项会静默抹掉用户可能在
    # 系统设置里做过的系统级设置，而且没有可路由的工作。
    if not enabled:
        return False
    return True


def should_apply(previous, current, enabled, explicit):
    # Decide whether to (re)apply a preference and whether the OS entry may be
    # removed. Returns (apply, allow_removal).
    #
    # The startup path must never REMOVE an existing preference: a stored
    # PREF_SYSTEM value there means "the user never chose", not "delete whatever
    # the OS has" — deleting on every launch would fight the OS settings page.
    # Only an explicit user action may delete the entry.
    # 决定是否（重新）应用首选项，以及是否允许删除系统项。返回 (是否应用, 是否允许删除)。
    #
    # 启动路径绝不能"删除"已有首选项：那里存储的 PREF_SYSTEM 意为"用户从未选择"，
    # 而非"删掉系统里的任何设置"——每次启动都删除会与系统设置页面相互打架。只有
    # 用户显式操作才允许删除该项。
    allow_removal = bool(explicit)
    if not explicit and current == previous:
        return (False, False)
    if current == PREF_SYSTEM and not allow_removal:
        return (False, False)
    return (True, allow_removal)


def describe_preference(preference, translate=None):
    # Human-readable label for a preference value. `translate` is an optional
    # `(key) -> str` callable so this module stays free of the language layer.
    # 首选项取值的人类可读标签。`translate` 是可选的 `(key) -> str` 回调，使本模块
    # 不依赖语言层。
    keys = {
        PREF_SYSTEM: "gpu_pref_system",
        PREF_POWER: "gpu_pref_power",
        PREF_HIGH: "gpu_pref_high",
    }
    key = keys.get(clamp_preference(preference), "gpu_pref_system")
    return translate(key) if translate else key


__all__ = [
    "DISCRETE_HINTS",
    "INTEGRATED_HINTS",
    "PREF_HIGH",
    "PREF_POWER",
    "PREF_SYSTEM",
    "VALID_PREFERENCES",
    "WINDOWS_VALUE_TEMPLATE",
    "clamp_preference",
    "classify_adapter",
    "describe_preference",
    "normalize_adapter_name",
    "parse_windows_value",
    "should_apply",
    "wants_override",
]
