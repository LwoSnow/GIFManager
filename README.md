<p align="center"><img src="assets/logo.png" width="128" alt="GIFManager logo"></p>

<h1 align="center">GIFManager</h1>

<p align="center"><b>Your emoji, sticker and GIF library — one keystroke away from any application.</b></p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <b>English</b>
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-2.0.0-4a4a55?style=flat-square">
  <img alt="python" src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square">
  <img alt="qt" src="https://img.shields.io/badge/Qt-6.11-41cd52?style=flat-square">
  <img alt="platforms" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-2ea44f?style=flat-square">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square">
</p>

<p align="center"><img src="https://count.getloli.com/@Lwogifmanagerreadnums?theme=moebooru" alt="ReadNums"></p>

GIFManager keeps the pictures you send a hundred times a day — reaction GIFs, stickers, plain
emoji, the odd one-line snippet — in a library on your own disk. Hit the global hotkey, click a
card, and it is on the clipboard of whatever you were typing into, ready to paste or already
pasted.

Nothing to sign up for. The library is a SQLite database next to your files, and the sending
path makes no network request at all.

![The library window](assets/screenshot.png)

## What it does

A library you arrange. Image groups hold pictures and text groups hold snippets; the two never
mix, so the right-hand column is never ambiguous. Import from files or from a whole folder,
recursively — anything that is not a GIF yet gets converted on the way in (ffmpeg for animated
sources, Pillow for stills), so a folder of PNGs becomes a GIF library without a second tool.
Search the open group as you type. Sort by import time, name, or how often you actually send a
sticker: that last one is measured, not guessed, and the counter goes up on every send.

Sending that stays on the keyboard. The hotkey takes a lone key (`F10`) or a combination
(`Ctrl+Alt+F8`). A bare key is allowed on purpose — a tray utility whose only shortcut demands
a modifier is harder to use, not safer. A click puts the image on the clipboard as image data
or as its file path, which is the form QQ and WeChat accept directly; which one is a setting.
Turn on auto-paste and the paste keystroke goes back to the window you came from, so the whole
interaction is hotkey → click → already in the chat. The tray icon shows, hides and quits the
app. On Windows, launching it again says one is already running; on Linux, where the shortcut
belongs to the compositor, it passes `--toggle`, `--show`, `--hide` or `--quit` to the running
copy instead.

Editing a whole library at once. Edit mode turns the grid into a selection surface: click to
toggle a card, drag to paint over several, select all or none, then delete or move the lot
together. Cards can also be dragged into an order by hand. Text stickers cover the things you
send that are a sentence rather than a picture, with separate limits for one-line and multi-line
stickers.

Quiet by default. Dark and light themes apply the moment you pick one — no restart, no
confirmation dialog. HarmonyOS Sans SC ships with the app in six weights, so the grid and its
dialogs measure the same on every machine instead of inheriting whatever the host installed.
The palette stays low contrast: base surfaces sit a few percent apart and only the selected
card is bright, because a window you open dozens of times a day has no business shouting.
Frameless, remembers the last group and the window geometry, can stay on top, can start with
the system.

Fast past a thousand stickers. Frames decode on a worker pool, never on the thread that draws,
and are cached under a pixel budget. Only the animations on screen play; everything else holds
a still frame. The decode queue is newest-first and drops requests you have already scrolled
past, so a fast flick through a big group does not leave the visible row waiting behind rows
you left.

Playback needs a native decoder. `make native` builds the Rust one from `native/`, and passing
`--install` to `scripts/build-native.*` copies it into `resources/` so a packaged build can carry
it. The C helper compiled from `resources/gifdec.c` is the other route. Without either, GIF cards
show their first frame and stay still.

## Platforms

| | Windows | Linux | macOS |
|---|---|---|---|
| Interface (Qt Quick) | ✅ | ✅ | ⚠️ untested |
| Frameless window, rounded corners | ✅ DWM | ✅ | ⚠️ untested |
| Global hotkey | ✅ `RegisterHotKey` | ✅ X11 · Wayland: bind it in the compositor | ❌ not implemented |
| Clipboard send + auto-paste | ✅ `SendInput` | ⚠️ X11 needs `xdotool` · Wayland forbids synthetic input | ⚠️ untested |
| Tray icon | ✅ | ✅ needs a StatusNotifier host | ⚠️ untested |
| Start with the system | ✅ registry | ✅ XDG autostart | ⚠️ untested |
| Second launch is blocked | ✅ mutex | ✅ socket | ❌ a second copy starts |
| Second launch forwards `--toggle` | ❌ | ✅ | ❌ |

