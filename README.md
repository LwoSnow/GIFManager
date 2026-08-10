# GIFManager

A lightweight sticker (emoji/GIF) manager for Windows, built with **PySide6 (Qt 6)**.
It mimics the look and feel of the QQ sticker panel: browse your sticker packs,
manage them in groups, and send them to any chat window in one click.

**[简体中文](README.zh-CN.md)**

---

## Features

- **Borderless dark and bright UI** — a clean frameless window with a draggable toolbar,
  Win11 rounded corners, dark/light themes, and a modern flat look.
- **Bottom group tab bar** Personalized grouping of bottom expressions.
  The built-in **"All"** tab shows every sticker across groups; a **"Default"** group is
  always available for quick imports.
- **Two group types**
  - *Image groups* — store GIF/PNG/JPG/WebP/BMP stickers.
  - *Text groups* — store pure text (kaomoji / Emoticon). Paste text with **Ctrl+V**
    to batch-save each line as a sticker.
- **Import method**
  - `Import GIF` button → *Import from folder* (recursive scan) or *Import from files*
    (multi-select).
  - Drag & drop files directly onto the window to batch-import into the current group
    (or the Default group when "All" is active).
  - Duplicate files in the same group are skipped automatically (MD5 content hash);
    the same file may exist in several groups as a multi-tag.
- **Send to chat** — click a sticker to copy it to the clipboard:
  - **File path mode** (default, recommended) — paste directly in QQ / WeChat.
  - **Image data mode** — copies the raw image pixels for apps that need image data.
- **Text stickers** — compact text cards instead of image thumbnails; preview length is
  configurable (single-line / multi-line limits).
- **Search** — real-time filtering by file name / text content.
- **Rich interactions**
  - Right-click a sticker: Send, Rename/Edit, Move to group, Delete.
  - In the "All" view, deleting a duplicated sticker opens a dialog to pick which group
    copies to remove.
  - Drag stickers to reorder within a column; drag group tabs to reorder groups;
    right-click a group to rename/delete (built-ins are protected).
  - **One-click rearrange** — evenly distribute stickers into columns by window width.
  - Hover a GIF to play its animation (visibility-driven playback, never plays
    off-screen GIFs).
- **System tray resident** — closing hides to the tray; left-click the tray icon (or
  press the global hotkey) to toggle visibility, tray menu to quit.
- **Global hotkey** — default **F10** to show/hide; supports key combinations
  (e.g. `Ctrl+Shift+1`), **mouse side buttons** (XButton1/XButton2), and ESC to clear.
- **Memory system** — window size/position, the last selected group (toggleable),
  send mode, theme, language, and hotkey persist across restarts.
- **Performance built-in** — lazy card creation (only visible cards are built),
  thread-pool thumbnail decoding with a 64 MB pixmap cache, configurable CPU core count,
  and column-merging on window resize so the layout never breaks.
- **Logging** — timestamped logs under `logs/`, crash-safe (flushed per line), with a
  one-click "Clear logs" action in Settings.

---

## AI Disclosure

This project used AI-assisted development tools:

- **Tool**: DeepSeek v4 flash 0731
- **Role**: Code generation, implementation assistance
- **Human oversight**: All code was reviewed, tested, and integrated by the project maintainer

---
## UI Layout

```
+------------------------------------------------------------------+
| [ 🔍 Search stickers...            ] [Import GIF▾] [+Text] [⚙]  |  ← draggable toolbar
+------------------------------------------------------------------+
|                                                                  |
|   [GIF1]   [GIF2]   [GIF3]   [GIF4]    ← image stickers (grid,   |
|   [GIF5]   [GIF6]   ...                 masonry columns)         |
|   ┌──────────────────┐                                            |
|   │ (｡•̀ᴗ-)✧       │  ← text stickers (compact cards)         |
|   └──────────────────┘                                            |
|                                                                  |
+------------------------------------------------------------------+
|  All | Default | Memes | Pets | Kaomoji |  ＋                    |  ← bottom group tabs
+------------------------------------------------------------------+
|   Default · 128 stickers  |  256 in total                        |  ← status bar
+------------------------------------------------------------------+
```

---

## Requirements

- **Windows 10 / 11** (global hotkey, tray, rounded corners, and autostart are
  Windows-specific; the app otherwise runs on other platforms)
- **Python 3.10+** (Program version is Python 3.12.0)
- **PySide6 ≥ 6.5**

The only third-party dependency is PySide6.

---

## Installation & Run

```bash
# 1. Create a virtual environment (optional but recommended)
python -m venv .venv

# 2. Activate it (Windows)
.venv\Scripts\activate

# 3. Install the dependency
pip install PySide6

# 4. Run
python main.py
```

Or, if you already have the `.venv` shipped with the project:

```bash
.venv\Scripts\python.exe main.py
```

On first launch the app creates `data/emoji.db` (SQLite, WAL mode) and
`data/emojis/<group>/` folders automatically.

---

## Usage Guide

### Importing stickers

