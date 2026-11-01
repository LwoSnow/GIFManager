"""Check and repair the translation tables.

# Why this exists as a permanent tool

Three one-off scripts added keys during development, which meant three files to
remember and three chances to add a key to only one language. This replaces them with
the one operation that actually matters at the end: REPORT any key missing from either
file, and optionally fill the gap with the other language's value so a build never
shows a raw key name.

# What it does not do

It cannot translate. Filling a gap copies the other language's text, which is a visible
"this needs translating" marker rather than a silent fallback to a key name — and
`--check` (the default) reports the gap without touching anything, which is the mode a
CI check wants.

# 为什么它作为常驻工具存在

开发期间有三个一次性脚本添加键，意味着三个需要记住的文件、以及三次"只把键加进一种语言"的
机会。本工具用真正要紧的那一个操作取代它们：报告任一文件中缺失的键，并可选地用另一种语言的
取值填补缺口，使构建永远不会显示原始键名。

# 它不做什么

它无法翻译。填补缺口会复制另一种语言的文本，那是一个可见的"此处待翻译"标记，而不是静默回退
到键名——而 `--check`（默认）只报告缺口、不动任何东西，那正是 CI 检查想要的模式。
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LANGUAGE_DIR = ROOT / "resources" / "language"

# The reference language. A key present here and absent elsewhere is a gap that needs
# filling; a key present ONLY in another file is a stale entry.
# 参考语言。在这里存在而在他处缺失的键是需要填补的缺口；只存在于另一个文件的键是陈旧条目。
REFERENCE = "en_US.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def tables():
    found = {}
    for path in sorted(LANGUAGE_DIR.glob("*.json")):
        found[path.name] = (path, load(path))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the translation tables for missing keys.")
    parser.add_argument(
        "--fix", action="store_true",
        help="fill a missing key with the reference language's value "
             "(default: report only)")
    parser.add_argument(
        "--quiet", action="store_true",
        help="print only the summary line")
    args = parser.parse_args(argv)

    found = tables()
    if not found:
        print(f"no translation tables in {LANGUAGE_DIR}")
        return 1
    if REFERENCE not in found:
        print(f"the reference table {REFERENCE} is missing")
        return 1

    _path, reference = found[REFERENCE]
    problems = 0
    total_keys = len(reference)

    for name, (path, data) in found.items():
        if name == REFERENCE:
            continue
        missing = sorted(set(reference) - set(data))
        extra = sorted(set(data) - set(reference))
        if not args.quiet:
            print(f"{name}: {len(data)} keys "
                  f"(reference has {total_keys})")
            if missing:
                print(f"  MISSING {len(missing)}:")
                for key in missing[:40]:
                    print(f"    {key}")
                if len(missing) > 40:
                    print(f"    ... and {len(missing) - 40} more")
            if extra:
                # Not an error on its own — a language may legitimately carry a key the
                # reference dropped — but worth seeing, because it usually means a
                # rename was applied to one file only.
                # 本身不是错误——某种语言合理地保留参考语言已删除的键——但值得一看，因为它
                # 通常意味着重命名只应用到了一个文件。
                print(f"  extra (not in the reference) {len(extra)}:")
                for key in extra[:20]:
                    print(f"    {key}")
        if missing:
            problems += len(missing)
            if args.fix:
                for key in missing:
                    data[key] = reference[key]
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=4,
                               sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
                if not args.quiet:
                    print(f"  -> filled {len(missing)} key(s) from {REFERENCE}; "
                          f"these need translating")

    print()
    if problems and not args.fix:
        print(f"TRANSLATION CHECK FAILED / 翻译检查未通过: {problems} missing key(s)")
        print("re-run with --fix to fill them from the reference language, then "
              "translate the copied text")
        return 1
    if problems:
        print(f"TRANSLATION CHECK REPAIRED / 翻译检查已修复: {problems} key(s) filled")
        print("the filled values are the reference language's text and need "
              "translating")
        return 0
    print(f"TRANSLATION CHECK OK / 翻译检查通过: "
          f"{len(found)} table(s), {total_keys} keys, none missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
