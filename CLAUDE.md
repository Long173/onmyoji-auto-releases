# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Windows-only PyQt5 desktop app that automates the PC game **Onmyoji** by
screen-scraping game windows and posting synthetic clicks to them, plus an
offline Vietnamese wiki (Thức thần / Ngự hồn / Hiệu ứng). Bot workers drive
several game windows at once in the background — the real cursor never moves
and the game window never needs focus.

Source lives in `decompiled/source/`, not at the repo root. `decompiled/_legacy/`
is the original decompiled build kept for reference — never edit or import it.

`docs/` (Vietnamese) is the real design documentation, and it is unusually
good — read it before changing anything non-trivial. `docs/ghi-chu-ky-thuat.md`
records constraints that were expensive to find and are invisible in the code;
`docs/kien-truc.md` explains the task registry; `docs/dong-goi-va-phat-hanh.md`
covers packaging and the self-update mechanism. `README.md` is the short
user-facing front page. All docs and user-facing strings are Vietnamese; code,
comments and docstrings are English.

## Commands

```bash
pip install -r requirements.txt

python decompiled/source/app.py            # run (add -v for click/match logging)
python decompiled/source/app.py --wiki     # open straight onto the wiki page
python decompiled/source/app.py --tray     # start hidden in the tray

python -m pytest tests -q                  # full suite; needs no game and no network
python -m pytest tests/test_realm_raid.py -q
python -m pytest tests/test_realm_raid.py::test_name -q

pyinstaller onmyoji_auto.spec --noconfirm  # -> dist/Onmyoji Tool/  (one-dir, ~245 MB)
python tools/export_icon.py                # regenerate assets/icon.ico first if missing
python tools/publish_release.py 3.16 --notes "..." [--upload]
```

On Windows, `Launch.vbs` runs without a console; `Launch (Show Log).bat` runs
with `-v` and a visible log. Logs go to `logs/onmyoji_auto.log`.

Tests import from `decompiled/source` via `tests/conftest.py`, which puts it on
`sys.path` and forces `QT_QPA_PLATFORM=offscreen`. The app itself only runs on
Windows (`pywin32`, `PrintWindow`, `PostMessage`), so on macOS/Linux expect
import failures for anything touching `game_control`.

## Architecture

### The task registry is the extension point

`decompiled/source/tasks.py` declares every automation as a frozen `TaskSpec`
(id, name, summary, `fields`, `build`). Everything downstream — sidebar rows,
the per-task page, generated config controls, settings persistence, start/stop
plumbing — is derived from this registry. **Adding an automation means adding a
`TaskSpec` plus a worker class; no UI file should need to change.** A spec with
`build=None` is *declared but unimplemented*: the UI lists it and refuses to
start it, showing its `todo`. `tasks.py` must stay Qt-free.

A worker is a duck-typed protocol, not a base class requirement (though
`task_worker.TaskWorker` implements the shared half): `start/stop/join/is_alive`,
`pause/resume/is_paused`, `elapsed_seconds`, `latest_frame()`, and optionally
`progress` (only when a `progress_label` is declared and the count is
trustworthy). `realm_raid.RealmRaidWorker` is the reference implementation.

Settings come in three layers, merged narrowest-last by
`SessionManager.config_for`: `tasks.APP_FIELDS` (app-wide, F9 dialog) →
`TaskSpec.fields` → `Field(per_window=True)` values stored on the session. A
task key must never shadow an app key — a test enforces this. Builders just read
`config[key]`.

### Windows, sessions, workers

`auto/window_scanner.py` enumerates game windows → `auto/session.py` holds one
window + its selected task + its live worker → `auto/manager.py` owns all
sessions and the shared per-task config. One window runs exactly one task (the
old per-window queue was removed). Task selection is remembered **by window
title**, because HWNDs change every launch. `auto/` is deliberately Qt-free so it
is testable headless.

`ui/auto_window.py` is the single main window; wiki pages and task pages are
views inside it, not separate windows.

### Task loops

Each loop is a `_step()` that runs a fixed, ordered list of handlers against one
captured frame and returns as soon as one matches — modal/blocking screens
first (invites, dialogs, result panels) because they draw *over* a board that
still template-matches straight through them, then the productive handlers.
Order in those lists encodes real bugs; don't reshuffle it casually.
`wanted_invite.py` is shared across all loops because a co-op invite dialog
blocks any task.

### Capture and input (`game_control.py`, `dpi.py`, `geometry.py`)

- Capture is `PrintWindow(PW_RENDERFULLCONTENT)`, **not** `BitBlt` — BitBlt
  returns a stale frame on DirectX surfaces.
