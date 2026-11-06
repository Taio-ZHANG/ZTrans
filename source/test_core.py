import json
import threading
from dataclasses import replace

import pytest

from core import (Cancelled, Settings, Translator, UserError, api_endpoint, is_loopback,
                  load_settings, normalize_url, repair_linebreaks, save_settings,
                  split_text, translation_prompt, validate_destination)
from documents import export_docx, export_html, export_pdf, extract_html, import_file


def test_repair_pdf_wraps_and_paragraphs():
    source = "Molecular dynamics simulations reveal\nthe structure of the solvation shell.\n\nA new paragraph."
    assert repair_linebreaks(source) == "Molecular dynamics simulations reveal the structure of the solvation shell.\n\nA new paragraph."


def test_repair_chinese_bullets_and_dehyphenation():
    assert repair_linebreaks("分子动力学\n模拟。\n结果很好。") == "分子动力学模拟。结果很好。"
    assert repair_linebreaks("electro-\nchemical") == "electrochemical"
    assert repair_linebreaks("List:\n- sodium\n- lithium") == "List:\n- sodium\n- lithium"
    assert repair_linebreaks("a\tb\nc\td") == "a\tb\nc\td"


@pytest.mark.parametrize("source", ["Word. " * 800, "中文文本。" * 900, "X" * 6000, "a\n\nb\n\nc", "token " * 1000 + "尾部"])
def test_chunking_never_drops_text(source):
    chunks = split_text(source)
    assert all(len(chunk) <= 1500 for chunk in chunks)
    assert "".join("".join(chunks).split()) == "".join(source.split())


def test_destination_restrictions():
    cfg = Settings()
    validate_destination(cfg)
    assert is_loopback("http://localhost:11434")
    assert is_loopback("http://[::1]:11434")
    assert not is_loopback("https://localhost.attacker.example")
    assert not is_loopback("https://127.0.0.1.nip.io")
    for value in ["file:///tmp/a", "https://user:secret@example.com", "https://host/x?key=secret", "http://host:bad"]:
        with pytest.raises(UserError):
            normalize_url(value)
    cfg.provider = "api"
    with pytest.raises(UserError):
        validate_destination(cfg)
    cfg.remote_consent = cfg.consent_id
    validate_destination(cfg)
    cfg.api_url = "https://another.example/v1"
    with pytest.raises(UserError):
        validate_destination(cfg)
    cfg.api_url = "http://another.example/v1"
    cfg.remote_consent = cfg.consent_id
    with pytest.raises(UserError):
        validate_destination(cfg)
    with pytest.raises(UserError):
        validate_destination(Settings(ollama_model="model:cloud"))


def test_api_paths():
    assert api_endpoint("https://example.com", "models") == "https://example.com/v1/models"
    assert api_endpoint("https://example.com/compatible-mode/v1/", "chat/completions") == "https://example.com/compatible-mode/v1/chat/completions"
    assert api_endpoint("https://example.com/v1/chat/completions", "models") == "https://example.com/v1/models"


