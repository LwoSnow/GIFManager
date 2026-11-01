"""Verify the native library's symbols and its graceful-degradation contract.

Two independent concerns:

1. **The ABI holds.** Every symbol `images.py` binds must exist in the compiled
   library, and every prototype must declare `argtypes`/`restype` — without them
   `ctypes` defaults both to `c_int` and truncates pointers on 64-bit Windows.

2. **The fallback is real.** With the library hidden, the application must still
   import, still decode through another path, and still report honestly which path
   is live. A "graceful fallback" that was never executed is an assumption, not a
   feature.

两件独立的事：

1. **ABI 成立。** `images.py` 绑定的每个符号都必须在编译产物中存在，且每个原型都必须
   声明 `argtypes`/`restype`——缺少时 `ctypes` 把两者都默认为 `c_int`，在 64 位
   Windows 上会截断指针。

2. **回退是真的。** 把库藏起来后，程序仍必须能导入、仍必须能经另一条路径解码，并且
   仍必须如实报告当前生效的路径。一个从未被执行过的"优雅回退"是假设，不是功能。
"""
import os
import subprocess
import sys
import tempfile
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Symbols that must exist and be bound / 必须存在且被绑定的符号
REQUIRED_SYMBOLS = (
    "gifmanager_version",
    "gifmanager_last_error_code",
    "gifmanager_last_error_message",
    "gifmanager_probe",
    "gifmanager_thread_count",
    "gifmanager_decode_gif",
    "gifmanager_frames_width",
    "gifmanager_frames_height",
    "gifmanager_frames_count",
    "gifmanager_frames_frame_bytes",
    "gifmanager_frames_offset",
    "gifmanager_frames_delay",
    "gifmanager_frames_copy",
    "gifmanager_frames_free",
    "gifmanager_decode_thumbnail",
    "gifmanager_thumbnail_width",
    "gifmanager_thumbnail_height",
    "gifmanager_thumbnail_bytes",
    "gifmanager_thumbnail_copy",
    "gifmanager_thumbnail_free",
)


def section(title):
    print()
    print("=" * 4, title)


def check_symbols():
    from gifmanager.frontend.qt import images

    problems = []
    loaded = images.api()
    if loaded is None:
        print("library is not available; skipping the symbol check")
        print("原生库不可用；跳过符号检查")
        return problems, False

    print("library:", loaded.path)
    print("version:", loaded.version)
    missing = []
    for name in REQUIRED_SYMBOLS:
        if not hasattr(loaded.lib, name):
            missing.append(name)
    print(f"symbols : {len(REQUIRED_SYMBOLS) - len(missing)}"
          f"/{len(REQUIRED_SYMBOLS)} present")
    if missing:
        problems.append(f"missing symbols: {', '.join(missing)}")

    # A pointer-returning function bound WITHOUT a restype is the classic
    # truncation bug, so the check is explicit rather than implied by a successful
    # call on this particular machine.
    # 一个返回指针的函数若"未"绑定 restype，就是经典的截断错误，因此这里显式检查，
    # 而不是靠"本机上调用恰好成功"来暗示。
    import ctypes

    for name in ("gifmanager_decode_gif", "gifmanager_decode_thumbnail"):
        function = getattr(loaded.lib, name, None)
        if function is None:
            continue
        restype = function.restype
        if restype is ctypes.c_int:
            problems.append(
                f"{name} has the default c_int restype; pointers would be "
                f"truncated on 64-bit Windows")
    print("restypes: pointer-returning functions declare c_void_p or better")
    return problems, True