The shipped build has only been run on Windows and on Arch + niri (Wayland). Two things bite on
Wayland. The compositor owns global shortcuts, so the application cannot register one: bind a key
to `gifmanager --toggle` instead, and `packaging/niri-binds.kdl` has a working example. That
binding is what the second-launch command channel exists for, and why the channel is Linux-only.
The other trap is the desktop entry, which has to be installed as `gifmanager.desktop` because
the XDG portal looks the application up by that name before it hands out an app id;
`scripts/install-desktop-entry.sh` does it.

The macOS backend exists but has never been executed — not by CI, not by hand — so treat it as
unproven, not supported. Its Carbon hotkey backend says out loud that it is not implemented
instead of pretending. With no single-instance backend there, a second launch simply starts a
second copy.

## Install

Releases are built by hand from `.github/workflows/build.yml` and attached to the release page.

| Platform | File | How |
|---|---|---|
| Windows | `GIFManager-Setup-<version>.exe` | Inno Setup installer, per-user by default |
| Windows | `GIFManager-<version>-win64.zip` | Portable: unpack and run, data stays beside the executable |
| Debian/Ubuntu | `gifmanager_<version>_amd64.deb` | `sudo apt install ./gifmanager_*.deb` |
| Any Linux | `GIFManager-<version>-linux-x86_64.AppImage` | `chmod +x`, then run |
| Any Linux | `GIFManager-<version>-linux-x86_64.bin` | Self-extracting installer, `--help` for options |
| Arch | `gifmanager-<version>-1-x86_64.pkg.tar.zst` | `sudo pacman -U` |
| Flatpak | `GIFManager-<version>-x86_64.flatpak` | `flatpak install ./GIFManager-*.flatpak` — *experimental, built only on request* |

From source it is a venv, one requirements file and an entry point:

```bash
git clone https://github.com/LwoSnow/GIFManager.git
cd GIFManager

python -m venv .venv
# Windows: py -3.12 -m venv .venv   (3.12, not whatever `python` is)
source .venv/bin/activate           # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python -m gifmanager
```

Contributors want `requirements-dev.txt` instead; it pulls in the requirements file and adds
PyInstaller. `pip install -e .` installs the `gifmanager` and `gifmanager-qml` commands; without
it, run the interface with `python -m gifmanager` or `apps/gifmanager_qml.py`.

Use 3.12 for the virtual environment even though the package needs only 3.10: Pillow's pinned
wheel is built for 3.12 specifically, and a 3.14 interpreter from `PATH` fails with an `_imaging`
import error that never mentions the version. PySide6 itself ships a 3.10+ wheel, so it is the
Pillow pin that decides this. `make env` checks it first and tells you the fix.

`python -m gifmanager` and `gifmanager-qml` both start the QML interface. The plain `gifmanager`
command starts the older Qt Widgets shell, which is kept around for comparison and is not what
releases run.

Playback is the one optional part: `make native` (or `scripts/build-native.ps1` on Windows,
`scripts/build-native.sh` elsewhere) builds the Rust decoder. Without it the app still opens and
browses; GIF cards just stay on their first frame.

## Where your data lives

`emoji.db`, the `emojis/<group>/` files and `settings.json` sit together in one directory. Which
directory depends on how you started the program:

