"""Local text extraction and document exports."""
from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from core import Cancelled, UserError, http_session, repair_linebreaks


@dataclass
class Imported:
    title: str
    text: str
    note: str = ""


def _check_cancel(cancel):
    if cancel and cancel.is_set():
        raise Cancelled()


def import_file(path: str, progress=lambda value, note: None, cancel=None) -> Imported:
    source = Path(path)
    if source.stat().st_size > 150 * 1024 * 1024:
        raise UserError("文件超过 150 MB，请先拆分文档后导入。")
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        import pymupdf as fitz
        pages, empty_pages = [], []
        with fitz.open(source) as doc:
            if doc.needs_pass:
                raise UserError("此 PDF 有密码。请先解锁并另存为可读取的副本。")
            for i, page in enumerate(doc):
                _check_cancel(cancel)
                progress(int(i / max(len(doc), 1) * 100), f"读取 PDF 第 {i + 1} / {len(doc)} 页")
                blocks = page.get_text("blocks", sort=True)
                text = "\n\n".join(repair_linebreaks(b[4]) for b in blocks if b[6] == 0 and b[4].strip())
                if text.strip():
                    pages.append(text)
                else:
                    empty_pages.append(i + 1)
        note = f"已从 {len(pages)} 页提取文本。"
        if empty_pages:
            note += " 无文本层文字的页码：" + ", ".join(map(str, empty_pages))
        note += " 双栏论文、公式与表格请对照原文件核对阅读顺序。"
        return Imported(source.name, "\n\n".join(pages), note)
    if suffix == ".docx":
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        with zipfile.ZipFile(source) as archive:
            if sum(x.file_size for x in archive.infolist()) > 300 * 1024 * 1024:
                raise UserError("Word 文件解压后过大，请拆分后导入。")
        doc = Document(source)
        parts = []
        for item in doc.iter_inner_content():
            _check_cancel(cancel)
            if isinstance(item, Paragraph) and item.text.strip():
                parts.append(item.text)
            elif isinstance(item, Table):
                for row in item.rows:
                    cells, seen = [], set()
                    for cell in row.cells:
                        if cell._tc not in seen:
                            cells.append(cell.text)
                            seen.add(cell._tc)
                    if any(cells):
                        parts.append("\t".join(cells))
        return Imported(source.name, "\n\n".join(parts), "已读取正文和表格。页眉页脚、文本框、批注及图片内文字不包含在此导入中。")
    if suffix == ".doc":
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        word, doc, previous_links = None, None, None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            word.AutomationSecurity = 3
            previous_links = word.Options.UpdateLinksAtOpen
            word.Options.UpdateLinksAtOpen = False
            doc = word.Documents.Open(str(source.resolve()), ConfirmConversions=False, ReadOnly=True, AddToRecentFiles=False, PasswordDocument="ZTrans-no-password")
            text = doc.Content.Text.replace("\r", "\n\n").replace("\x07", "\t")
        except Exception:
            raise UserError("无法读取旧版 .doc。请用 Word 另存为 .docx 后导入（原文件不会被修改）。")
        finally:
            if doc is not None:
                doc.Close(False)
            if word is not None:
                if previous_links is not None:
                    word.Options.UpdateLinksAtOpen = previous_links
                word.Quit()
            pythoncom.CoUninitialize()
        return Imported(source.name, text, "已通过本机 Word 只读提取正文。")
    if suffix in (".html", ".htm"):
        return extract_html(source.read_bytes(), source.name)
    if suffix in (".txt", ".md", ".srt"):
        data = source.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "gb18030"):
            try:
                return Imported(source.name, data.decode(encoding))
            except UnicodeError:
                continue
        raise UserError("无法识别文本编码。请另存为 UTF-8 后导入。")
    raise UserError("支持 PDF、Word（docx/doc）、TXT、Markdown、HTML 和 SRT 文本。")


def extract_html(data: bytes | str, fallback="网页") -> Imported:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else fallback
    for tag in soup.select("script,style,noscript,nav,footer,header,aside,form,svg,canvas,iframe,[hidden],[aria-hidden='true']"):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    parts = []
    for tag in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote", "td", "th"]):
        # Keep deepest blocks once, while retaining <br> within a block.
        if tag.find(["p", "li", "pre", "blockquote", "td", "th"]):
            continue
        text = tag.get_text(" ", strip=True)
        if text:
            parts.append(text)
    text = "\n\n".join(parts) or root.get_text("\n", strip=True)
    return Imported(title, text, "提取网页正文；不执行脚本，不读取浏览器登录信息。动态网页可复制正文后粘贴。")