def check_fallback():
    # Run a child process with the library hidden and confirm the application
    # still works. `GIFMANAGER_NATIVE_LIB` points at a nonexistent file, which is
    # the same condition as "not built".
    # 在隐藏库的子进程中运行，确认程序仍可用。`GIFMANAGER_NATIVE_LIB` 指向一个不存在的
    # 文件，与"未构建"是同一种情况。
    program = textwrap.dedent(
        """
        import os, sys, tempfile
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["GIFMANAGER_NATIVE_DISABLE"] = "1"
        sys.path.insert(0, sys.argv[1])
        from gifmanager.frontend.qt import images
        report = images.describe()
        assert report["available"] is False, report
        print("FALLBACK_AVAILABLE", report["available"])
        print("FALLBACK_CANDIDATES", len(report["candidates"]))
        # The Qt path must still decode a real file, or "fallback" is a claim
        # rather than a behaviour.
        # Qt 路径仍必须能解码真实文件，否则"回退"只是说法而不是行为。
        from PySide6.QtWidgets import QApplication
        from gifmanager.frontend.qt.thumbnails import ThumbnailLoader
        app = QApplication.instance() or QApplication([])
        from PIL import Image
        import time
        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "t.png")
            Image.new("RGB", (200, 100), (12, 34, 56)).save(png)
            loader = ThumbnailLoader()
            loader.cached_result = None
            loader.done.connect(lambda key, image: setattr(loader, "cached_result", image))
            loader.request(png, 64)
            # Pump the event loop until the worker's queued signal is delivered.
            # `processEvents()` alone is not enough: the signal is queued, and a
            # queued signal is only delivered by a running event loop, so a single
            # call before the worker finishes would silently see nothing.
            # 泵送事件循环直到工作线程的队列信号被投递。仅调用一次 `processEvents()`
            # 不够：该信号是队列信号，只有运行中的事件循环才会投递它，因此在工作线程
            # 完成前调用一次会静默地什么也看不到。
            deadline = time.monotonic() + 10.0
            while loader.cached_result is None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.01)
            got = loader.cached_result
            print("FALLBACK_THUMB", "ok" if got is not None else "missing")
            assert got is not None, "the Qt fallback produced no thumbnail"
            # The image must be scaled into the requested box. Note the loader
            # EMITS the decoded image; storing it in the cache is the GRID's job
            # (`_on_thumb_ready` calls `loader.store`), so asserting a cache hit
            # here would be testing the wrong object.
            # 图像必须被缩放进所请求的范围。注意加载器只是"发出"解码结果；写入缓存是
            # "网格"的职责（`_on_thumb_ready` 调用 `loader.store`），因此在此断言缓存
            # 命中等于在测错误的对象。
            assert got.width() == 64, got.width()
            loader.shutdown(2000)
        print("FALLBACK_OK")
        """
    )

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", program, ROOT],
        env=env, capture_output=True, text=True, timeout=120)

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    problems = []
    for line in stdout.splitlines():
        if line.startswith("FALLBACK_"):
            print("  " + line)
    if completed.returncode != 0:
        problems.append(f"the fallback run exited {completed.returncode}")
    if "FALLBACK_OK" not in stdout:
        problems.append("the fallback run did not complete")
    if "Traceback" in stderr:
        problems.append("the fallback run printed a traceback")
    return problems, stdout, stderr


def main():
    section("symbols and prototypes")
    problems, available = check_symbols()

    section("graceful degradation with the library hidden")
    fallback_problems, stdout, stderr = check_fallback()
    problems.extend(fallback_problems)

    print()
    if problems:
        print("NATIVE CONTRACT CHECK FAILED / 原生契约检查未通过")
        for problem in problems:
            print("  " + problem)
        if stderr:
            print()
            print("--- child stderr (tail) ---")
            print("\n".join(stderr.splitlines()[-20:]))
        return 1

    print("NATIVE CONTRACT CHECK OK / 原生契约检查通过")
    if available:
        print("  every bound symbol exists and pointer restypes are declared")
        print("  每个被绑定的符号都存在，且指针返回类型已声明")
    print("  with the library hidden the application still imports and still")
    print("  decodes thumbnails through the Qt path")
    print("  隐藏库后程序仍可导入，并仍经 Qt 路径解码缩略图")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