| How you run it | Windows | Linux | macOS |
|---|---|---|---|
| From source | `%APPDATA%\GIFManager` | `~/.local/share/GIFManager` | `~/Library/Application Support/GIFManager` |
| Packaged build | `data\` beside the executable | `data/` beside the executable | `data/` beside the executable |

A packaged build keeps the library next to its executable, and falls back to the per-user directory
in the row above when that place is read-only — an AppImage mount, a system-wide install. The
Windows installer defaults to `%LOCALAPPDATA%\Programs\GIFManager`, so its library lands in
`…\GIFManager\data`. Logs never move: `%LOCALAPPDATA%\GIFManager\logs` on Windows,
`~/.cache/GIFManager/logs` on Linux, `~/Library/Logs/GIFManager` on macOS.

`GIFMANAGER_DATA_DIR` overrides the library directory and leaves the logs where they are, which is
how you keep two profiles apart or run from a USB stick. A library in the per-user directory
survives uninstalling; one in the install folder goes when you delete the folder.

## Building the installers

```bash
make build-qml      # PyInstaller onedir bundle in dist/GIFManager
```

That is the QML front-end. `make build` builds the retired Qt Widgets bundle from a spec that
excludes Qt Quick, so it produces a working program without the interface this repository
documents.

The release workflow runs only when you trigger it: an installer on every push is noise, and one
run costs the better part of an hour. It reads the version from `gifmanager/__init__.py`, so an
artifact can never carry a number the code does not, and it builds one bundle per platform and
wraps that bundle into every format in the table above. Ticking `create_release` publishes a
draft release with all of them.

Pushing this working directory is not the same as publishing it: it holds a virtual environment,
Rust build output, PyInstaller output and a few stray test files, about 1.1 GB of things nobody
needs. `make-archive.bat` builds a clean zip from tracked files and drops the six things that do
not belong in an upload. Upload the contents of the zip.

## Working on it

```bash
make check      # environment, layering, style, translations, batch files, unit tests
make smoke      # the offscreen smoke suite; needs Qt installed
make run-qml    # run the interface from source
```

Pass your interpreter explicitly if the venv is not active: `make check PYTHON=.venv/Scripts/python.exe`
on Windows, `PYTHON=.venv/bin/python` elsewhere.

`make check` is not decoration, and every check refuses one specific class of mistake:

| Check | It refuses |
|---|---|
| `tools/check_environment.py` | a Pillow that cannot import; warns when the interpreter is not the 3.12 the wheels were verified on |
| `tools/check_layers.py` | a `core` module importing Qt, or front-end logic leaking downwards |
| `tools/check_style.py` | lines over 100 columns, tabs, trailing whitespace, a comment block with no Chinese in it |
| `tools/sync_language_keys.py` | a translation table missing a key another table has |
| `tools/check_batch_encoding.py` | a `.bat` that is not ASCII with CRLF endings |
| `make test` | a broken import or a lost row; 125 unit and integration tests, Qt offscreen |

CI runs the layering, style, translation and unit checks plus `tests/smoke_qml.py` before
anything is packaged. `make probe-services` is separate because it needs a real desktop: the
offscreen platform has no tray and no hotkey to register.

`make` is GNU Make; on Windows it needs MSYS2 or Git Bash, because the recipes use POSIX shell
syntax (`QT_QPA_PLATFORM=offscreen python …`), which `cmd.exe` cannot run. Every target is one
command in the `Makefile` you can run yourself; `check` and `smoke` just run the others in a row.

`docs/` holds the longer pieces: the layering and how the QML front-end is put together
(`ARCHITECTURE.md`, `QML_FRONTEND.md`), platform setup and troubleshooting (`RUNNING.md`), and
what is still missing (`COMPLETION_CHECKLIST.md`).

The interface speaks English and Simplified Chinese, switched at runtime under *Settings →
General → Language*. Translations are plain tables in `resources/language/`; to add one, copy
`en_US.json` to `<locale>.json`, translate the values and never the keys, then run
`python tools/sync_language_keys.py`. The file name is the locale the settings page offers, so a
new file is selectable immediately.

`CONTRIBUTING.md` has the comment, commit and pull-request conventions.

## License and credits

**MIT** — see [LICENSE](LICENSE). Use it, fork it, ship it.

HarmonyOS Sans SC ships in `resources/fonts/` in six weights, redistributed under its own font
licence; the licence text is not bundled, so add it before republishing the fonts in a fork. The
component set follows the ideas in [SWB-QML-UI](https://github.com/xxmzwf/SWB-QML-UI) (MIT) and
shadcn's look, ported to QML rather than linked, because PySide6 ships no Qt CMake package. The
interaction details — press feedback, interruptible motion, contrast as state, optical type —
come from Apple's *Designing Fluid Interfaces* and Emil Kowalski's writing on interface polish.

## Contributors

<p align="left">
  <a href="https://github.com/LwoSnow" title="LwoSnow">
    <img src="https://github.com/LwoSnow.png" alt="LwoSnow" width="48" height="48" style="border-radius:50%" />
  </a>
  <a href="https://github.com/Sunroin9" title="Sunroin9">
    <img src="https://github.com/Sunroin9.png" alt="Sunroin9" width="48" height="48" style="border-radius:50%" />
  </a>
</p>


**LwoSnow** **Sunroin9**