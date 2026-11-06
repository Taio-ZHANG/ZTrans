from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QMimeData, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSplitter, QSystemTrayIcon,
    QVBoxLayout, QWidget)

from compact import CompactWindow
from core import (APP_VERSION, Cancelled, LANGUAGES, Translator, UserError, is_loopback,
                  load_settings, repair_linebreaks, save_settings, split_text, validate_destination)
from documents import export_docx, export_html, export_pdf, fetch_webpage, import_file
from jobs import Job
from settings_ui import SettingsDialog
from theme import STYLE
from windows import Hotkeys, app_icon, set_startup


def label(text, name=None):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    return item


def button(text, handler, name=None):
    item = QPushButton(text)
    if name:
        item.setObjectName(name)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    item.clicked.connect(handler)
    return item


class TextEdit(QPlainTextEdit):
    file_dropped = Signal(str)

    def canInsertFromMimeData(self, source):
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls() and source.urls()[0].isLocalFile():
            self.file_dropped.emit(source.urls()[0].toLocalFile())
        else:
            super().insertFromMimeData(source)


class MainWindow(QMainWindow):
    def __init__(self, register_hotkeys=True, window_state_path=None):
        super().__init__()
        self.cfg = load_settings()
        self.compact = None
        self.job = None
        self.pairs = []
        self.translation_complete = False
        self.document_title = "ZTrans 翻译"
        self.started_at = None
        self._selection_pending = False
        self._selection_foreground = None
        self.quitting = False
        self.tray_hint = False
        self.setWindowTitle("ZTrans · 自在翻译，数据由你掌握")
        self.setWindowIcon(app_icon())
        self.resize(1260, 820)
        self.setMinimumSize(960, 650)
        self.setAcceptDrops(True)
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(198)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 30, 20, 22)
        brand_row = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(38, 38))
        brand_row.addWidget(mark)
        brand_row.addWidget(label("ZTrans", "brand"))
        side.addLayout(brand_row)
        side.addSpacing(9)
        side.addWidget(label("自在翻译，数据由你掌握", "muted"))
        side.addSpacing(35)
        side.addWidget(label("WORKSPACE", "eyebrow"))
        side.addSpacing(8)
        self.navs = []
        nav_group = QButtonGroup(self)
        for index, title in enumerate(["文字翻译", "文档翻译", "网页翻译"]):
            nav = button(title, lambda checked=False, i=index: self.set_mode(i), "nav")
            nav.setCheckable(True)
            nav_group.addButton(nav)
            side.addWidget(nav)
            self.navs.append(nav)
        self.navs[0].setChecked(True)
        side.addSpacing(7)
        side.addWidget(button("悬浮小窗", self.show_compact, "nav"))
        side.addStretch()
        side.addWidget(label("随手就能翻译", "eyebrow"))
        shortcuts = label("选中文字  F1\n唤起窗口  Ctrl + Alt + Z", "muted")
        shortcuts.setStyleSheet("line-height: 1.8;")
        side.addWidget(shortcuts)
        side.addSpacing(22)
        self.settings_button = button("设置与隐私", self.open_settings, "nav")
        side.addWidget(self.settings_button)
        side.addWidget(label(f"ZTrans  {APP_VERSION}  ·  本地优先", "muted"))
        outer.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(30, 28, 30, 22)
        body.setSpacing(18)
        outer.addLayout(body, 1)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_title = label("把语言的距离，留给翻译。", "title")
        self.subtitle = label("粘贴文字或拖入文档，在这里安心阅读。", "muted")
        titles.addWidget(self.page_title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.badge = label("", "badge")
        header.addWidget(self.badge)
        body.addLayout(header)
        self.import_card = QFrame()
        self.import_card.setObjectName("card")
        import_row = QHBoxLayout(self.import_card)
        import_row.setContentsMargins(18, 15, 18, 15)
        desc = label("拖入 PDF / Word / 文本\n在本机提取文字，再选择是否翻译。")
        import_row.addWidget(desc, 1)
        self.pick_button = button("选择文件", self.choose_file)
        import_row.addWidget(self.pick_button)
        self.import_card.hide()
        body.addWidget(self.import_card)
        self.web_card = QFrame()
        self.web_card.setObjectName("card")
        web_layout = QVBoxLayout(self.web_card)
        web_row = QHBoxLayout()
        self.web_url = QLineEdit()
        self.web_url.setPlaceholderText("输入网页地址，例如 https://example.com/article")
        self.web_url.returnPressed.connect(self.fetch_page)
        web_row.addWidget(self.web_url, 1)
        self.web_button = button("读取正文", self.fetch_page)
        web_row.addWidget(self.web_button)
        web_layout.addLayout(web_row)
        web_layout.addWidget(label("读取时会访问该网站；正文翻译只交给当前所选模型。登录页请复制正文。", "muted"))
        self.web_card.hide()
        body.addWidget(self.web_card)
        controls = QHBoxLayout()
        self.source_lang = QComboBox()
        self.source_lang.addItems(["自动识别"] + LANGUAGES)
        self.source_lang.setCurrentText(self.cfg.source)
        self.target_lang = QComboBox()
        self.target_lang.addItems(LANGUAGES)
        self.target_lang.setCurrentText(self.cfg.target)
        self.swap_button = button("⇄", self.swap_languages, "quiet")
        controls.addWidget(self.source_lang)
        controls.addWidget(self.swap_button)
        controls.addWidget(self.target_lang)
        controls.addSpacing(12)
        self.style = QComboBox()
        self.style.addItems(["忠实翻译", "学术论文", "自然流畅"])
        self.style.setCurrentText(self.cfg.style)
        controls.addWidget(self.style)
        controls.addStretch()
        self.model_label = label("", "muted")
        controls.addWidget(self.model_label)
        body.addLayout(controls)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.source = TextEdit()
        self.source.setPlaceholderText("在这里粘贴需要翻译的内容…\n\n也可以拖入 PDF、Word 或文本文件。\n从 PDF 复制的碎行，可以一键拼回完整段落。")
        self.source.file_dropped.connect(self.load_file)
        self.result = QPlainTextEdit()
        self.result.setPlaceholderText("译文会在这里逐步出现。\n\n支持编辑译文，以及导出双语 Word、PDF、HTML。\n\n默认不保存翻译历史。")
        self.source.setObjectName("editor")
        self.result.setObjectName("editor")
        self.source_count = label("0 字符", "muted")
        self.result_count = label("等待翻译", "muted")
        self.source.textChanged.connect(lambda: self.source_count.setText(f"{len(self.source.toPlainText()):,} 字符"))
        self.source_card = self.editor_card("原文", self.source, self.source_count, [
            ("粘贴", self.paste), ("修复断行", self.preview_repair), ("清空", self.clear)])
        self.result_card = self.editor_card("译文", self.result, self.result_count, [
            ("复制", self.copy_result), ("导出", self.export)])
        split.addWidget(self.source_card)
        split.addWidget(self.result_card)
        split.setSizes([520, 520])
        body.addWidget(split, 1)
        footer = QHBoxLayout()
        self.repair_check = QCheckBox("翻译前修复多余换行")
        self.repair_check.setChecked(self.cfg.repair_lines)
        self.repair_check.setToolTip("保留空行分段和列表；论文标题、双栏和连字符仍建议预览核对。")
        footer.addWidget(self.repair_check)
        footer.addStretch()
        footer.addWidget(label("Ctrl + Enter", "muted"))
        self.stop_button = button("停止", self.cancel_job)
        self.stop_button.hide()
        footer.addWidget(self.stop_button)
        self.translate_button = button("开始翻译  →", self.translate, "primary")
        footer.addWidget(self.translate_button)
        body.addLayout(footer)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        body.addWidget(self.progress)
        self.status = label("就绪 · 原文和译文只保留在当前会话内", "muted")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(33)
        body.addWidget(self.status)
        self.shortcut_translate = QShortcut(QKeySequence("Ctrl+Return"), self, self.translate)
        self.shortcut_stop = QShortcut(QKeySequence("Escape"), self, self.cancel_job)
        self.shortcut_open = QShortcut(QKeySequence("Ctrl+O"), self, self.choose_file)
        self.shortcut_export = QShortcut(QKeySequence("Ctrl+Shift+S"), self, self.export)
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("ZTrans · 本地优先的翻译工具")
        tray_menu = QMenu()
        tray_menu.addAction("打开 ZTrans", self.show_preferred)
        tray_menu.addAction("悬浮小窗", self.show_compact)
        tray_menu.addAction("翻译剪贴板文字", self.translate_clipboard)
        tray_menu.addSeparator()
        tray_menu.addAction("设置与隐私", self.open_settings)
        tray_menu.addAction("退出 ZTrans", self.quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(lambda reason: self.show_preferred() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        if register_hotkeys:
            self.tray.show()
        self.hotkeys = Hotkeys() if register_hotkeys else None
        if self.hotkeys:
            QApplication.instance().installNativeEventFilter(self.hotkeys)
            self.hotkeys.signals.activated.connect(self.on_hotkey)
            if self.hotkeys.failed:
                self.status.setText("快捷键被其他程序占用：" + ", ".join(self.hotkeys.failed) + "。仍可用窗口或托盘操作。")
        self.apply_preferences()
        self.compact = CompactWindow(self, state_path=window_state_path, persist=register_hotkeys)

    def editor_card(self, title, editor, count, actions):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 15, 16, 13)
        top = QHBoxLayout()
        name = label(title)
        name.setStyleSheet("font-weight: 600; font-size: 14px;")
        top.addWidget(name)
        top.addStretch()
        for text, handler in actions:
            top.addWidget(button(text, handler, "quiet"))
        layout.addLayout(top)
        layout.addWidget(editor, 1)
        layout.addWidget(count)
        return card

    def apply_preferences(self):
        local = is_loopback(self.cfg.base_url)
        self.badge.setText(("●  本机模型" if self.cfg.provider == "ollama" else "●  本机 API") if local else "●  在线 API")
        self.badge.setObjectName("badge" if local else "remoteBadge")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.badge.setToolTip(f"内容发送到：{self.cfg.base_url}\n模型：{self.cfg.model}")
        self.model_label.setText(self.cfg.model)
        for editor in (self.source, self.result):
            editor.setFont(QFont("Microsoft YaHei UI", self.cfg.font_size))
        if self.compact:
            self.compact.apply_preferences()

    def set_mode(self, mode):
        self.navs[mode].setChecked(True)
        self.import_card.setVisible(mode == 1)
        self.web_card.setVisible(mode == 2)
        self.page_title.setText(["把语言的距离，留给翻译。", "每一页，都能轻松读懂。", "让好内容，不止一种语言。"][mode])
        self.subtitle.setText(["粘贴文字或拖入文档，在这里安心阅读。", "本地提取 · 双栏对照 · 自由导出", "读取网页正文，在熟悉的双栏里阅读。"][mode])

    def show_window(self):
        self.show_compact()

    def show_compact(self, activate=True):
        if self.compact:
            self.hide()
            self.compact.show_compact(activate=activate)

    def show_preferred(self, activate=True):
        self.show_compact(activate=activate)

    def active_surface(self):
        return self.compact if self.compact and self.compact.isVisible() else self

    def notify(self, text):
        self.status.setText(text)
        if self.compact:
            self.compact.set_status(text)

    def paste(self):
        if not self.job:
            self.source.insertPlainText(QApplication.clipboard().text())

    def clear(self):
        if not self.job:
            self.source.clear()
            self.result.clear()
            self.pairs = []
            self.translation_complete = False
            self.document_title = "ZTrans 翻译"
            self.result_count.setText("等待翻译")
            self.progress.setValue(0)
            self.notify("当前原文和译文已清空。")

    def copy_result(self):
        if self.result.toPlainText():
            QApplication.clipboard().setText(self.result.toPlainText())
            self.notify("译文已复制到系统剪贴板。")

    def swap_languages(self):
        if self.job:
            return
        source = self.source_lang.currentText()
        if source == "自动识别":
            source = "英语" if self.target_lang.currentText() == "简体中文" else "简体中文"
        self.source_lang.setCurrentText(self.target_lang.currentText())
        self.target_lang.setCurrentText(source)

    def preview_repair(self):
        if self.job or not self.source.toPlainText().strip():
            return
        original = self.source.toPlainText()
        repaired = repair_linebreaks(original)
        dialog = QDialog(self.active_surface())
        dialog.setWindowTitle("修复断行 · 预览")
        dialog.resize(850, 540)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("合并 PDF 碎行，保留空行与列表。应用后可在原文框按 Ctrl + Z 撤销。", "muted"))
        split = QSplitter()
        for content in (original, repaired):
            edit = QPlainTextEdit(content)
            edit.setReadOnly(True)
            split.addWidget(edit)
        layout.addWidget(split, 1)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("取消", dialog.reject))
        row.addWidget(button("应用修复", dialog.accept, "primary"))
        layout.addLayout(row)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Keep the undo operation on the editor the user actually interacts with.
            editor = self.compact.source if self.compact else self.source
            cursor = editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(repaired)
            cursor.endEditBlock()
            editor.setTextCursor(cursor)
            self.notify("已修复断行 · Ctrl + Z 可撤销")

    def set_busy(self, busy):
        for widget in (self.translate_button, self.settings_button,
                       self.pick_button, self.web_button, self.web_url, self.source_lang,
                       self.target_lang, self.swap_button, self.style, self.repair_check):
            widget.setEnabled(not busy)
        for card in (self.source_card, self.result_card):
            for control in card.findChildren(QPushButton):
                control.setEnabled(not busy)
        self.source.setReadOnly(busy)
        self.result.setReadOnly(busy)
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(busy)
        self.stop_button.setText("停止")
        if self.compact:
            self.compact.set_busy(busy)

    def run_job(self, function, success, tokens=False):
        if self.job:
            return
        self.set_busy(True)
        self.progress.setRange(0, 0)
        self.job = Job(function, self)
        self.job.result.connect(success)
        self.job.error.connect(self.job_error)
        self.job.cancelled.connect(self.job_cancelled)
        self.job.progress.connect(self.update_progress)
        if tokens:
            self.job.token.connect(self.add_token)
            self.job.piece.connect(lambda original, translated: self.pairs.append((original, translated)))
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def update_progress(self, value, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(value)
        if self.compact:
            self.compact.set_progress(value)
        self.notify(message)

    def add_token(self, token):
        bar = self.result.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 15
        position = bar.value()
        cursor = self.result.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        if at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(position)

    def job_error(self, text):
        if self.result.toPlainText().strip() and not self.translation_complete:
            self.result_count.setText("部分译文 · 任务未完成")
        self.notify(text)
        self.show_preferred()
        QMessageBox.warning(self.active_surface(), "ZTrans · 需要处理", text)

    def job_cancelled(self):
        if not self.translation_complete:
            self.result_count.setText("部分译文 · 已停止")
        self.notify("已停止。已生成的译文保留在小窗，可复制或导出。")

    def job_finished(self):
        completed = self.job
        self.job = None
        self.set_busy(False)
        self.progress.setRange(0, 100)
        completed.deleteLater()
        if self.quitting:
            self.quit_app()

    def cancel_job(self):
        if self.job:
            self.job.cancel.set()
            self.stop_button.setEnabled(False)
            self.stop_button.setText("正在停止…")
            if self.compact:
                self.compact.stop.setEnabled(False)
            self.notify("正在停止，保留已生成的内容；服务无响应时最长等待 90 秒。")

    def translate(self):
        if self.job:
            return
        self.compact.show_translation()
        text = self.source.toPlainText().strip()
        if not text:
            self.source.setFocus()
            self.notify("请先粘贴文字、读取网页或导入文件。")
            return
        self.cfg.source = self.source_lang.currentText()
        self.cfg.target = self.target_lang.currentText()
        self.cfg.style = self.style.currentText()
        self.cfg.repair_lines = self.repair_check.isChecked()
        cfg = replace(self.cfg)
        try:
            validate_destination(cfg)
            save_settings(cfg)
        except (UserError, OSError) as e:
            QMessageBox.warning(self.active_surface(), "检查翻译设置", str(e))
            return
        prepared = repair_linebreaks(text) if cfg.repair_lines else text
        chunks = split_text(prepared)
        if not chunks:
            return
        self.result.clear()
        if self.compact:
            self.compact.follow_output = True
        self.pairs = []
        self.translation_complete = False
        self.started_at = time.monotonic()
        self.result_count.setText("正在翻译…")
        def work(job):
            translator = Translator(cfg, job.cancel)
            for index, chunk in enumerate(chunks):
                if job.cancel.is_set():
                    raise Cancelled()
                job.progress.emit(int(index / len(chunks) * 100), f"正在翻译第 {index + 1} / {len(chunks)} 段 · {cfg.model}")
                if index:
                    job.token.emit("\n\n")
                translated = translator.translate(chunk, job.token.emit)
                job.piece.emit(chunk, translated)
            return len(chunks)
        self.run_job(work, self.translation_done, tokens=True)

    def translation_done(self, count):
        self.translation_complete = True
        seconds = time.monotonic() - self.started_at
        self.progress.setValue(100)
        if self.compact:
            self.compact.set_progress(100)
        self.result_count.setText(f"{len(self.result.toPlainText()):,} 字符  ·  {seconds:.1f} 秒")
        self.notify(f"翻译完成 · {count} 段 · 可复制译文，或导出双语文件")

    def choose_file(self):
        if self.job:
            return
        path, _ = QFileDialog.getOpenFileName(self.active_surface(), "选择需要翻译的文档", "", "文本与文档 (*.pdf *.docx *.doc *.txt *.md *.html *.htm *.srt);;所有文件 (*)")
        if path:
            self.load_file(path)

    def load_file(self, path):
        if self.job:
            return
        self.set_mode(1)
        self.notify("正在本机读取文件…")
        self.run_job(lambda job: import_file(path, job.progress.emit, job.cancel), self.import_done)

    def import_done(self, imported):
        if not imported.text.strip():
            self.notify("未提取到可选文字。扫描版文档请先转换为含文字的文件。")
            return
        self.source.setPlainText(imported.text)
        self.result.clear()
        self.pairs = []
        self.translation_complete = False
        self.document_title = imported.title
        if self.compact:
            self.compact.source_toggle.setChecked(True)
        self.result_count.setText("等待翻译")
        self.progress.setValue(0)
        self.notify(f"{imported.title} · {imported.note or '读取完成。'} 点击“翻译原文”继续。")

    def fetch_page(self):
        if self.job or not self.web_url.text().strip():
            return
        url = self.web_url.text()
        self.notify("正在读取网页正文…")
        self.run_job(lambda job: fetch_webpage(url, job.cancel), self.import_done)

    def dragEnterEvent(self, event):
        if not self.job and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.job and event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                self.load_file(url.toLocalFile())
                event.acceptProposedAction()

    def on_hotkey(self, ident):
        if self.quitting or QApplication.activeModalWidget():
            return
        if ident == 3:
            self.show_preferred()
        elif ident == 1 and not self.job and not self._selection_pending:
            self._selection_pending = True
            self._selection_foreground = ctypes.windll.user32.GetForegroundWindow()
            self.capture_selection(0)

    def selection_context_valid(self):
        if not self._selection_pending:
            return False
        if (self.job or self.quitting or QApplication.activeModalWidget()
                or not self._selection_foreground
                or ctypes.windll.user32.GetForegroundWindow() != self._selection_foreground):
            self._selection_pending = False
            self.notify("取词已取消：当前窗口或任务已变化，请重新选中文字并按 F1。")
            return False
        return True

    def capture_selection(self, attempts):
        if not self.selection_context_valid():
            return
        # Wait for modifier keys to be released before injecting a normal Copy command.
        user32 = ctypes.windll.user32
        if any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C, 0x70)):
            if attempts < 40:
                QTimer.singleShot(50, lambda: self.capture_selection(attempts + 1))
            else:
                self._selection_pending = False
                self.notify("请松开快捷键，再按一次 F1 取词。")
            return
        sequence = user32.GetClipboardSequenceNumber()
        user32.keybd_event(0x11, 0, 0, 0)
        user32.keybd_event(0x43, 0, 0, 0)
        user32.keybd_event(0x43, 0, 2, 0)
        user32.keybd_event(0x11, 0, 2, 0)
        QTimer.singleShot(220, lambda: self.selection_ready(sequence, 0))

    def selection_ready(self, sequence, tries):
        if not self.selection_context_valid():
            return
        if ctypes.windll.user32.GetClipboardSequenceNumber() == sequence:
            if tries < 3:
                QTimer.singleShot(180, lambda: self.selection_ready(sequence, tries + 1))
            else:
                self._selection_pending = False
                self.show_preferred(activate=False)
                self.compact.show_translation()
                self.notify("未获取到选中文字，未发送旧剪贴板内容。可以先复制，再点“粘贴翻译”。")
            return
        self._selection_pending = False
        self.translate_clipboard()

    def translate_clipboard(self):
        if self.job:
            self.show_preferred(activate=False)
            return
        text = QApplication.clipboard().text()
        self.show_preferred(activate=False)
        self.compact.show_translation()
        if text.strip():
            self.set_mode(0)
            self.source.setPlainText(text)
            self.document_title = "选中文字翻译"
            self.translate()
        else:
            self.notify("未获得选中文字。请先选中并复制，再使用快捷键。")

    def open_settings(self):
        if self.job:
            self.show_preferred()
            return
        if not self.isVisible() and not (self.compact and self.compact.isVisible()):
            self.show_preferred()
        parent = self.active_surface()
        dialog = SettingsDialog(self.cfg, parent)
        area = parent.screen().availableGeometry()
        dialog.move(area.x() + max(0, (area.width() - dialog.width()) // 2),
                    area.y() + max(0, (area.height() - dialog.height()) // 2))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                set_startup(dialog.value.startup)
                save_settings(dialog.value)
                self.cfg = dialog.value
                self.apply_preferences()
                self.notify("设置已保存 · 当前服务：" + self.cfg.base_url)
            except Exception:
                QMessageBox.warning(self, "设置未完成", "无法写入设置或开机启动项，请检查当前用户权限后重试。")

    def export(self):
        if self.job or not self.result.toPlainText().strip():
            self.notify("请先完成翻译，再导出文件。")
            return
        menu = QMenu(self.active_surface())
        for text, suffix, bilingual in [("双语 Word 文档", ".docx", True), ("双语 PDF 文档", ".pdf", True),
                                       ("双语 HTML 阅读页", ".html", True), ("仅译文 Word", ".docx", False), ("仅译文 TXT", ".txt", False)]:
            action = menu.addAction(text)
            action.triggered.connect(lambda checked=False, ext=suffix, both=bilingual: self.save_export(ext, both))
        from PySide6.QtGui import QCursor
        menu.exec(QCursor.pos())

    def save_export(self, suffix, bilingual):
        import re
        name = re.sub(r'[<>:"/\\|?*]', "_", Path(self.document_title).stem)[:100]
        partial = "_部分译文" if not self.translation_complete else ""
        export_title = self.document_title + ("（部分译文，任务未完成）" if partial else "")
        default = name + partial + ("_双语" if bilingual else "_译文") + suffix
        path, _ = QFileDialog.getSaveFileName(self.active_surface(), "导出翻译", default, f"{suffix[1:].upper()} 文件 (*{suffix})")
        if not path:
            return
        if not path.lower().endswith(suffix):
            path += suffix
        result = self.result.toPlainText().strip()
        canonical = "\n\n".join(translated for _, translated in self.pairs).strip()
        pairs = list(self.pairs) if self.pairs and canonical == result else [(self.source.toPlainText(), result)]
        def write(job):
            output = Path(path)
            # Export through a sibling temporary file to avoid destroying an existing output on failure.
            import tempfile
            with tempfile.NamedTemporaryFile(prefix=".ztrans-", suffix=suffix, dir=output.parent, delete=False) as temp:
                temporary = Path(temp.name)
            try:
                if suffix == ".docx":
                    export_docx(str(temporary), pairs, export_title, bilingual)
                elif suffix == ".pdf":
                    export_pdf(str(temporary), pairs, export_title, bilingual)
                elif suffix == ".html":
                    export_html(str(temporary), pairs, export_title, bilingual)
                else:
                    temporary.write_text(result, encoding="utf-8-sig")
                temporary.replace(output)
            finally:
                temporary.unlink(missing_ok=True)
            return output.name
        self.run_job(write, lambda name: self.notify("已导出：" + name))

    def closeEvent(self, event):
        if self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self.tray_hint:
                self.tray.showMessage("ZTrans 仍在托盘运行", "可继续使用快捷键；完全退出请右键托盘图标 → 退出 ZTrans。")
                self.tray_hint = True
        else:
            if self.job:
                event.ignore()
                self.quit_app()
            else:
                event.accept()

    def quit_app(self):
        if QApplication.activeModalWidget():
            QApplication.activeModalWidget().raise_()
            return
        if self.job:
            self.quitting = True
            self.cancel_job()
            self.show_window()
            return
        if self.hotkeys:
            self.hotkeys.close()
        if self.compact:
            self.compact.remember_geometry()
            self.compact.hide()
            self.compact.wordnote.shutdown()
        self.tray.hide()
        self.source.clear()
        self.result.clear()
        self.pairs = []
        QApplication.instance().quit()


def main():
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZT.ZTrans.1")
    app = QApplication(sys.argv)
    app.setApplicationName("ZTrans")
    app.setOrganizationName("ZTrans")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    if "--smoke-test" in sys.argv:
        from smoke_test import run_smoke
        return run_smoke(app, Path(sys.argv[sys.argv.index("--smoke-test") + 1]))
    if "--compact-test" in sys.argv:
        from test_compact import run_compact_checks
        return run_compact_checks(app, Path(sys.argv[sys.argv.index("--compact-test") + 1]))
    # A named pipe is used only to raise an existing window, never to expose translation APIs.
    name = "ZTrans-" + hashlib.sha256(os.environ.get("USERNAME", "user").encode()).hexdigest()[:12]
    client = QLocalSocket()
    client.connectToServer(name)
    if client.waitForConnected(500):
        command = b"tray" if "--tray" in sys.argv else b"show"
        if "--main" in sys.argv:
            command = b"main"
        elif "--compact" in sys.argv:
            command = b"compact"
        elif "--quit" in sys.argv:
            command = b"quit"
        client.write(command)
        client.waitForBytesWritten(1000)
        client.waitForReadyRead(1500)
        client.disconnectFromServer()
        return 0
    if "--quit" in sys.argv:
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        QMessageBox.warning(None, "ZTrans", "另一个实例正在启动，请稍候从托盘打开。")
        return 1
    window = MainWindow()
    if "--restore-session" in sys.argv:
        transfer = Path(sys.argv[sys.argv.index("--restore-session") + 1])
        try:
            import win32crypt
            recovered = json.loads(win32crypt.CryptUnprotectData(transfer.read_bytes(), None, None, None, 0)[1])
            window.source.setPlainText(recovered.get("source", ""))
            window.result.setPlainText(recovered.get("result", ""))
            window.document_title = "更新前的翻译"
            window.translation_complete = bool(recovered.get("complete", False))
            window.notify("已恢复更新前的原文和译文。")
        except Exception:
            window.notify("更新前会话未能自动恢复，已保留加密恢复文件。")
        else:
            transfer.unlink(missing_ok=True)
    def connection():
        socket = server.nextPendingConnection()
        def read():
            command = bytes(socket.readAll())
            if command == b"main":
                window.show_window()
            elif command == b"compact":
                window.show_compact()
            elif command == b"quit":
                QTimer.singleShot(100, window.quit_app)
            elif command not in (b"tray", b"status"):
                window.show_preferred()
            compact = window.compact
            reply = {"version": APP_VERSION, "busy": window.job is not None,
                     "main_visible": window.isVisible(), "compact_visible": compact.isVisible(),
                     "page": "wordnote" if compact.showing_wordnote() else "translation",
                     "pinned": compact.state.pinned, "screen": compact.screen().name(),
                     "geometry": [compact.x(), compact.y(), compact.width(), compact.height()]}
            socket.write(json.dumps(reply).encode("utf-8"))
            socket.flush()
            socket.disconnectFromServer()
        socket.disconnected.connect(socket.deleteLater)
        socket.readyRead.connect(read)
        if socket.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    if "--tray" not in sys.argv:
        if "--main" in sys.argv:
            window.show_window()
        else:
            window.show_preferred()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
