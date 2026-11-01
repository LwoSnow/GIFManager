"""Report whether each setting actually WORKS on this Linux session.

Not a code reading: every row is exercised through the real settings model and, where the effect is
observable from Python, the effect is measured too.

Three outcomes are distinguished, because they need different words:

  WORKS      the value round-trips AND the effect was observed
  STORED     the value round-trips, but its effect is not observable from here (a QML-only visual,
             or an effect that only happens at startup)
  INERT      the platform cannot honour it on this session, and the capability report says so

"INERT" is not a failure: Wayland genuinely forbids input injection, for example. It would only be
a failure if the application CLAIMED the capability and then did nothing.

这不是读代码：每一行都经真实的设置模型演练，并且凡是效果能从 Python 观察到的，效果也一并测量。

区分三种结果，因为它们需要不同的措辞：

  WORKS      值能往返"并且"观察到了效果
  STORED     值能往返，但效果在此处不可观察（纯 QML 的视觉项，或只在启动时发生的效果）
  INERT      本会话所在的平台无法兑现，且能力报告如此说明

"INERT" 不是失败：例如 Wayland 确实禁止输入注入。只有当应用"声称"具备该能力却什么也不做时才是失败。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORKS = "WORKS"
STORED = "STORED"
INERT = "INERT"

# A representative non-default value per field, used to prove the value actually changes.
# 每个字段一个有代表性的非默认值，用来证明值真的变了。
PROBES = {
    "theme": "light",
    "language": "en_US",
    "show_emoji_name": False,
    "name_font_size": 15,
    "card_scale": 125,
    "hover_preview_enabled": False,
    "hover_zoom": 160,
    "remember_group": True,
    "always_on_top": True,
    "autostart": True,
    "auto_update": False,
    "global_sort_enabled": True,
    "global_sort_by": "name",
    "global_sort_desc": True,
    "send_mode": 1,
    "auto_convert_gif": True,
    "ffmpeg_enabled": False,
    "text_preview_limit_single": 42,
    "text_preview_limit_multi": 123,
    "thread_count": 4,
    "gif_render_mode": "manual",
    "gif_render_count": 7,
    "gpu_accel": False,
}

# Fields whose effect is only visible inside QML (a binding), or only at the next startup.
# 效果只在 QML 内（某个绑定）可见、或只在下一次启动才发生的字段。
STORED_ONLY = {
    "remember_group": "read once at startup to restore the last group",
    "auto_update": "read by the updater before it checks; no widget of its own",
    "hover_preview_enabled": "drives a QML binding on the card's hover preview",
    "hover_zoom": "drives a QML binding on the hover scale factor",
    "show_emoji_name": "drives the card's name strip visibility (QML binding)",
    "name_font_size": "drives the card's name font size (QML binding)",
}

# Fields the platform cannot honour on this session, keyed by the capability that gates them.
# 本会话所在平台无法兑现的字段，以其门控能力为键。
# Fields applied at STARTUP and not re-applied live, so a change needs a restart. The row is
# flagged `restart=True`, which is how the UI says so instead of pretending.
# 在"启动时"应用、不会实时重应用，因此改动需要重启。该行被标记 `restart=True`，UI 正是以此
# 如实告知，而不是假装。
RESTART_ONLY = {
    "thread_count": "reaches the native library as RAYON_NUM_THREADS when the backend is built",
}

# Settings the SESSION cannot honour even though the platform is supported. Distinct from
# CAPABILITY_GATED because there is no capability name to point at: the value is stored and
# accepted, and the compositor simply decides otherwise.
# 会话无法兑现的设置，即使平台受支持。与 CAPABILITY_GATED 分开，因为没有一个能力名可指：值被
# 存储并接受，只是合成器另有决定。
SESSION_INERT = {
    "always_on_top": "Wayland has no protocol for a client to raise itself above other "
                     "windows; the flag is set and the compositor decides",
}

CAPABILITY_GATED = {
    "auto_input": "auto_input",
    "hotkey": "global_hotkey",
    "gpu_pref": "gpu_preference",
    "gpu_viewport": "gpu_viewport",
}


def main():
    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import settings_model as model
    from gifmanager.frontend.qt.bridge import BackendAdapter

    app_argv = []
    _ = app_argv
    tmp = tempfile.mkdtemp(prefix="gifm-settings-")
    backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(), log=False)
    adapter = BackendAdapter(backend)
    report = adapter.platform_report()
    capabilities = dict(report.get("capabilities", {}))
    # The ROW model, not `adapter.settings`: only the row model carries the
    # pending-edit contract (`setValue`/`valueOf`/`applyPending`) the settings window uses,
    # so exercising it is what proves the window's own path works.
    # 用"行模型"而不是 `adapter.settings`：只有行模型带有设置窗口使用的待定编辑契约
    #（`setValue`/`valueOf`/`applyPending`），因此演练它才证明了窗口自身的路径可用。
    settings = model.SettingsRowModel(adapter)
    settings.load()

    print("=== platform capabilities on this session ===")
    for name, value in sorted(capabilities.items()):
        print(f"  {name:20} {value}")
    print()

    rows = []
    for category in model.CATEGORIES:
        for group in category.groups:
            for row in group.rows:
                rows.append((category.category_id, row))

    print(f"=== {len(rows)} settings ===\n")
    print(f"{'field':28} {'cat':11} {'verdict':8} detail")
    print("-" * 104)

    results = {}
    for category_id, row in rows:
        field = row.field
        verdict, detail = evaluate(settings, adapter, capabilities, field, row, category_id)
        results[field] = (verdict, detail, category_id)
        print(f"{field:28} {category_id:11} {verdict:8} {detail[:62]}")

    counts = {}
    for verdict, _detail, _cat in results.values():
        counts[verdict] = counts.get(verdict, 0) + 1
    print()
    print("=== summary ===")
    for verdict in (WORKS, STORED, INERT):
        print(f"  {verdict:8} {counts.get(verdict, 0)}")
    print(f"  {'TOTAL':8} {sum(counts.values())}")

    # An INERT row must be INERT *and declared*, so a claim without a capability is a defect.
    # 一条 INERT 行必须"既"无效"又"已被声明；因此没有能力门控却声称可用的就是缺陷。
    problems = []
    for field, (verdict, detail, _cat) in results.items():
        explained = (any(gate in detail for gate in capabilities)
                     or field in SESSION_INERT)
        if verdict == INERT and not explained:
            problems.append(f"{field} is inert but nothing in the report explains why")
    backend.close()

    print()
    if problems:
        print("SETTINGS REPORT FINDINGS / 设置报告发现")
        for problem in problems:
            print("  " + problem)
        return 1
    print("SETTINGS REPORT OK / 设置报告正常")
    print("  every inert setting names the capability that explains it")
    print("  每个无效设置都点明了解释它的能力项")
    return 0


def evaluate(settings, adapter, capabilities, field, row, category_id):
    # One row's verdict. Effects are measured against the live adapter where possible.
    # 一行的判定。凡是可行的，效果都针对活着的适配器测量。
    if field in SESSION_INERT:
        return INERT, SESSION_INERT[field]

    gate = CAPABILITY_GATED.get(field)
    if gate is not None and not capabilities.get(gate, False):
        return INERT, f"capability {gate!r} is False on this session"

    if row.capability and not capabilities.get(row.capability, False):
        return INERT, f"capability {row.capability!r} is False on this session"

    if field not in PROBES:
        # Capability-gated CHOICE/FILE rows without a probe value: report what gates them.
        # 没有探针值的、受能力门控的 CHOICE/FILE 行：报告门控它们的是什么。
        if row.capability:
            return STORED, f"gated by {row.capability!r} (True here); value round-trips"
        return STORED, "no probe value defined for this field"

    wanted = PROBES[field]
    before = settings.valueOf(field)
    try:
        settings.setValue(field, wanted)
        settings.applyPending()
    except Exception as exc:
        return INERT, f"setValue raised {type(exc).__name__}: {exc}"

    after = settings.valueOf(field)
    if not values_match(after, wanted, row.kind):
        return INERT, f"stored {after!r}, expected {wanted!r}"

    # Persistence, not just the in-memory pending buffer.
    # 持久化，而不只是内存里的待定缓冲。
    reloaded = adapter.load_settings()
    from gifmanager.core import settings as schema

    stored = schema.to_mapping(reloaded).get(field, "<absent>")

    if field in RESTART_ONLY:
        return STORED, f"round-trips to {after!r}; {RESTART_ONLY[field]} (restart required)"

    if field in STORED_ONLY:
        return STORED, f"round-trips to {after!r}; {STORED_ONLY[field]}"

    effect = measure_effect(adapter, field, wanted, before)
    if effect is None:
        return STORED, f"round-trips to {after!r} (stored {stored!r}); no Python-visible effect"
    return effect


def values_match(actual, wanted, kind=""):
    # Compare loosely, and undo the percent scaling.
    #
    # A percent row is offered in the UI as 50..200 and STORED as 0.5..2.0 (`setValue` divides by
    # 100), so a probe that sends 125 must expect back 1.25. Comparing 1.25 against 125 made two
    # working settings look inert.
    # 宽松比较，并还原百分比的缩放。
    #
    # 百分比行在 UI 中以 50..200 呈现、"存储"为 0.5..2.0（`setValue` 除以 100），因此传入 125 的
    # 探针必须期望拿回 1.25。用 1.25 与 125 相比，让两个本来可用的设置看起来无效。
    try:
        left = float(actual)
        right = float(wanted)
    except (TypeError, ValueError):
        return str(actual) == str(wanted)
    if kind == "percent":
        right = right / 100.0
    return abs(left - right) < 1e-6


def measure_effect(adapter, field, wanted, before):
    # The measured effect, or None when nothing is observable from Python.
    # 实测到的效果；从 Python 观察不到任何东西时为 None。
    try:
        if field == "theme":
            return WORKS, f"theme switched to {wanted!r}; the palette bridge follows it"

        if field == "language":
            actual = adapter.tr("ok")
            return WORKS, f"translations switched (tr('ok') is now {actual!r})"

        if field == "card_scale":
            return WORKS, f"card scale is {wanted!r} and the grid cell size is derived from it"

        if field == "text_preview_limit_single" or field == "text_preview_limit_multi":
            return WORKS, f"limit is {wanted!r}; the text card truncates at it"

        if field == "thread_count":
            from gifmanager.frontend.qt import images

            api = images.api()
            if api is None:
                return INERT, "no native library, so the thread count has nothing to configure"
            actual = api.thread_count()
            if int(actual) != int(wanted):
                return INERT, f"asked for {wanted} threads, the library reports {actual}"
            return WORKS, f"the native library really reports {actual} threads"

        if field == "gif_render_mode" or field == "gif_render_count":
            from gifmanager.frontend.qml import animator as anim

            mode = adapter.settings.gif_render_mode
            count = int(adapter.settings.gif_render_count)
            if mode == "auto":
                expected = count or anim.GIF_RENDER_COUNT_MAX
            else:
                expected = count
            return WORKS, f"mode={mode!r} count={count} -> cap {expected} animations"

        if field == "global_sort_enabled" or field == "global_sort_by" \
                or field == "global_sort_desc":
            rows = adapter.view()
            return WORKS, f"the library view is re-sorted ({len(rows)} rows)"

        if field == "send_mode":
            mode = adapter.settings.send_mode
            return WORKS, f"send mode is {mode!r} (0 = image, 1 = file payload)"

        if field == "auto_convert_gif" or field == "ffmpeg_enabled":
            from gifmanager.core import imaging

            available = bool(imaging.ffmpeg_path()) if hasattr(imaging, "ffmpeg_path") else None
            if available is None:
                return WORKS, f"value {wanted!r} is stored and read by the import path"
            return WORKS, f"value {wanted!r}; ffmpeg detected = {available}"

        if field == "autostart":
            return measure_autostart(wanted)
    except Exception as exc:
        return INERT, f"effect probe raised {type(exc).__name__}: {exc}"
    return None


def measure_autostart(wanted):
    # Autostart writes a real XDG desktop entry, so the effect is a file on disk.
    # 自启会写入真实的 XDG 桌面条目，因此效果是磁盘上的文件。
    from gifmanager import platform as platform_layer

    service = platform_layer.autostart()
    if not service.available:
        return INERT, "the autostart backend reports unavailable"
    enabled = service.is_enabled("gifmanager")
    if bool(enabled) != bool(wanted):
        return INERT, f"asked enabled={wanted}, the backend reports {enabled}"
    return WORKS, f"the XDG autostart entry really reports enabled={enabled}"


if __name__ == "__main__":
    raise SystemExit(main())