| Action | Result |
| --- | --- |
| Click **Import GIF** → *From files* | Multi-select GIF/PNG/JPG/WebP/BMP, copied into the current group |
| Click **Import GIF** → *From folder* | Recursively scans a folder for supported images |
| Drag & drop files onto the window | Batch import into the current group (or Default when "All" is active) |
| Ctrl+V while a **text group** is selected | Each line of the clipboard becomes a text sticker |

### Groups

- The **All** tab is built-in and cannot be deleted/renamed; it shows every sticker,
  folding cross-group duplicates into one card.
- The **Default** group is the fallback target when importing while "All" is selected.
- Click **＋** at the right end of the tab bar to create a new **image group** or
  **text group**.
- Drag tabs to reorder; right-click a tab to rename or delete (built-ins protected).

### Sending stickers

1. Click a sticker — it is copied to the clipboard immediately (status bar confirms).
2. Switch the send mode in **Settings → Send**: *Copy file path* (recommended) or
   *Copy image data*.
3. Paste in QQ / WeChat / any chat window.

> Tip: QQ accepts pasted file paths directly; WeChat also pastes the image.
> If a target app doesn't accept a pasted path, switch to *Copy image data*.

### Keyboard shortcuts

- **F10** (default, configurable): show/hide the window from anywhere.
- **ESC** while capturing a hotkey: clear the hotkey (disabled).
- Right-click inside the search box shows a localized context menu
  (Undo/Redo/Cut/Copy/Paste/Delete/Select All).

---

## Data Storage & Backup

```
GIFManager/
├── main.py                     # entry point
├── app/                        # application code
│   ├── main_window.py          # main window, tray, hotkey, drag & drop
│   ├── models/
│   │   ├── data_manager.py     # SQLite + file management, clipboard
│   │   ├── lang_manager.py     # i18n loader (language/*.json)
│   │   └── logger.py           # crash-safe logging
│   ├── widgets/                # group tabs, sticker grid, settings, hotkey, ...
│   └── theme/                  # dark / light QSS
├── language/                   # translation files (zh_CN.json, en_US.json, ...)
├── data/
│   ├── emoji.db                # SQLite database (groups, emojis, columns)
│   └── emojis/<group>/         # actual sticker files, one folder per image group
├── logs/                       # timestamped session logs (auto-created)
└── icon.ico                    # app & tray icon
```

**To back up your stickers, copy the whole `data/` folder** — it contains both the
database and all sticker files. Sticker files are renamed to random 8-hex names, so
group membership is tracked in `emoji.db`.

### SQLite schema (summary)

- `groups(id, name, type, sort_order, is_builtin, created_at)` — `type` is
  `'image'` or `'text'`.
- `emojis(id, group_id, filename, text_content, original_name, content_hash,
  sort_order, col_index, user_sorted, created_at)` — `content_hash` enables
  same-group deduplication and cross-group folding in the "All" view.

---

## Settings

| Category | Setting | Notes |
| --- | --- | --- |
| General | Language | `zh_CN` / `en_US` (auto-detected from `language/*.json`), applied instantly |
| General | Restore last group on startup | On by default |
| General | Launch at startup | Windows registry `Run` key |
| General | Always on top | Window stays above others |
| General | Theme | Dark (default) / Light |
| General | Clear logs | Deletes all `logs/*.log` |
| Send | Send mode | File path (recommended) / Image data |
| Hotkey | Global hotkey | Default F10; supports combinations, mouse side buttons; ESC clears |
| Text | Preview limits | Single-line / multi-line char caps for text sticker cards |
| Performance | Thread count | CPU cores for thumbnails & batch import (0 = auto) |
| About | — | Version, Agreement |

---

## Language

Translations live in `language/<code>.json`. The app scans this folder and lists every
available language in **Settings → Language**. Adding a new language is just a matter of
creating another JSON file with the same keys as `zh_CN.json`.

---

## Performance Design

- **Lazy rendering** — only stickers inside the visible area (±300 px buffer) are
  materialized as widgets; the "All" view builds all cards at once but stays fluid
  thanks to the pixmap cache.
- **Thread-pool thumbnails** — decoding/scaling runs on a global `QThreadPool`
  (min(cores−1, 8) by default); results are cached in a 64 MB `QPixmapCache`.
- **Visibility-driven GIF playback** — only GIFs in the viewport (±150 px) play, capped
  at `threads × 2` simultaneous animations; others show their first frame.
- **Column merging** — when the window shrinks, overflowing masonry columns merge into
  earlier ones (150 ms debounce), so cards never overlap.
- **Batch import** — hashing + file copying are parallelized; DB inserts run in a single
  transaction with deduplication.

---

## Troubleshooting

- **Hotkey registration failed** — another program already owns that key combination.
  Pick another hotkey in Settings.
- **Pasting a "file path" doesn't work in some app** — switch to *Copy image data* in
  Settings → Send.
- **Import seems to skip files** — files identical to existing ones in the same group
  are skipped as duplicates on purpose.
- **GIF doesn't animate** — playback is limited to visible GIFs for performance; scroll
  it into view and it will start playing.

---

## License

[MIT](LICENSE) © 2026 LwoSnow