def fetch_webpage(url: str, cancel=None) -> Imported:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise UserError("请输入有效的网页地址。")
    import requests
    try:
        with http_session() as session:
            session.max_redirects = 5
            with session.get(url, timeout=(8, 25), stream=True) as response:
                if not response.ok:
                    raise UserError(f"网页返回 HTTP {response.status_code}，可改为复制正文后粘贴。")
                content_type = response.headers.get("Content-Type", "").lower()
                if "pdf" in content_type:
                    raise UserError("此地址是 PDF，请先下载文件，然后拖入 ZTrans。")
                if content_type and not any(x in content_type for x in ("text/", "html", "xhtml")):
                    raise UserError("此地址不是 HTML 网页，请下载文件后导入。")
                data, size = [], 0
                for chunk in response.iter_content(65536):
                    _check_cancel(cancel)
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise UserError("网页超过 8 MB，请复制需要翻译的正文。")
                    data.append(chunk)
        return extract_html(b"".join(data), url)
    except requests.RequestException:
        raise UserError("网页连接失败。请检查地址，或直接复制正文到左侧。")


def export_docx(path: str, pairs: list[tuple[str, str]], title: str, bilingual=True):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(.75)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.paragraph_format.space_after = Pt(9)
    normal.paragraph_format.line_spacing = 1.35
    doc.add_heading(title or "ZTrans 翻译", 0)
    doc.add_paragraph("双语对照 · ZTrans" if bilingual else "译文 · ZTrans", "Subtitle")
    for original, translated in pairs:
        if bilingual:
            p = doc.add_paragraph(original)
            for run in p.runs:
                run.font.color.rgb = RGBColor.from_string("64748B")
        doc.add_paragraph(translated)
    footer = section.footer.paragraphs[0]
    footer.alignment = 2
    footer.add_run("ZTrans  ·  ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    footer._p.append(fld)
    doc.save(path)


def export_html(path: str, pairs: list[tuple[str, str]], title: str, bilingual=True):
    blocks = []
    for original, translated in pairs:
        if bilingual:
            blocks.append('<p class="source">' + html.escape(original) + "</p>")
        blocks.append('<p class="target">' + html.escape(translated) + "</p>")
    content = f'''<!doctype html><html lang="zh-CN"><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<title>{html.escape(title)}</title><style>body{{max-width:820px;margin:60px auto;padding:0 24px;font:17px/1.9 system-ui,sans-serif;color:#172c3e}}h1{{font-size:28px}}p{{white-space:pre-wrap}}.source{{color:#73818d;font-size:15px;margin-bottom:8px}}.target{{margin-top:0;border-left:3px solid #158b7b;padding-left:18px;margin-bottom:32px}}small{{color:#73818d}}</style>
<h1>{html.escape(title)}</h1><small>ZTrans · 双语对照</small>{''.join(blocks)}</html>'''
    Path(path).write_text(content, encoding="utf-8")


def export_pdf(path: str, pairs: list[tuple[str, str]], title: str, bilingual=True):
    """Reflowed readable PDF; never claims to reproduce the original layout."""
    import pymupdf as fitz
    blocks = []
    for original, translated in pairs:
        if bilingual:
            blocks.append('<p class="source">' + html.escape(original).replace("\n", "<br>") + "</p>")
        blocks.append('<p>' + html.escape(translated).replace("\n", "<br>") + "</p>")
    story = fitz.Story(html=f"<h1>{html.escape(title)}</h1>" + "".join(blocks), user_css="body{font-family:sans-serif;font-size:11pt;line-height:1.55}h1{font-size:20pt;color:#17384a}.source{color:#64748b;font-size:10pt}")
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (48, 48, -48, -48)
    with fitz.DocumentWriter(path) as writer:
        more = True
        while more:
            device = writer.begin_page(mediabox)
            more, _ = story.place(where)
            story.draw(device)
            writer.end_page()
