"""Verify importing from the bridge down to the store, and back into the model.

The path collection and the store's batch import were each already covered, but the
SEAM between them was not: the bridge decides which group receives the files, the
importer runs the batch off the GUI thread, and the report has to add up to the
number of files the user actually chose. A miscount here is invisible — the user sees
"imported 3" and does not know they picked 5.

Two properties matter beyond the happy path:

1. the report accounts for EVERY selected file exactly once, and
2. a refused import says so, rather than starting and silently importing nothing.

路径收集与存储层的批量导入此前各自已被覆盖，但两者之间的"接缝"没有：桥决定由哪个分组接收
文件、导入器在 GUI 线程之外运行批量、而报告必须正好合计为用户实际选择的文件数。这里数错是
看不见的——用户看到"已导入 3"，却不知道自己选了 5 个。

除正常路径外，还有两个性质重要：

1. 报告对"每一个"被选文件恰好计一次；
2. 被拒绝的导入会明说，而不是启动后静默导入零个。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.frontend.qml.importer import ImportReport, collect_paths
from gifmanager.frontend.qt.bridge import BackendAdapter


def section(title):
    print()
    print("=" * 4, title)


def make_png(path, size=(32, 32), colour=(200, 30, 30)):
    from PIL import Image

    Image.new("RGB", size, colour).save(path)
    return path


def pump(app, adapter, bridge, seconds=20.0):
    # Run the event loop until the import finishes.
    #
    # The import advances on a timer, so the event loop MUST run for it to make
    # progress; blocking on it would deadlock. `processEvents` plus a short sleep is
    # the standard way to drive a timer-driven job from a console test.
    # 运行事件循环直到导入结束。
    #
    # 导入由定时器推进，因此事件循环"必须"运行它才会前进；阻塞等待它会死锁。
    # `processEvents` 加短暂休眠是从控制台测试驱动定时器任务的标准方式。
    import time

    deadline = time.monotonic() + seconds
    report = {}
    bridge.importer.finished.connect(lambda data: report.update(data))
    while not report and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    # One more turn so the status line and the models settle.
    # 再走一轮，让状态行与模型稳定下来。
    app.processEvents()
    return report


def main():
    app = QApplication.instance() or QApplication([])
    if QGuiApplication.instance() is None:
        print("no GUI application")
        return 1
    problems = []

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)
        from gifmanager.frontend.qml.bridge import BackendBridge
        from gifmanager.frontend.qml.theme import ThemeBridge

        theme = ThemeBridge(adapter.settings)
        bridge = BackendBridge(adapter, theme)

        # A source folder with three importable images and one that is not.
        # 一个源文件夹，含三张可导入图片和一个不可导入文件。
        source = os.path.join(tmp, "source")
        os.makedirs(source)
        make_png(os.path.join(source, "one.png"), colour=(200, 30, 30))
        make_png(os.path.join(source, "two.png"), colour=(30, 200, 30))
        make_png(os.path.join(source, "three.png"), colour=(30, 30, 200))
        with open(os.path.join(source, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("not an image")

        image_group = backend.store.create_group("导入测试", "image")
        text_group = backend.store.create_group("文字组", "text")
        bridge.groups.reload()

        section("what the bridge says about the current target")
        print("canImportHere (All)  :", bridge.canImportHere())
        print("target group id (All):", bridge.currentImportGroupId())
        print("import targets       :", bridge.importTargets())
        if not bridge.canImportHere():
            problems.append("import is refused even though an image group exists")

        section("selecting a TEXT group must refuse to import")
        bridge.selectGroup(text_group)
        app.processEvents()
        print("canImportHere (text) :", bridge.canImportHere())
        if bridge.canImportHere():
            problems.append("a text group was accepted as an import target")

        section("importing a folder")
        bridge.selectGroup(image_group)
        app.processEvents()
        collected = collect_paths([source])
        print("collected            :",
              [os.path.basename(p) for p in collected])
        result = bridge.importFiles([source])
        print("bridge start         :", result)
        if not result.get("started"):
            problems.append(f"the import did not start: {result}")
        report = pump(app, adapter, bridge)
        print("report               :", report)
        if not report:
            problems.append("the import never reported completion")
        else:
            # EVERY selected file must be accounted for exactly once.
            # "每一个"被选文件必须恰好被计一次。
            total = (report.get("imported", 0) + report.get("skipped", 0)
                     + report.get("rejected", 0))
            print(f"accounted for        : {total} of {len(collected)}")
            if total != len(collected):
                problems.append(
                    f"the report accounts for {total} files but {len(collected)} "
                    f"were collected")
            if report.get("imported") != 3:
                problems.append(
                    f"expected 3 imported, got {report.get('imported')}")
            if report.get("rejected") != 1:
                problems.append(
                    f"expected 1 rejected (the .txt), got "
                    f"{report.get('rejected')}")
            if report.get("errors"):
                problems.append(f"the import reported errors: {report['errors']}")

        section("the library shows the imported stickers")
        app.processEvents()
        rows = bridge.stickers.rowCount()
        print("sticker rows         :", rows)
        if rows != 3:
            problems.append(f"the model shows {rows} rows, expected 3")

        section("importing the same folder again is all duplicates")
        result = bridge.importFiles([source])
        if not result.get("started"):
            problems.append("re-importing did not start")
        report = pump(app, adapter, bridge)
        print("second report        :", report)
        if report.get("imported") != 0:
            problems.append(
                f"re-import inserted {report.get('imported')} duplicate(s)")
        if report.get("skipped") != 3:
            problems.append(
                f"re-import skipped {report.get('skipped')}, expected 3")

        section("a refused import says so instead of importing nothing")
        bridge.selectGroup(text_group)
        app.processEvents()
        # The bridge refuses before starting, so no worker exists to report.
        # 桥在启动前就拒绝，因此不存在可报告的 worker。
        refused = bridge.importFiles([source])
        print("refused              :", refused)
        if refused.get("started"):
            problems.append("an import into a text group was allowed to start")
        if refused.get("reason") != "no-group":
            problems.append(
                f"the refusal gave reason {refused.get('reason')!r}, expected "
                f"'no-group'")

        section("an empty selection is refused rather than reported as success")
        bridge.selectGroup(image_group)
        app.processEvents()
        empty = bridge.importFiles([])
        print("empty                :", empty)
        if empty.get("started"):
            problems.append("an empty selection was allowed to start")

        section("the importer's own state is honest")
        print("running              :", bridge.importer.running)
        print("fraction             :", bridge.importer.fraction)
        print("filter               :", bridge.importer.filter[:60], "...")
        if bridge.importer.running:
            problems.append("the importer still reports itself as running")
        # After a COMPLETED import the fraction is 1.0, which is correct: the last
        # import really did finish. Asserting 0.0 here was the test's mistake — it
        # would have been asserting that a finished job looks unfinished. The
        # meaningful property is that fraction never exceeds 1 or goes negative.
        # 一次"已完成"的导入之后 fraction 是 1.0，这是正确的：上一次导入确实完成了。在此
        # 断言 0.0 是测试的错误——那等于断言已完成的任务看起来未完成。有意义的性质是 fraction
        # 从不超过 1 也不为负。
        if not (0.0 <= bridge.importer.fraction <= 1.0):
            problems.append(
                f"fraction {bridge.importer.fraction} is outside [0, 1]")
        # A fresh importer must report 0.0, or a progress bar in a newly opened dialog
        # would start full.
        # 全新的导入器必须报告 0.0，否则新打开对话框里的进度条会一开始就是满的。
        from gifmanager.frontend.qml.importer import ImportService

        fresh = ImportService(backend)
        print("fresh fraction       :", fresh.fraction)
        if fresh.fraction != 0.0:
            problems.append(
                f"a fresh importer reports {fresh.fraction}, expected 0.0")

        section("the report object itself")
        report_object = ImportReport(imported=2, skipped=1, rejected=3,
                                     group_name="g")
        print("as_dict              :", report_object.as_dict())
        if report_object.total != 6:
            problems.append("ImportReport.total does not sum its parts")

        section("shutdown")
        bridge.detach()
        backend.close()
        print("torn down cleanly")

    print()
    if problems:
        print("IMPORT CHECK FAILED / 导入检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("IMPORT CHECK OK / 导入检查通过")
    print("  files and folders are collected, the report accounts for every")
    print("  selection exactly once, duplicates are skipped, and an impossible")
    print("  target is refused instead of silently importing nothing")
    print("  文件与文件夹被收集、报告对每次选择恰好计一次、重复被跳过、不可能的目标被明确")
    print("  拒绝而不是静默导入零个")
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    _status = main()
    _sys.stdout.flush()
    _sys.stderr.flush()
    _os._exit(_status)
