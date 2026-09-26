"""Make bundled PySide6 and shiboken6 DLLs discoverable on Windows."""

from __future__ import annotations

import os
import sys
import ctypes


if sys.platform == "win32" and hasattr(sys, "_MEIPASS"):
    _dll_directory_handles = []
    _dll_directories = [sys._MEIPASS]
    try:
        _dll_directory_handles.append(os.add_dll_directory(sys._MEIPASS))
    except (OSError, AttributeError):
        pass
    os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ.get("PATH", "")
    for _relative_path in ("PySide6", "shiboken6"):
        _dll_directory = os.path.join(sys._MEIPASS, _relative_path)
        if not os.path.isdir(_dll_directory):
            continue
        _dll_directories.append(_dll_directory)
        try:
            _dll_directory_handles.append(os.add_dll_directory(_dll_directory))
        except (OSError, AttributeError):
            pass
        os.environ["PATH"] = (
            _dll_directory
            + os.pathsep
            + os.environ.get("PATH", "")
        )

    # PySide6's extension modules and Qt DLLs live in different bundled
    # subdirectories.  Explicitly preload the bundled copies so Windows does
    # not bind an identically named DLL from another Qt installation first.
    for _dll_name in (
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "shiboken6.abi3.dll",
        "pyside6.abi3.dll",
    ):
        for _dll_directory in _dll_directories:
            _dll_path = os.path.join(_dll_directory, _dll_name)
            if not os.path.isfile(_dll_path):
                continue
            try:
                ctypes.WinDLL(_dll_path)
            except OSError:
                pass
            break
