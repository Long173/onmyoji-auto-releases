# Legacy source (archive — not used at runtime)

The original `uncompyle6` output from `Tool Auto.exe`, kept because it is the
only surviving copy: the executable it came from was deleted, and this project
is not under version control.

Nothing here is imported. The current app lives in `../source/`.

| Legacy file      | Replaced by                                                |
| ---------------- | ---------------------------------------------------------- |
| `GUI2.py`        | `app.py`, `main_window.py`, `widgets.py`, `theme.py`        |
| `realm.py`       | `realm_raid.py`, `geometry.py`, `paths.py`                  |
| `GameControl.py` | `game_control.py`                                           |
| `Util.py`        | `logging_setup.py`                                          |
| `ThreadGame.py`  | removed — the lock it exposed was constructed but never used |

Delete this folder once you are confident the rewrite behaves correctly.