- Clicks are `PostMessage(WM_LBUTTON*)` — no cursor movement, no focus.
- **Every measurement, capture and click must run inside `dpi.game_space()`**
  (a thread-local DPI-unaware scope). The game is DPI-unaware; mixing its
  coordinate space with the aware one silently produces 0.91 false matches
  against empty background and clicks that land nowhere. There is a test that
  asserts clicks are posted from an unaware thread — it exists because this
  failure is invisible in code review.
- Read images through `game_control.read_image` (bytes → `cv2.imdecode`);
  `cv2.imread` returns `None` for non-ASCII paths, and this app usually lives
  under a path like `陰陽師Onmyoji`.
- One frame is captured per scan pass and cached; the cache is invalidated after
  every click and every wait, so a template is never matched against a
  pre-click frame.
- Templates in `screenshots/<Task>/` are captured at `geometry.REFERENCE_CLIENT_SIZE`
  (1122×633 **client**, not outer). `Geometry` scales fixed coordinates but
  `cv2.matchTemplate` does not scale templates, so off-reference client sizes
  degrade detection. Window resizing measures each window's own frame — border
  thickness is not a constant across DPI settings.

### Paths, packaging, updates

`paths.py` splits `BUNDLE_ROOT` (read-only; `sys._MEIPASS` when frozen) from
`APP_ROOT` (writable; the folder holding the .exe — logs, `cache/`, `.env`).
In a checkout the two are the same, so path bugs of this kind only surface after
packaging. Build is deliberately **one-dir, no UPX** (one-file extraction to
`%TEMP%\_MEIxxxxxx` caused DLL-load failures; UPX triggers antivirus).

`theme.APP_VERSION` is the single source of truth for the version — the spec
file reads it out of `theme.py`. Release flow: bump `APP_VERSION` → build →
`tools/publish_release.py`. Two manifests ship with every release:
`latest-v2.json` (current, points at the .zip) and `latest.json`, permanently
frozen at 3.0 so pre-3.1 one-file installs don't download a .zip, rename it
`.exe`, and destroy themselves. Don't "fix" `latest.json`.

Self-update hands off to a PowerShell script (not `.bat` — cmd mishandles
non-ASCII paths) that backs each replaced entry into `.update-backup` and rolls
back on failure, leaving `logs/ cache/ .env wiki/` untouched.

### Wiki

`wiki/repository.py` layers offline data → `cache/wiki/` (synced) → Supabase
(PostgREST over stdlib `urllib`, no client package). Data is read from the
sibling checkout `../onmyoji_wiki/assets/data` in development, or from the
bundled copy when frozen. `sync()` **backfills only** — a field the server
leaves empty is filled from bundled data; a field the server has is never
overwritten. The `image` field has two spellings (`assets/images/souls/x.webp`
from the Flutter JSON vs `souls/x.webp` from the Supabase bucket) and
`ImageResolver.local_path` must keep trying both.

### UI conventions

- Build layouts with `ui.primitives.vbox()` / `hbox()` — a bare `QVBoxLayout()`
  carries a 9px default margin that breaks the design spacing.
- Design tokens (Classical theme: dark ground, brass accent, Cormorant
  Garamond + Lora + IBM Plex Mono) live in `theme.py`; fonts in `assets/fonts`
  are static instances flattened with fonttools because Qt5 cannot use variable
  fonts.
- The app outlives its windows on purpose (`setQuitOnLastWindowClosed(False)`);
  the only real quit path is `AutoWindow.closeEvent`.
- Open QSettings only through `app_settings.open_store` so tests can redirect it.
  Registry-backed QSettings returns the *string* `'false'` for booleans — use
  `tasks.as_bool`.

## Testing

`tests/conftest.py` carries the shared seams: `isolated_settings` (autouse,
per-test settings file), `dashboard` (a real `AutoWindow` with fake game
windows and every implemented worker swapped for `SpyWorker`), `bare_control()`
(a `GameControl` with no window behind it — anything added to
`GameControl.__init__` belongs here too), `quiet_dialogs`, `instant_background`.

`STUBBED_WORKERS` in conftest must list every task with a `build`; a guard test
compares the two sets. Real workers in a UI test call back into Qt from their
own thread and crash the run rather than fail it.

## Working notes

- Worker shutdown is cooperative (`threading.Event`), never injected
  `SystemExit` — that could land mid-GDI call and leak handles.
- `tools/` holds the template/data pipeline: `record_screens.py` (capture a task's
  distinct screens), `crop_region.py` (cut a template), `score_template.py`
  (score it before trusting it), `collect_figures.py`/`cluster_figures.py`/
  `promote_group.py`/`pack_library.py` (build the Demon Parade rarity library,
  which identifies shikigami by hue/saturation histogram, not shape).
- `decompiled/source/contact.py` is the single place contact details are
  declared; they surface in Settings and in every GitHub release body, and both
  places render nothing when left empty.
