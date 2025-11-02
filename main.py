from __future__ import annotations
import sys, os, traceback

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon

# Let you run from project root without installing as a package
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# ---- Global crash catcher so the app shows a dialog instead of dying ----
def _excepthook(exc_type, exc, tb):
    err = "".join(traceback.format_exception(exc_type, exc, tb))
    app = QApplication.instance()
    if app is None:
        # If Qt isn't ready yet, print to console (safe during early import failures)
        print(err, file=sys.stderr)
        return
    try:
        QMessageBox.critical(None, "Unhandled Error", err)
    except Exception:
        print(err, file=sys.stderr)

sys.excepthook = _excepthook
# ------------------------------------------------------------------------

if __name__ == "__main__":
    # Create QApplication first (prevents accidental widget creation during imports).
    app = QApplication(sys.argv)

    # Help Windows taskbar use your icon instead of a generic one.
    try:
        import ctypes  # noqa: E402
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ProtoBuffers.LiesOfP.SaveEditor"
        )
    except Exception:
        pass

    # Set the application icon (taskbar/dock).
    from app.utils.resources import find_app_icon  # noqa: E402
    ico_path = find_app_icon()
    if ico_path:
        app.setWindowIcon(QIcon(ico_path))

    # Import MainWindow after QApplication exists.
    from app.ui.main_window import MainWindow  # noqa: E402

    w = MainWindow()
    w.show()
    sys.exit(app.exec())
