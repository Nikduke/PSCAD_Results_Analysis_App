from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys


try:
    import pywintypes
except ImportError:
    EXCEL_AUTOMATION_ERRORS = (AttributeError, OSError, RuntimeError, TypeError, ValueError)
else:
    EXCEL_AUTOMATION_ERRORS = (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        pywintypes.com_error,
    )


@contextmanager
def excel_app():
    if sys.platform != "win32":
        raise RuntimeError("Microsoft Excel automation requires Windows.")
    try:
        import pythoncom
        import win32com.client as win32
    except ImportError as exc:
        raise RuntimeError("pywin32 is required for Microsoft Excel automation.") from exc

    pythoncom.CoInitialize()
    excel = None
    try:
        excel = win32.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        try:
            excel.ScreenUpdating = False
            excel.EnableEvents = False
            excel.AskToUpdateLinks = False
        except EXCEL_AUTOMATION_ERRORS:
            pass
        yield excel
    finally:
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()


def autofit_workbook(excel, path: str | Path) -> None:
    """Apply Excel's native AutoFit to every used column in a workbook."""
    workbook = excel.Workbooks.Open(
        str(Path(path).resolve()),
        UpdateLinks=0,
        ReadOnly=False,
    )
    try:
        for worksheet in workbook.Worksheets:
            worksheet.UsedRange.Columns.AutoFit()
        workbook.Save()
    finally:
        try:
            workbook.Close(SaveChanges=True)
        except EXCEL_AUTOMATION_ERRORS:
            pass
