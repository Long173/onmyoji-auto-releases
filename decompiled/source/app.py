"""Entry point for Onmyoji Tool — the task centre.

Run with ``--verbose`` for debug-level logging (every click and match score),
or ``--wiki`` to open straight into the wiki window.
"""
from __future__ import annotations

import argparse
import logging
import sys

from PyQt5 import QtCore, QtWidgets

import fonts
import logging_setup
import paths
import theme

logger = logging.getLogger(__name__)


def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="onmyoji-tool", description=theme.APP_NAME)
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log every click and template match score",
    )
    parser.add_argument(
        "--wiki",
        action="store_true",
        help="Open straight onto the wiki page",
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Start in the system tray with no window (used by Windows startup)",
    )
    return parser.parse_args(argv)


# Left at the old name on purpose. Windows keys pinned taskbar shortcuts and
# notification history to this id; changing it unpins the app and orphans any
# notices already delivered. It is never shown to anyone.
APP_USER_MODEL_ID = "OnmyojiAuto.RealmRaid"


def _claim_taskbar_identity() -> None:
    """Give Windows an explicit app id.

    Without it the shell treats the process as generic Python, so notifications
    are attributed to "python" and the taskbar groups the app with any other
    script. Harmless if the call is unavailable.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception as exc:  # noqa: BLE001 - cosmetic only
        logger.debug("Could not set the app user model id: %s", exc)


def apply_window_policy(app) -> None:
    """This app outlives its windows on purpose.

    It hides to the tray, and from there it has no window at all until somebody
    asks for one.

    Qt's default is to quit when the last window closes, and this was left on —
    on the theory that the tray icon would otherwise hold the process open. It
    would not: a QSystemTrayIcon is not a window and does not count towards this
    at all. What the default actually did was end the app when the last *window*
    closed, and once a screenshot could be taken by a hotkey while the dashboard
    was hidden, that last window was the preview. Closing the preview took the
    whole app with it, tray icon and all.

    So quitting is explicit instead — see :meth:`ui.auto_window.AutoWindow.closeEvent`,
    the one place that knows a close was a real close.
    """
    app.setQuitOnLastWindowClosed(False)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging_setup.configure(verbose=args.verbose)
    paths.ensure_cache_dirs()
    logger.info("%s v%s starting", theme.APP_NAME, theme.APP_VERSION)
    # Logged every launch: in a packaged build these paths are the first thing
    # worth knowing when something cannot be found.
    logger.info("Paths: %s", paths.describe())

    # Must be set before the QApplication exists. The design is specified in
    # pixels, so scaling is what keeps it honest on high-DPI displays.
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    _claim_taskbar_identity()

    # Qt requires its application object on the main thread. The 1.0 build
    # started it inside a worker thread, which Qt warned about on every launch.
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(theme.APP_NAME)
    fonts.load()
    app.setStyleSheet(theme.app_stylesheet())

    from ui.app_icon import build_icon

    app.setWindowIcon(build_icon())
    apply_window_policy(app)

    # One copy at a time. Checked after the QApplication exists — the claim is
    # made over a Qt local socket — and before the window is built, so a second
    # launch costs a moment rather than a whole dashboard.
    import single_instance

    only = single_instance.SingleInstance(APP_USER_MODEL_ID, app)
    if not only.claim():
        logger.info("Another copy is running; showing that one and exiting")
        return 0

    from ui.auto_window import AutoWindow

    window = AutoWindow()
    # A later launch asks for the window rather than starting another copy. The
    # same slot the tray icon uses, because it is the same request.
    only.woken.connect(window.show_from_launch)
    if args.tray:
        # Started by Windows at sign-in. The tray icon exists as soon as the
        # window is built, so there is nothing to show and nothing to do; the
        # icon is how the user gets to it. --wiki is ignored on purpose: it asks
        # for a page to be opened, which is a request for a window.
        logger.info("Starting in the tray with no window")
    else:
        window.show()
        if args.wiki:
            # The wiki is a page in this window now, not a window of its own.
            window.open_wiki()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
