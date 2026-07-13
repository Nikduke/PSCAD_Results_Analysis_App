from __future__ import annotations

import ctypes
import sys
from importlib import resources

from PySide6 import QtGui, QtWidgets

from results_analysis_app.main_window import MainWindow
from results_analysis_app.models import AppSession


def _app_icon() -> QtGui.QIcon | None:
    try:
        icon_path = resources.files("results_analysis_app.assets").joinpath("mpe_app_icon.ico")
    except ModuleNotFoundError:
        return None
    if not icon_path.is_file():
        return None
    icon = QtGui.QIcon(str(icon_path))
    return icon if not icon.isNull() else None


def _configure_windows_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "loMPE.PSCADResultsAnalysis"
        )
    except Exception:
        return


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--smoke" in args:
        AppSession.default()
        return 0

    _configure_windows_identity()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("PSCAD Results Analysis")
    app.setOrganizationName("loMPE")
    icon = _app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    window = MainWindow()
    if icon is not None:
        window.setWindowIcon(icon)
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
