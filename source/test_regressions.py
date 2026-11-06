"""Regression checks use synthetic content and never read the user's clipboard."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QDialog

import app as zapp
from core import Settings, load_settings
from documents import import_file


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(zapp, "load_settings", lambda: Settings())
    monkeypatch.setattr(zapp, "save_settings", lambda _: None)
    window = zapp.MainWindow(register_hotkeys=False, window_state_path=tmp_path / "window.json")
    yield window
    window.compact.hide()
    window.hide()
    window.deleteLater()
    application.processEvents()


def test_repair_can_be_undone_in_visible_editor(window, monkeypatch):
    original = "Molecular dynamics\nreveals solvation structure."
    window.source.setPlainText(original)
    monkeypatch.setattr(QDialog, "exec", lambda _: QDialog.DialogCode.Accepted)
    window.preview_repair()
    assert window.compact.source.toPlainText() != original
    window.compact.source.undo()
    assert window.compact.source.toPlainText() == original
    assert window.source.toPlainText() == original


@pytest.mark.parametrize("encoding", ["gb18030", "utf-16", "utf-8-sig"])
def test_chinese_text_encoding(tmp_path, encoding):
    path = tmp_path / "sample.txt"
    text = "电解液的溶剂化结构决定离子电导率。"
    path.write_bytes(text.encode(encoding))
    assert import_file(str(path)).text == text


@pytest.mark.parametrize("data", [None, ["provider"], {"ollama_url": "broken", "font_size": -999}, {"provider": "unknown", "target": "bad"}])
def test_damaged_settings_recover(tmp_path, data):
    (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    cfg = load_settings(tmp_path)
    assert cfg.base_url.startswith("http")
    assert 11 <= cfg.font_size <= 22
    assert cfg.provider in ("api", "ollama")
    assert cfg.target == Settings().target


@pytest.fixture
def capture_env(window, monkeypatch):
    scheduled, sent, translated = [], [], []
    state = {"foreground": 4321, "sequence": 1, "held": False}
    user32 = SimpleNamespace(
        GetForegroundWindow=lambda: state["foreground"],
        GetAsyncKeyState=lambda key: 0x8000 if state["held"] else 0,
        GetClipboardSequenceNumber=lambda: state["sequence"],
        keybd_event=lambda *args: sent.append(args),
    )
    monkeypatch.setattr(zapp, "ctypes", SimpleNamespace(windll=SimpleNamespace(user32=user32)))
    monkeypatch.setattr(zapp, "QTimer", SimpleNamespace(singleShot=lambda ms, fn: scheduled.append(fn)))
    monkeypatch.setattr(window, "translate_clipboard", lambda: translated.append(True))
    monkeypatch.setattr(window, "show_preferred", lambda **kwargs: None)
    return state, scheduled, sent, translated


def test_rapid_f1_does_not_overlap(window, capture_env):
    state, scheduled, sent, translated = capture_env
    window.on_hotkey(1)
    window.on_hotkey(1)
    assert len(sent) == 4  # Exactly one Ctrl+C press/release sequence.
    state["sequence"] += 1
    scheduled.pop(0)()
    assert translated == [True]
    window.on_hotkey(1)
    assert len(sent) == 8  # The next independent request still works.


def test_focus_change_before_copy_aborts(window, capture_env):
    state, scheduled, sent, translated = capture_env
    state["held"] = True
    window.on_hotkey(1)
    state.update(held=False, foreground=9999)
    scheduled.pop(0)()
    assert not sent and not translated


def test_focus_change_while_copy_pending_aborts(window, capture_env):
    state, scheduled, sent, translated = capture_env
    window.on_hotkey(1)
    state.update(sequence=2, foreground=9999)
    scheduled.pop(0)()
    assert not translated


def test_old_clipboard_never_translated(window, capture_env):
    state, scheduled, sent, translated = capture_env
    window.on_hotkey(1)
    while scheduled:
        scheduled.pop(0)()
    assert not translated


def test_modal_dialog_blocks_f1(window, capture_env):
    state, scheduled, sent, translated = capture_env
    dialog = QDialog(window.compact)
    dialog.setModal(True)
    dialog.show()
    QApplication.processEvents()
    try:
        window.on_hotkey(1)
        assert not sent
    finally:
        dialog.hide()