def test_key_encrypted_and_endpoint_bound(tmp_path):
    cfg = Settings(api_key="TEST-ONLY-FAKE-SECRET")
    save_settings(cfg, tmp_path)
    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert cfg.api_key not in raw
    assert load_settings(tmp_path).api_key == cfg.api_key
    data = json.loads(raw)
    data["api_url"] = "https://different.example/v1"
    (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    assert load_settings(tmp_path).api_key == ""
    cfg.remember_key = False
    save_settings(cfg, tmp_path)
    assert "protected_key" not in (tmp_path / "settings.json").read_text(encoding="utf-8")


def test_only_relevant_glossary_sent():
    cfg = Settings(glossary="solvation = 溶剂化\nprivate_unmatched = PRIVATE TERM")
    prompt = translation_prompt("The solvation shell.", cfg)
    assert "溶剂化" in prompt
    assert "PRIVATE" not in prompt


class Response:
    def __init__(self, lines=(), data=None, status=200):
        self.status_code = status
        self.lines = lines
        self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def json(self): return self.data
    def iter_lines(self, **kwargs): yield from self.lines


class Session:
    def __init__(self, response, metadata=None):
        self.response = response
        self.metadata = metadata or {}
        self.calls = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert kwargs.get("allow_redirects") is False
        return Response(data=self.metadata) if url.endswith("/show") else self.response


def test_stream_completion_and_cloud_forwarding_guard(monkeypatch):
    lines = [json.dumps({"message": {"content": "你好"}, "done": False}), json.dumps({"done": True})]
    session = Session(Response(lines))
    monkeypatch.setattr("core.http_session", lambda: session)
    assert Translator(Settings()).translate("Hello") == "你好"
    session.metadata = {"remote_host": "https://cloud.example"}
    session.calls.clear()
    with pytest.raises(UserError, match="云端"):
        Translator(Settings()).translate("PRIVATE")
    assert len(session.calls) == 1
    assert "PRIVATE" not in json.dumps(session.calls)


def test_incomplete_and_cancelled_streams(monkeypatch):
    session = Session(Response([json.dumps({"message": {"content": "part"}})]))
    monkeypatch.setattr("core.http_session", lambda: session)
    with pytest.raises(UserError, match="完整"):
        Translator(Settings()).translate("input")
    event = threading.Event()
    event.set()
    session.calls.clear()
    with pytest.raises(Cancelled):
        Translator(Settings(), event).translate("input")
    assert not session.calls


def test_remote_never_sent_before_consent(monkeypatch):
    session = Session(Response())
    monkeypatch.setattr("core.http_session", lambda: session)
    with pytest.raises(UserError):
        Translator(Settings(provider="api")).translate("PRIVATE")
    assert not session.calls


def test_api_sse_and_truncation(monkeypatch):
    cfg = Settings(provider="api", api_url="http://127.0.0.1:8888/v1")
    session = Session(Response(['data: {"choices":[{"delta":{"content":"译文"},"finish_reason":null}]}', 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}', 'data: [DONE]']))
    monkeypatch.setattr("core.http_session", lambda: session)
    assert Translator(cfg).translate("text") == "译文"
    session.response = Response(['data: {"choices":[{"delta":{"content":"part"},"finish_reason":"length"}]}'])
    with pytest.raises(UserError):
        Translator(cfg).translate("text")
    session.response = Response(status=302)
    with pytest.raises(UserError, match="重定向"):
        Translator(cfg).translate("text")


def test_html_no_script_and_no_duplicate_blocks(tmp_path):
    doc = extract_html("<title>Sample</title><nav>menu</nav><article><h1>Heading</h1><p>Hello <b>world</b></p><script>bad()</script></article>")
    assert doc.title == "Sample"
    assert doc.text == "Heading\n\nHello world"
    path = tmp_path / "out.html"
    export_html(str(path), [("<script>bad()</script>", "译文")], "<unsafe>")
    out = path.read_text(encoding="utf-8")
    assert "<script>bad()" not in out
    assert "default-src 'none'" in out


def test_word_table_order_and_export(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("Before")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Sodium"
    table.cell(0, 1).text = "Lithium"
    doc.add_paragraph("After")
    path = tmp_path / "test.docx"
    doc.save(path)
    imported = import_file(str(path))
    assert imported.text == "Before\n\nSodium\tLithium\n\nAfter"
    export_docx(str(tmp_path / "bilingual.docx"), [("Original", "译文")], "测试")
    exported = Document(tmp_path / "bilingual.docx")
    assert "译文" in [p.text for p in exported.paragraphs]


def test_pdf_export_unicode_and_import(tmp_path):
    import pymupdf
    path = tmp_path / "test.pdf"
    export_pdf(str(path), [("Molecular dynamics reveals solvation structure.", "分子动力学揭示溶剂化结构。")], "双语测试")
    with pymupdf.open(path) as doc:
        text = "".join(page.get_text() for page in doc)
    assert "分子动力学" in text
    assert "Molecular dynamics" in import_file(str(path)).text
