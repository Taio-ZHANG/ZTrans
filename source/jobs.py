import threading
from PySide6.QtCore import QThread, Signal
from core import Cancelled, UserError


class Job(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, str)
    token = Signal(str)
    piece = Signal(str, str)
    cancelled = Signal()

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            result = self.function(self)
            if self.cancel.is_set():
                raise Cancelled()
            self.result.emit(result)
        except Cancelled:
            self.cancelled.emit()
        except UserError as e:
            self.error.emit(str(e))
        except Exception as e:
            # Deliberately omit arbitrary exception bodies: some libraries include document text / URLs.
            self.error.emit(f"处理失败（{type(e).__name__}）。请确认文件未损坏、服务可用后重试。")
