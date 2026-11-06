"""Integration checks against real Ollama and a local synthetic API server."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import app as zapp
from core import Settings, Translator
from documents import import_file
from settings_ui import SettingsDialog
from theme import STYLE


def run():
    application = QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE)
    application.setQuitOnLastWindowClosed(False)
    zapp.load_settings = lambda: Settings()
    zapp.save_settings = lambda value: None
    errors = []
    QMessageBox.warning = lambda *args: errors.append(str(args[-1]))
    window = zapp.MainWindow(register_hotkeys=False)
    window.show()
    def until_done(timeout=90):
        deadline = time.monotonic() + timeout
        while window.job and time.monotonic() < deadline:
            QTest.qWait(25)
        assert window.job is None, "Worker did not exit"
        assert not errors, errors
    window.source.setPlainText("The electrolyte improves ionic conductivity.\n\nThe separator prevents a short circuit.")
    window.translate()
    assert window.job and window.source.isReadOnly()
    until_done()
    assert window.translation_complete and len(window.pairs) == 2
    assert len(window.result.toPlainText()) > 15
    assert not window.source.isReadOnly()
    window.result.insertPlainText("（编辑校对）")
    assert "编辑校对" in window.result.toPlainText()
    window.set_mode(2)
    assert window.web_card.isVisible()
    window.set_mode(1)
    assert window.import_card.isVisible()
    window.load_file(str(Path(__file__).parent.parent / "smoke-native" / "sample.docx"))
    until_done()
    assert "Molecular" in window.source.toPlainText()
    dialog = SettingsDialog(Settings(), window)
    dialog.provider.setCurrentIndex(1)
    assert dialog.collect().provider == "api"
    assert dialog.collect().api_model == "deepseek-chat"
    dialog.remote.setChecked(True)
    assert dialog.collect().remote_consent
    dialog.url.setText("https://changed.example/v1")
    dialog.endpoint_changed()
    assert not dialog.remote.isChecked()
    dialog.provider.setCurrentIndex(0)
    assert dialog.collect().ollama_model == "hy-mt1.5:7b"
    dialog.fetch_models()
    deadline = time.monotonic() + 25
    while dialog.job and time.monotonic() < deadline:
        QTest.qWait(25)
    assert dialog.job is None
    assert dialog.model.findText("hy-mt1.5:7b") >= 0
    dialog.close()
    # Real HTTP transport: chunks, UTF-8, authorization, stop event and explicit API route.
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))), self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for token in ["电解液", "提高", "离子电导率。"]:
                msg = {"choices": [{"delta": {"content": token}, "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(msg, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(.02)
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = Settings(provider="api", api_url=f"http://127.0.0.1:{server.server_port}/v1", api_model="test", api_key="SYNTHETIC-TEST-KEY")
    result = Translator(cfg).translate("The electrolyte improves ionic conductivity.")
    assert result == "电解液提高离子电导率。"
    assert received[0][0] == "/v1/chat/completions"
    assert received[0][2] == "Bearer SYNTHETIC-TEST-KEY"
    server.shutdown()
    server.server_close()
    # Cancelling a job keeps the application usable and never destroys a running QThread.
    def slow(job):
        for _ in range(50):
            if job.cancel.wait(.02):
                from core import Cancelled
                raise Cancelled()
    window.run_job(slow, lambda _: None)
    window.cancel_job()
    until_done(5)
    assert window.translate_button.isEnabled()
    window.hide()
    print(json.dumps({"gui_real_translation": "passed", "import": "passed", "settings_model_detection": "passed", "api_http_stream": "passed", "cancellation": "passed"}))


if __name__ == "__main__":
    run()
