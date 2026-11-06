"""A small, non-activating translation window with monitor-relative placement."""
from __future__ import annotations

import ctypes
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTextBlockFormat, QTextCursor, QTextOption
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
    QInputDialog, QMenu, QPlainTextEdit, QProgressBar, QPushButton, QSizeGrip, QSizePolicy, QStackedWidget,
    QToolButton, QVBoxLayout, QWidget)

from core import CONFIG_DIR, LANGUAGES, is_loopback
from wordnote import WordNotePane


TRANSLATION_IDLE_MS = 60_000


@dataclass
class WindowState:
    compact_default: bool = True
    pinned: bool = True
    screen_name: str = ""
    x: int = -1
    y: int = -1
    width: int = 440
    height: int = 560


def load_window_state(path: Path) -> WindowState:
    state = WindowState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for name in state.__dataclass_fields__:
            if name in data and type(data[name]) is type(getattr(state, name)):
                setattr(state, name, data[name])
    except (OSError, ValueError, TypeError):
        pass
    return state


def save_window_state(state: WindowState, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def place_rect(area: QRect, state: WindowState) -> QRect:
    """Keep all edges inside the available area, including negative monitor origins."""
    width = min(max(360, state.width), area.width())
    height = min(max(340, state.height), area.height())
    x = state.x if state.x >= 0 else area.width() - width - 24
    y = state.y if state.y >= 0 else 24
    x = max(0, min(x, area.width() - width))
    y = max(0, min(y, area.height() - height))
    return QRect(area.x() + x, area.y() + y, width, height)


def line_icon(name: str, color="#5c666b") -> QIcon:
    pix = QPixmap(40, 40)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(2, 2)
    p.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name == "pin":
        path = QPainterPath()
        path.moveTo(7, 3); path.lineTo(13, 3); path.lineTo(12, 8)
        path.lineTo(15, 12); path.lineTo(5, 12); path.lineTo(8, 8); path.closeSubpath()
        p.drawPath(path); p.drawLine(10, 12, 10, 17)
    elif name == "close":
        p.drawLine(5, 5, 15, 15); p.drawLine(15, 5, 5, 15)
    elif name == "expand":
        p.drawRect(4, 6, 10, 10); p.drawLine(10, 3, 17, 3)
        p.drawLine(17, 3, 17, 10); p.drawLine(17, 3, 10, 10)
    elif name == "screen":
        p.drawRoundedRect(2, 3, 16, 11, 1.5, 1.5)
        p.drawLine(10, 14, 10, 17); p.drawLine(6, 17, 14, 17)
    elif name == "settings":
        p.drawEllipse(5, 5, 10, 10); p.drawEllipse(8, 8, 4, 4)
        for angle in range(0, 360, 45):
            p.save(); p.translate(10, 10); p.rotate(angle); p.drawLine(0, -5, 0, -8); p.restore()
    elif name == "copy":
        p.drawRoundedRect(7, 6, 10, 12, 1, 1)
        path = QPainterPath(); path.moveTo(13, 3); path.lineTo(3, 3); path.lineTo(3, 14)
        p.drawPath(path)
    elif name == "swap":
        p.drawLine(3, 7, 17, 7); p.drawLine(3, 7, 7, 3)
        p.drawLine(17, 13, 3, 13); p.drawLine(17, 13, 13, 17)
    elif name == "retry":
        p.drawArc(4, 4, 12, 12, 40 * 16, 280 * 16)
        p.drawLine(16, 3, 16, 8); p.drawLine(16, 8, 11, 8)
    p.end()
    return QIcon(pix)


COMPACT_STYLE = """
QWidget#compactWindow { background: transparent; }
QFrame#compactShell { background: #ffffff; border: 1px solid #d7dcde; border-radius: 13px; }
QFrame#compactShell QLabel { border: none; background: transparent; }
QFrame#languageBar { background: #eeeeef; border: none; border-radius: 9px; }
QFrame#translationCard { background: #efeff0; border: none; border-radius: 9px; }
QFrame#modelBar { background: #e3e5e6; border: none; border-radius: 8px; }
QLabel#compactModel { color: #303b40; font-weight: 600; font-size: 12px; }
QLabel#compactBrand { color: #969da1; font-size: 12px; }
QComboBox { border: none; border-radius: 6px; background: transparent; padding: 7px 9px; font-size: 13px; }
QComboBox:hover { background: #e4e6e7; }
QComboBox QAbstractItemView { background: white; color: #25343a; selection-background-color: #dcefe8; }
QToolButton { background: transparent; border: none; border-radius: 6px; padding: 5px; color: #637077; }
QToolButton:hover { background: #e4e8e8; }
QToolButton:checked { background: #dcefe8; color: #137769; }
QToolButton:disabled { color: #acb2b5; }
QPlainTextEdit#compactResult { background: transparent; border: none; padding: 8px 11px; color: #535c61; }
QPlainTextEdit#compactSource { background: #fafbfb; border: 1px solid #e3e7e7; border-radius: 7px; padding: 7px; }
QPushButton#compactTranslate { background: #e1eee9; color: #176e60; border: none; border-radius: 6px; padding: 6px 11px; }
QPushButton#compactTranslate:hover { background: #cce5db; }
QPushButton#compactTranslate:disabled { background: #eaeded; color: #a0a9aa; }
QLabel#compactStatus { color: #9aa2a6; font-size: 11px; }
QProgressBar { background: #e7ecea; max-height: 2px; border: none; }
QProgressBar::chunk { background: #358f7c; }
"""


class CompactWindow(QWidget):
    def __init__(self, controller, state_path=None, persist=True):
        self.state_path = Path(state_path) if state_path is not None else CONFIG_DIR / "window.json"
        self.state = load_window_state(self.state_path)
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self.state.pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.controller = controller
        self.persist = persist
        self.positioned = False
        self.placing = False
        self.follow_output = True
        self._drag_offset = None
        self.result_viewport = None
        self._connected_screens = set()
        self.setObjectName("compactWindow")
        self.setWindowTitle("ZTrans · 悬浮翻译")
        self.setWindowIcon(controller.windowIcon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(360, 340)
        self.resize(440, 560)
        self.setStyleSheet(COMPACT_STYLE)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.remember_geometry)
        self.idle_timer = QTimer(self, singleShot=True, interval=TRANSLATION_IDLE_MS,
                                timerType=Qt.TimerType.PreciseTimer)
        self.idle_timer.timeout.connect(self.show_wordnote)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        shell = QFrame()
        shell.setObjectName("compactShell")
        outer.addWidget(shell)
        body = QVBoxLayout(shell)
        body.setContentsMargins(12, 9, 12, 9)
        body.setSpacing(10)
        self.toolbar = QWidget()
        top = QHBoxLayout(self.toolbar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        self.pin = self.tool("pin", "置顶 / 取消置顶", self.toggle_pin)
        self.pin.setCheckable(True)
        self.pin.setChecked(self.state.pinned)
        top.addWidget(self.pin)
        brand = QLabel("ZTrans")
        brand.setObjectName("compactBrand")
        brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        top.addWidget(brand)
        top.addStretch()
        self.back_to_translation = QToolButton(text="翻译")
        self.back_to_translation.setToolTip("返回翻译界面 · F1 翻译选中文字")
        self.back_to_translation.clicked.connect(self.show_translation)
        self.back_to_translation.hide()
        top.addWidget(self.back_to_translation)
        self.idle_paste_button = QPushButton("粘贴翻译")
        self.idle_paste_button.setObjectName("compactTranslate")
        self.idle_paste_button.clicked.connect(controller.translate_clipboard)
        self.idle_paste_button.hide()
        top.addWidget(self.idle_paste_button)
        self.monitor_button = self.tool("screen", "选择显示屏 / 重置位置", self.monitor_menu)
        top.addWidget(self.monitor_button)
        self.actions_button = self.tool("expand", "文档 / 网页 / 导出", self.actions_menu)
        top.addWidget(self.actions_button)
        self.settings_button = self.tool("settings", "设置与隐私", controller.open_settings)
        top.addWidget(self.settings_button)
        top.addWidget(self.tool("close", "收起到托盘", self.close))
        body.addWidget(self.toolbar)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self.translation = QWidget()
        translation_layout = QVBoxLayout(self.translation)
        translation_layout.setContentsMargins(0, 0, 0, 0)
        translation_layout.setSpacing(10)
        self.pages.addWidget(self.translation)
        self.wordnote = WordNotePane(self.pages, self.state_path.parent / "wordnote")
        self.pages.addWidget(self.wordnote)
        language_bar = QFrame()
        language_bar.setObjectName("languageBar")
        languages = QHBoxLayout(language_bar)
        languages.setContentsMargins(5, 0, 5, 0)
        languages.setSpacing(3)
        self.source_lang = QComboBox()
        self.source_lang.addItems(["自动识别"] + LANGUAGES)
        self.source_lang.setCurrentText(controller.source_lang.currentText())
        self.target_lang = QComboBox()
        self.target_lang.addItems(LANGUAGES)
        self.target_lang.setCurrentText(controller.target_lang.currentText())
        self.swap = self.tool("swap", "交换语言", controller.swap_languages)
        languages.addWidget(self.source_lang, 1)
        languages.addWidget(self.swap)
        languages.addWidget(self.target_lang, 1)
        translation_layout.addWidget(language_bar)
        self.source_lang.currentTextChanged.connect(controller.source_lang.setCurrentText)
        self.target_lang.currentTextChanged.connect(controller.target_lang.setCurrentText)
        controller.source_lang.currentTextChanged.connect(self.source_lang.setCurrentText)
        controller.target_lang.currentTextChanged.connect(self.target_lang.setCurrentText)
        self.source = QPlainTextEdit()
        self.source.setObjectName("compactSource")
        self.source.setPlainText(controller.source.toPlainText())
        self.source.textChanged.connect(self.source_edited)
        controller.source.textChanged.connect(self.sync_source)
        self.source.setPlaceholderText("粘贴或输入原文，Ctrl + Enter 翻译")
        self.source.setFixedHeight(120)
        self.source.hide()
        translation_layout.addWidget(self.source)
        card = QFrame()
        card.setObjectName("translationCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(0)
        model_bar = QFrame()
        model_bar.setObjectName("modelBar")
        model_row = QHBoxLayout(model_bar)
        model_row.setContentsMargins(11, 4, 7, 4)
        self.model = QLabel()
        self.model.setObjectName("compactModel")
        self.model.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        model_row.addWidget(self.model, 1)
        self.source_toggle = QToolButton()
        self.source_toggle.setText("原文 ▾")
        self.source_toggle.setToolTip("展开 / 收起原文")
        self.source_toggle.setCheckable(True)
        self.source_toggle.toggled.connect(self.toggle_source)
        model_row.addWidget(self.source_toggle)
        layout.addWidget(model_bar)
        self.result = QPlainTextEdit()
        self.result.setObjectName("compactResult")
        self.result.setPlainText(controller.result.toPlainText())
        self.result.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.result.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("选中文字，按 F1。\n译文会直接显示在这里。\n\n也可点击下方“粘贴翻译”。\n\n拖动顶部移动窗口；拖动右下角调整大小。")
        self.result_viewport = self.result.viewport()
        self.result.verticalScrollBar().actionTriggered.connect(lambda _: QTimer.singleShot(0, self.update_follow))
        controller.result.textChanged.connect(self.output_changed)
        layout.addWidget(self.result, 1)
        actions = QHBoxLayout()
        actions.setContentsMargins(9, 2, 9, 3)
        actions.setSpacing(5)
        self.copy = self.tool("copy", "复制译文", controller.copy_result)
        actions.addWidget(self.copy)
        self.retry = self.tool("retry", "重新翻译当前原文", controller.translate)
        actions.addWidget(self.retry)
        actions.addStretch()
        self.stop = QPushButton("停止")
        self.stop.clicked.connect(controller.cancel_job)
        self.stop.hide()
        actions.addWidget(self.stop)
        self.translate_button = QPushButton("粘贴翻译")
        self.translate_button.setObjectName("compactTranslate")
        self.translate_button.clicked.connect(self.translate_clicked)
        actions.addWidget(self.translate_button)
        layout.addLayout(actions)
        translation_layout.addWidget(card, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        translation_layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("本机模型 · 不自动保存历史")
        self.status.setObjectName("compactStatus")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        translation_layout.addWidget(self.status)
        bottom.addStretch()
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(14, 14)
        bottom.addWidget(self.grip)
        body.addLayout(bottom)
        from PySide6.QtGui import QShortcut, QKeySequence
        self.shortcut_translate = QShortcut(QKeySequence("Ctrl+Return"), self, controller.translate)
        self.shortcut_stop = QShortcut(QKeySequence("Escape"), self, controller.cancel_job)
        self.shortcut_open = QShortcut(QKeySequence("Ctrl+O"), self, controller.choose_file)
        self.shortcut_export = QShortcut(QKeySequence("Ctrl+Shift+S"), self, controller.export)
        self.setAcceptDrops(True)
        app = QApplication.instance()
        app.installEventFilter(self)
        app.screenAdded.connect(self.screens_changed)
        app.screenRemoved.connect(self.screens_changed)
        self.connect_screens()
        self.apply_preferences()

    def tool(self, name, tooltip, callback):
        widget = QToolButton()
        widget.setIcon(line_icon(name))
        widget.setIconSize(QSize(20, 20))
        widget.setFixedSize(30, 30)
        widget.setToolTip(tooltip)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.clicked.connect(callback)
        return widget

    def apply_preferences(self):
        cfg = self.controller.cfg
        local = is_loopback(cfg.base_url)
        provider = "Ollama" if cfg.provider == "ollama" else "API"
        self.model.setText(f"{'●' if local else '◉'}  {provider} · {cfg.model}")
        self.model.setToolTip(f"内容发送到：{cfg.base_url}\n{'本机接口' if local else '远程服务'}")
        self.model.setStyleSheet("color: #303b40;" if local else "color: #a46a17;")
        font = QFont("Microsoft YaHei UI", max(11, min(22, cfg.font_size)))
        self.result.setFont(font)
        self.source.setFont(font)
        for edit in (self.result, self.source):
            edit.setStyleSheet(f"font-family: 'Microsoft YaHei UI'; font-size: {font.pointSize()}pt;")
        self.format_result()

    def format_result(self):
        cursor = QTextCursor(self.result.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(130, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)

    def selected_screen(self):
        app = QApplication.instance()
        screens = app.screens()
        matched = next((s for s in screens if s.name() == self.state.screen_name), None)
        return matched or next((s for s in screens if s != app.primaryScreen()), app.primaryScreen())

    def restore_placement(self):
        self.placing = True
        screen = self.selected_screen()
        self.setGeometry(place_rect(screen.availableGeometry(), self.state))
        self.positioned = True
        QTimer.singleShot(0, self.finish_placing)

    def finish_placing(self):
        self.placing = False

    def show_compact(self, activate=True):
        if not self.positioned:
            self.restore_placement()
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, not activate)
        self.show()
        self.restart_idle_timer()
        # Explicitly handle processes launched with Windows STARTF_USESHOWWINDOW/SW_HIDE.
        if sys.platform == "win32":
            ctypes.windll.user32.ShowWindow(int(self.winId()), 9 if activate else 4)
        self.raise_()
        if activate:
            self.activateWindow()

    def showing_wordnote(self):
        return self.pages.currentWidget() is self.wordnote

    def show_translation(self):
        self.back_to_translation.hide()
        self.idle_paste_button.hide()
        self.actions_button.show()
        self.pages.setCurrentWidget(self.translation)
        self.restart_idle_timer()

    def restart_idle_timer(self):
        if self.isVisible() and not self.showing_wordnote() and self.controller.job is None:
            self.idle_timer.start(TRANSLATION_IDLE_MS)

    def show_wordnote(self):
        if not self.isVisible() or self.controller.job is not None:
            return
        if (self.controller._selection_pending or QApplication.activeModalWidget()
                or QApplication.activePopupWidget()):
            self.idle_timer.start(TRANSLATION_IDLE_MS)
            return
        self.idle_timer.stop()
        self.pages.setCurrentWidget(self.wordnote)
        self.actions_button.hide()
        self.back_to_translation.show()
        self.idle_paste_button.show()

    def remember_geometry(self):
        if not self.positioned or self.placing or not self.isVisible():
            return
        area_screen = QApplication.screenAt(self.geometry().center()) or self.selected_screen()
        area = area_screen.availableGeometry()
        self.state.screen_name = area_screen.name()
        self.state.x = self.x() - area.x()
        self.state.y = self.y() - area.y()
        self.state.width = self.width()
        self.state.height = self.height()
        self.save_state()

    def save_state(self):
        if self.persist:
            try:
                save_window_state(self.state, self.state_path)
            except OSError:
                self.set_status("窗口位置暂时无法保存；本次仍可正常使用。")

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.positioned and not self.placing:
            self.save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.positioned and not self.placing:
            self.save_timer.start()

    def toggle_pin(self, pinned):
        self.remember_geometry()
        self.state.pinned = pinned
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)
        self.setGeometry(geometry)
        self.show_compact(activate=False)
        self.save_state()

    def toggle_source(self, checked):
        self.source.setVisible(checked)
        self.source_toggle.setText("原文 ▴" if checked else "原文 ▾")
        self.translate_button.setText("翻译原文" if checked else "粘贴翻译")

    def translate_clicked(self):
        if self.source.isVisible():
            self.controller.translate()
        else:
            self.controller.translate_clipboard()

    def set_busy(self, busy):
        if busy:
            self.show_translation()
            self.idle_timer.stop()
        else:
            self.restart_idle_timer()
        for widget in (self.source_lang, self.target_lang, self.swap, self.settings_button,
                       self.retry, self.translate_button):
            widget.setEnabled(not busy)
        self.source.setReadOnly(busy)
        self.stop.setVisible(busy)
        self.stop.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 100)

    def set_status(self, message):
        self.status.setText(message)
        self.status.setToolTip(message)

    def set_progress(self, value):
        self.progress.setRange(0, 100)
        self.progress.setValue(value)

    def update_follow(self):
        bar = self.result.verticalScrollBar()
        self.follow_output = bar.value() >= bar.maximum() - 15

    def output_changed(self):
        # Each editor needs its own document layout: a shared QTextDocument uses one
        # wrap width and clips text when the main window and the small window differ.
        text = self.controller.result.toPlainText()
        current = self.result.toPlainText()
        if text != current:
            bar = self.result.verticalScrollBar()
            position = bar.value()
            if text.startswith(current):
                cursor = self.result.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(text[len(current):])
            else:
                self.result.setPlainText(text)
            if not current or not text.startswith(current):
                self.format_result()
            if not self.follow_output:
                bar.setValue(position)
        if self.follow_output:
            QTimer.singleShot(0, self.scroll_to_end)

    def sync_source(self):
        text = self.controller.source.toPlainText()
        if self.source.toPlainText() != text:
            self.source.setPlainText(text)

    def source_edited(self):
        text = self.source.toPlainText()
        if self.controller.source.toPlainText() != text:
            self.controller.source.setPlainText(text)

    def scroll_to_end(self):
        if self.follow_output:
            bar = self.result.verticalScrollBar()
            bar.setValue(bar.maximum())

    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel)
                and isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))):
            self.restart_idle_timer()
        if watched is self.toolbar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self.windowHandle() and self.windowHandle().startSystemMove():
                    return True
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
        if watched is self.result_viewport and event.type() == QEvent.Type.Wheel:
            if event.angleDelta().y() > 0:
                self.follow_output = False
            else:
                QTimer.singleShot(0, self.update_follow)
        return super().eventFilter(watched, event)

    def monitor_menu(self):
        menu = QMenu(self)
        app = QApplication.instance()
        for screen in app.screens():
            name = screen.name()
            action = menu.addAction(("主屏" if screen == app.primaryScreen() else "副屏") + " · " + name)
            action.setCheckable(True)
            action.setChecked(screen == self.screen())
            action.triggered.connect(lambda checked=False, n=name: self.move_to_screen(n))
        menu.addSeparator()
        menu.addAction("回到副屏右上角", lambda: self.move_to_screen(""))
        menu.exec(self.monitor_button.mapToGlobal(QPoint(0, self.monitor_button.height())))

    def actions_menu(self):
        menu = QMenu(self)
        busy = self.controller.job is not None
        for title, callback in [("导入 PDF / Word / 文本…", self.controller.choose_file),
                                ("读取网页正文…", self.read_webpage),
                                ("导出译文…", self.controller.export),
                                ("预览修复断行…", self.controller.preview_repair),
                                ("清空当前内容", self.controller.clear)]:
            action = menu.addAction(title, callback)
            action.setEnabled(not busy)
        menu.addSeparator()
        repair = menu.addAction("翻译前修复多余换行")
        repair.setCheckable(True)
        repair.setChecked(self.controller.repair_check.isChecked())
        repair.setEnabled(not busy)
        repair.toggled.connect(self.controller.repair_check.setChecked)
        styles = menu.addMenu("翻译风格")
        for text in ["忠实翻译", "学术论文", "自然流畅"]:
            action = styles.addAction(text)
            action.setCheckable(True)
            action.setChecked(self.controller.style.currentText() == text)
            action.setEnabled(not busy)
            action.triggered.connect(lambda checked=False, value=text: self.controller.style.setCurrentText(value))
        menu.exec(self.actions_button.mapToGlobal(QPoint(0, self.actions_button.height())))

    def read_webpage(self):
        if self.controller.job:
            return
        url, accepted = QInputDialog.getText(self, "读取网页正文", "网页地址", text=self.controller.web_url.text())
        if accepted and url.strip():
            self.controller.web_url.setText(url.strip())
            self.controller.fetch_page()

    def dragEnterEvent(self, event):
        if not self.controller.job and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not self.controller.job and event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                self.controller.load_file(url.toLocalFile())
                self.source_toggle.setChecked(True)
                event.acceptProposedAction()

    def set_default(self, checked):
        self.state.compact_default = checked
        self.save_state()

    def move_to_screen(self, name):
        self.state.screen_name = name
        self.state.x = self.state.y = -1
        self.restore_placement()
        self.show_compact()
        self.save_state()

    def connect_screens(self):
        for screen in QApplication.screens():
            identity = id(screen)
            if identity not in self._connected_screens:
                self._connected_screens.add(identity)
                screen.availableGeometryChanged.connect(self.screens_changed)

    def screens_changed(self, *args):
        self.connect_screens()
        if self.positioned:
            QTimer.singleShot(150, self.restore_placement)

    def hideEvent(self, event):
        self.idle_timer.stop()
        self.save_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.remember_geometry()
        event.ignore()
        self.hide()
