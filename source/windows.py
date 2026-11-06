from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def app_icon(size=128):
    pix = QPixmap(size, size)
    pix.fill(QColor("transparent"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor("transparent"))
    p.setBrush(QColor("#138679"))
    p.drawRoundedRect(1, 1, size - 2, size - 2, size * .23, size * .23)
    p.setPen(QColor("white"))
    font = QFont("Segoe UI", int(size * .43), QFont.Weight.Bold)
    p.setFont(font)
    p.drawText(pix.rect(), 0x84, "Z")
    p.setBrush(QColor("#a9ecce"))
    p.setPen(QColor("transparent"))
    p.drawEllipse(int(size * .73), int(size * .73), int(size * .12), int(size * .12))
    p.end()
    return QIcon(pix)


def startup_path():
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    return Path(shell.SpecialFolders("Startup")) / "ZTrans.lnk"


def set_startup(enabled: bool):
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    path = startup_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    shortcut = shell.CreateShortcut(str(path))
    if getattr(sys, "frozen", False):
        shortcut.TargetPath = sys.executable
        shortcut.Arguments = "--tray"
        shortcut.WorkingDirectory = str(Path(sys.executable).parent)
    else:
        shortcut.TargetPath = str(Path(sys.executable).with_name("pythonw.exe"))
        shortcut.Arguments = f'"{Path(__file__).with_name("app.py")}" --tray'
        shortcut.WorkingDirectory = str(Path(__file__).parent)
    shortcut.Description = "ZTrans · 本地优先的翻译工具"
    shortcut.Save()


class HotkeySignals(QObject):
    activated = Signal(int)


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self.signals = HotkeySignals()
        self.registered, self.failed = [], []
        for ident, modifiers, virtual_key, label in (
            (1, 0x4000, 0x70, "F1"),
            (3, 0x4003, ord("Z"), "Ctrl+Alt+Z"),
        ):
            # MOD_NOREPEAT avoids duplicate requests while a key is held down.
            if ctypes.windll.user32.RegisterHotKey(None, ident, modifiers, virtual_key):
                self.registered.append(ident)
            else:
                self.failed.append(label)

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.wParam in self.registered:
            self.signals.activated.emit(int(msg.wParam))
            return True, 0
        return False, 0

    def close(self):
        for ident in self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, ident)
        self.registered.clear()
