"""Runs with synthetic content only, including inside the packaged application."""
import json
import traceback
from pathlib import Path


def run_smoke(app, directory):
    directory.mkdir(parents=True, exist_ok=True)
    report = {}
    try:
        from app import MainWindow
        from core import Settings, Translator, UserError, repair_linebreaks
        from documents import export_docx, export_pdf, import_file
        from settings_ui import SettingsDialog
        from windows import app_icon
        import pymupdf
        original = "Molecular dynamics simulations reveal\nthe solvation structure of sodium ions."
        text = repair_linebreaks(original)
        translated = Translator(Settings()).translate(text)
        assert any('\u4e00' <= c <= '\u9fff' for c in translated)
        report["local_translation"] = {"source": text, "translation": translated}
        pairs = [(text, translated)]
        export_docx(str(directory / "sample.docx"), pairs, "ZTrans 翻译测试")
        assert "Molecular" in import_file(str(directory / "sample.docx")).text
        export_pdf(str(directory / "sample.pdf"), pairs, "ZTrans 双语测试")
        assert "Molecular" in import_file(str(directory / "sample.pdf")).text
        with pymupdf.open(directory / "sample.pdf") as pdf:
            pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4)).save(directory / "pdf-preview.png")
        image = directory / "image-fixture.png"
        with pymupdf.open(directory / "sample.pdf") as pdf:
            pdf[0].get_pixmap().save(image)
        try:
            import_file(str(image))
        except UserError:
            report["image_rejected"] = "passed"
        else:
            raise AssertionError("Image import should be rejected")
        with pymupdf.open() as scan:
            page = scan.new_page()
            page.insert_image(page.rect, filename=str(image))
            scan.save(directory / "scanned.pdf")
        assert not import_file(str(directory / "scanned.pdf")).text
        report["image_only_pdf_skipped"] = "passed"
        window = MainWindow(register_hotkeys=False)
        window.show()
        window.source.setPlainText(original)
        window.result.setPlainText(translated)
        window.pairs = pairs
        window.result_count.setText("翻译完成 · 本机 hy-mt1.5:7b")
        window.notify("翻译完成 · 原文未发送到在线翻译服务")
        app.processEvents()
        window.grab().save(str(directory / "app-preview.png"))
        dialog = SettingsDialog(Settings(), window)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(directory / "settings-preview.png"))
        dialog.close()
        window.hide()
        report["ui"] = "passed"
        report["status"] = "passed"
    except Exception:
        report["status"] = "failed"
        report["traceback"] = traceback.format_exc()
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
