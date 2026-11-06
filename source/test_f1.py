"""Register F1 and verify native WM_HOTKEY dispatch without reading user text."""
import ctypes
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from windows import Hotkeys

app = QApplication([])
hotkeys = Hotkeys()
assert 1 in hotkeys.registered, "F1 is occupied by another app"
app.installNativeEventFilter(hotkeys)
events = []
hotkeys.signals.activated.connect(events.append)
try:
    thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
    QTimer.singleShot(100, lambda: ctypes.windll.user32.PostThreadMessageW(thread_id, 0x0312, 1, 0x00700000))
    QTimer.singleShot(500, app.quit)
    app.exec()
    assert events == [1], events
    print("Global F1 registration and native event dispatch: passed")
finally:
    hotkeys.close()
