from __future__ import annotations

import traceback

from PySide6 import QtCore


class OperationCancelled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Operation stopped by user.")


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def throw_if_cancelled(self) -> None:
        if self._cancelled:
            raise OperationCancelled()


class BackgroundTask(QtCore.QThread):
    message = QtCore.Signal(str)
    succeeded = QtCore.Signal(object)
    cancelled = QtCore.Signal()
    failed = QtCore.Signal(str, str)

    def __init__(self, work, cancel_token: CancelToken, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work
        self.cancel_token = cancel_token

    def run(self) -> None:
        try:
            self.succeeded.emit(self._work(self.message.emit, self.cancel_token))
        except OperationCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
