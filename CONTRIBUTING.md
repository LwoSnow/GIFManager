# Contributing to GIFManager

Read this before you open a pull request. It is short, and the mechanical parts are checked by
scripts in `tools/`, so you can find out whether you are breaking one without asking anyone.

Longer explanations of the code live in [`docs/`](docs/). If you only want to run the thing, see
[`docs/RUNNING.md`](docs/RUNNING.md); this file is about changing it.

## Set it up

Python 3.10+ runs the package, but build the virtual environment with 3.12: Pillow's pinned wheel
is built for 3.12 specifically, and a newer interpreter from `PATH` fails with an `_imaging`
import error that says nothing about versions. PySide6 itself ships a 3.10+ wheel; the Pillow pin
is what decides this.

```bash
python -m venv .venv            # Windows: py -3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .                # the gifmanager / gifmanager-qml commands
python -m gifmanager            # the QML interface releases ship
```

`gifmanager` on its own starts the retired Qt Widgets shell. `python -m gifmanager`,
`gifmanager-qml` and `apps/gifmanager_qml.py` all start the QML one, which is the interface you
are usually fixing. The console scripts only exist after that editable install.

`make env` imports the compiled dependencies and names an interpreter that cannot load them; it
runs first in `make check` so a version mismatch is reported as such instead of as a missing
submodule.

## Before you push

```bash
make check      # environment, layering, style, translations, batch files, unit tests
make smoke      # the offscreen smoke suite, if you touched the interface
```

If the virtual environment is not active, pass the interpreter: `make check PYTHON=.venv/Scripts/python.exe`
on Windows, `make check PYTHON=.venv/bin/python` elsewhere.

CI does not run all of `make check`. It runs the layering, style, translation and unit checks,
plus `tests/smoke_qml.py`. A green pull request means those five pass. `make probe-services` is
not part of either: it needs a real desktop session for the tray and the global hotkey, and the
offscreen platform has neither.

`make` means GNU Make; on Windows use MSYS2 or Git Bash, because the recipes use POSIX shell
syntax (`QT_QPA_PLATFORM=offscreen python …`) that `cmd.exe` cannot run. Every target is one
command in the `Makefile`; `check` and `smoke` just run the others in a row.

## Code style

The project's code-style standard is PEP8 plus a comment rule. `tools/check_style.py` enforces
part of it and leaves part to the reviewer.

Machine-checked: ≤100 columns, no tabs, no trailing whitespace, exactly one trailing newline, and
a `"""` docstring only as the first statement of a file.

Convention, not checked: 4-space indentation, and the ordering inside a bilingual comment block.
Every `#` comment block is written in both languages, English first — the script only checks that
Chinese appears at all:

```python
# Frames decode off the GUI thread; QMovie would block it.
# 帧在界面线程之外解码；QMovie 会阻塞界面。
```

The script fails a block that contains no Chinese at all; it cannot tell the two halves apart, so
the ordering is on you. The rule is about blocks, not lines: the English half and the Chinese half
can sit on separate lines, which is how a sentence of either language fits into 100 columns.

Batch files are the exception you cannot edit your way out of. `cmd.exe` reads a `.bat` with the
console ANSI code page, so any Chinese in one makes it unrunnable while still looking fine in an
editor. `tools/check_batch_encoding.py` keeps them ASCII with CRLF; the Chinese explanation
belongs in `docs/`, where UTF-8 is correct.

## Layering

The architecture has one hard rule, and `tools/check_layers.py` parses the source to enforce it:

| Layer | May import | What the boundary buys |
|---|---|---|
| `gifmanager/core` | standard library; Pillow only through an optional import | testable without a display or a toolkit; no `sys.platform` branches |
| `gifmanager/platform` | `core` | the only place that knows Windows from Linux from macOS |
| `gifmanager/backend` | `core`, `platform` | one application object, still toolkit-free |
| `gifmanager/frontend` | anything | the only layer allowed to import PySide6 |

If a new capability needs the operating system — a window hint, a hotkey, a clipboard format —
it belongs in `gifmanager/platform/` behind a service in that backend's `SERVICES` table, not in
the front-end. If it needs a GUI toolkit, it belongs in `gifmanager/frontend/`. Anything that
satisfies both descriptions means the split is wrong, and the check will say so.

## Tests

`make test` discovers `tests/unit/` and `tests/integration/` and runs them with Qt offscreen; it
is 125 tests today. Behaviour that can be observed without a window belongs there.

Anything that only breaks in the interface goes in a `tests/smoke_*.py` script. No assertion can
judge whether a window looks right; `the grid created 0 delegates for 24 rows` is a fact.
`tests/capture_qml.py` renders the real interface to a PNG for the looking-at part:

```bash
python tests/capture_qml.py out.png --cards 24
```

Run that one on a real platform rather than offscreen: the offscreen platform has no CJK fonts
and every Chinese label comes out as tofu.

A bug fix comes with a test that fails before it and passes after. Write the test first if the
bug is reproducible; if it is not, put into the pull request what you did to make it show up.

## Translations

Never edit a key, only a value, and never rename a file without adding the old locale back —
the JSON tables under `resources/language/` are the interface contract. To add a language, copy
`en_US.json` to `<locale>.json`, translate the values, and run `python tools/sync_language_keys.py`.
It fails when one table is missing a key another table has, which is what keeps a half-translated
interface out of a release.

Both `zh_CN.json` and `en_US.json` have to be updated in the same commit when a feature adds
strings. `make lang` is the check.

## Commits and pull requests

Commit messages are the changelog, so use Conventional Commits with a scope where it helps:

```
fix(animation): drop stale decodes and serve the newest request first
docs: which files are the program, and which are generated
feat(linux): make the Linux front-end actually run on niri/Wayland
test: full scenario walkthrough, and two bugs it found
```

The subject says what changed. If the change needs a body, the body explains why this approach
and not the obvious one. A single commit that compiles and passes `make check` is worth more than
five that only make sense together.

Branch from `main` and keep a pull request on one topic; small diffs get reviewed properly. Say
what you changed, what you ran to verify it, and attach a screenshot or a capture when the
interface moved. If a check cannot run on your machine, say so in the pull request.

Bug reports belong in the issue templates under `.github/ISSUE_TEMPLATE/`. They ask for the
version, the build type and a log; the log path is printed at startup and is the same for the
portable and installed builds, so paste the line rather than guessing.

## Version and license

The version is written into four files: `gifmanager/__init__.py` (`__version__`, what the release
workflow reads), `pyproject.toml` (`[project].version`, what the package metadata carries), the
badge in each README (nothing generates those), and `native/Cargo.toml`. Bump the first three
together; the crate version is independent, because it is compiled into the Rust library and
reported by `images.describe()` rather than by the application. `tests/smoke_ui_tokens.py` asserts
the application version starts with `2.`, so a major bump touches that test too.

The project is MIT-licensed; by submitting a patch you agree to release it under the same
license. See [LICENSE](LICENSE).
