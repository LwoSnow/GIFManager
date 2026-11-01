"""Ad-hoc smoke check for the core and platform layers.

核心层与平台层的临时冒烟检查。
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gifmanager import __version__
from gifmanager.core import grid_layout, gpu, hotkeys, paths
from gifmanager.core.imaging import signatures
from gifmanager.core.store.repository import Store
from gifmanager.platform import current, describe


def section(title):
    print()
    print("=" * 4, title)


def main():
    section("platform")
    print("version:", __version__)
    print("sys.platform:", sys.platform)
    print("registered:", sorted(
        {v for v in __import__("gifmanager.platform.base",
                               fromlist=["Platform"]).Platform.REGISTRY.values()}))
    report = describe()
    print("active key:", report["platform_key"], "->", report["backend_module"])
    for row in report["services"]:
        print("  {service:<16} implemented={implemented!s:<5} "
              "backend={backend:<28} available={available}".format(**row))

    section("paths")
    # The platform's directory rules must be installed before anything reads a
    # path; `create_backend` does this, and the core falls back to generic
    # POSIX rules until then.
    # 平台的目录规则必须在读取任何路径之前安装；`create_backend` 会做这件事，在那之前
    # 核心层回退到通用 POSIX 规则。
    from gifmanager.backend.app import install_platform_paths

    install_platform_paths()
    from gifmanager.platform import paths as platform_paths
    print("backend module:", platform_paths.backend_name())
    for name in ("user_data_dir", "user_config_dir", "user_cache_dir",
                 "user_log_dir", "user_documents_dir"):
        print(f"  {name:<20}", getattr(platform_paths, name)())
    print("  core data_dir       ", paths.data_dir())
    print("  core logs_dir       ", paths.logs_dir())

    section("hotkeys")
    print("parse 'Ctrl+Shift+F10':", hotkeys.HotkeyBinding.parse("Ctrl+Shift+F10"))
    print("describe Ctrl+Alt+K:", hotkeys.HotkeyBinding.parse("Ctrl+Alt+K").describe())
    print("describe Meta+K:", hotkeys.HotkeyBinding(8, "K").describe())

    section("gpu classification")
    for name in ("Intel(R) Arc(TM) A770 Graphics", "Intel(R) UHD Graphics 630",
                 "AMD Radeon 780M", "NVIDIA GeForce RTX 4060 Laptop GPU",
                 "Radeon(TM) Graphics", "Microsoft Basic Display Adapter"):
        print(f"  {name:<40} -> {gpu.classify_adapter(name)}")

    section("grid layout")
    print("row-major 5 over 3:", grid_layout.row_major_columns([1, 2, 3, 4, 5], 3))
    print("flatten back:", grid_layout.flatten_columns(
        grid_layout.row_major_columns([1, 2, 3, 4, 5], 3)))
    print("distribute evenly 7/3:", grid_layout.distribute_evenly(7, 3))
    rows = [{"col_index": 0, "sort_order": 2}, {"col_index": 1, "sort_order": 0}]
    print("visual order:", grid_layout.visual_order(rows))

    section("store")
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(data_dir=tmp)
        print("data dir:", store.data_dir)
        groups = store.get_all_groups()
        print("builtin:", [(g["id"], g["name"], g["builtin_role"]) for g in groups])
        gid = store.create_group("冒烟测试")
        print("created:", gid, store.group_name(gid))
        print("all-group id:", store._all_group_id(), "default:", store.default_group_id())
        print("counts:", store.count_all_emojis(), store.count_image_emojis(),
              store.count_emojis_in_group(gid))
        print("renamed:", store.rename_group(gid, "改名成功"),
              "->", store.group_name(gid))
        print("deleted:", store.delete_group(gid), "->", store.group_name(gid))
        store.close()
    print()
    print("OK")


if __name__ == "__main__":
    main()
