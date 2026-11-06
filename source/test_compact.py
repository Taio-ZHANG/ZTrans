"""Synthetic-content compact-window integration tests, runnable in the EXE."""
from __future__ import annotations

import ctypes
import json
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from compact import WindowState, load_window_state, place_rect, save_window_state


def run_compact_checks(application, directory):
    directory.mkdir(parents=True, exist_ok=True)
    report = {}
    window = editor = None
    try:
        import app as zapp
        from core import Settings
        zapp.load_settings = lambda: Settings()
        zapp.save_settings = lambda value: None
        state_path = directory / "window-test.json"
        save_window_state(WindowState(), state_path)
        # Placement must work for negative origins, disconnected screens and oversized saved windows.
        for area in [QRect(-1504, -806, 1003, 1456), QRect(0, 0, 1280, 720), QRect(1920, -1080, 1920, 1080)]:
            for state in [WindowState(), WindowState(x=99999, y=99999, width=9999, height=9999), WindowState(x=12, y=30, width=390, height=480)]:
                assert area.contains(place_rect(area, state))
        report["placement_clamps"] = "passed"
        window = zapp.MainWindow(register_hotkeys=False, window_state_path=state_path)
        small = window.compact
        small.persist = True
        window.show_compact()
        QTest.qWait(150)
        screen = small.selected_screen()
        assert screen.availableGeometry().contains(small.geometry())
        if len(application.screens()) > 1:
            assert screen != application.primaryScreen()
        assert not window.isVisible()
        assert small.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        report["secondary_screen"] = screen.name()
        original = "Molecular dynamics simulations reveal the solvation structure of sodium ions."
        translated = "分子动力学模拟揭示了钠离子的溶剂化结构。"
        window.source.setPlainText(original)
        window.result.setPlainText(translated)
        assert small.result.toPlainText() == translated
        small.source_toggle.setChecked(True)
        small.source.insertPlainText("More text. ")
        assert "More text. " in window.source.toPlainText()
        small.source_toggle.setChecked(False)
        small.target_lang.setCurrentText("英语")
        assert window.target_lang.currentText() == "英语"
        window.target_lang.setCurrentText("简体中文")
        assert small.target_lang.currentText() == "简体中文"
        report["shared_documents_languages"] = "passed"
        small.move(small.pos() + QPoint(-36, 42))
        small.resize(450, 580)
        QTest.qWait(500)
        saved = load_window_state(state_path)
        assert saved.width == 450 and saved.height == 580
        assert saved.screen_name == screen.name()
        saved_geometry = small.geometry()
        small.hide()
        small.positioned = False
        small.show_compact()
        QTest.qWait(100)
        assert small.geometry() == saved_geometry
        report["geometry_persistence"] = "passed"
        small.pin.click()
        QTest.qWait(30)
        assert not small.state.pinned
        assert not small.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        small.pin.click()
        QTest.qWait(30)
        assert small.state.pinned
        report["pin_toggle"] = "passed"
        window.show_window()
        QTest.qWait(30)
        assert not window.isVisible() and small.isVisible()
        assert window.result.toPlainText() == translated
        small.hide()
        # A real separate edit window represents the user's foreground application.
        editor = QPlainTextEdit("Synthetic focus test. No user clipboard is read.")
        editor.setWindowTitle("ZTrans focus verification")
        editor.resize(430, 160)
        editor.show()
        editor.activateWindow()
        ctypes.windll.user32.SetForegroundWindow(int(editor.winId()))
        QTest.qWait(150)
        before = ctypes.windll.user32.GetForegroundWindow()
        assert before not in (0, int(small.winId())), "Could not establish an external foreground"
        window.show_compact(activate=False)
        QTest.qWait(150)
        after = ctypes.windll.user32.GetForegroundWindow()
        assert after == before, "Compact window stole focus"
        report["no_focus_stealing"] = "passed"
        # Simulate streaming through the actual worker and controller signal path.
        def work(job):
            for token in ["本地", "翻译", "，流式显示。"]:
                job.token.emit(token)
                time.sleep(.03)
        window.result.clear()
        window.run_job(work, lambda _: None, tokens=True)
        assert small.stop.isVisible() and not small.translate_button.isEnabled()
        deadline = time.monotonic() + 5
        while window.job and time.monotonic() < deadline:
            QTest.qWait(20)
        assert window.job is None
        assert small.result.toPlainText() == "本地翻译，流式显示。"
        assert small.translate_button.isEnabled() and not small.stop.isVisible()
        report["worker_streaming"] = "passed"
        small.move_to_screen("missing-disconnected-display")
        QTest.qWait(50)
        assert small.selected_screen().availableGeometry().contains(small.geometry())
        report["missing_screen_fallback"] = "passed"
        # Reference screenshot uses only synthetic text, never another app's screen contents.
        small.state.width, small.state.height = 440, 560
        small.move_to_screen("")
        sample = ("在锂离子电池中，电解质的整体溶剂化结构是决定电池物理性质和电化学性能的关键因素。"
                  "这些性质包括导电性、黏度、盐类物质的解离及其后续反应行为，以及电化学稳定性窗口。\n\n"
                  "通过分子动力学模拟，我们可以观察离子的配位环境，并理解溶剂分子在第一配位壳层中的交换过程。"
                  "结合实验数据和量子化学计算，可以进一步分析微观结构与宏观输运性质之间的联系。\n\n"
                  "ZTrans 使用本机模型完成翻译。你可以继续在主屏阅读，译文会在副屏的小窗口中逐步显示。")
        window.source.setPlainText(original)
        window.result.setPlainText(sample)
        small.follow_output = False
        small.result.verticalScrollBar().setValue(0)
        small.set_status("翻译完成 · 本机模型")
        small.set_progress(100)
        application.processEvents()
        small.grab().save(str(directory / "compact-preview.png"))
        small.close()
        assert not small.isVisible()
        window.show_preferred(activate=False)
        assert small.isVisible() and not window.isVisible()
        report["close_and_restore"] = "passed"
        report["status"] = "passed"
    except Exception:
        report["status"] = "failed"
        report["traceback"] = traceback.format_exc()
    finally:
        if editor:
            editor.close()
        if window:
            window.hide()
            window.compact.hide()
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
