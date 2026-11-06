from __future__ import annotations

import ctypes
import hashlib
from contextlib import contextmanager
from pathlib import Path
from queue import Empty
from time import monotonic, strftime
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from wordnote_store import (
    Rotation, Speech, Store, fill_missing_details,
    lookup_american_ipa, lookup_chinese_meaning,
)


@contextmanager
def wordnote_writer(directory):
    # Match the existing 拾词 app's session mutex so both editors cannot overwrite a snapshot.
    identity = hashlib.sha256(str(directory.resolve()).casefold().encode()).hexdigest()[:24]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, "Local\\WordNote-Python-" + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if ctypes.get_last_error() == 183:
            raise ValueError("独立拾词窗口仍在运行。关闭该窗口后，即可在 ZTrans 编辑同一份单词本。")
        yield
    finally:
        kernel.CloseHandle(handle)


def button(text, action):
    control = QPushButton(text)
    control.clicked.connect(action)
    return control


class WordNotePane(QWidget):
    def __init__(self, parent, directory):
        super().__init__(parent)
        self.directory = Path(directory)
        self.data = None
        self.file_stamp = None
        self.error = ""
        self.rotation = Rotation()
        self.batch = []
        self.revealed = None
        self.hold = False
        self.speech = None
        self.speech_error = ""
        self.last_tick = monotonic()
        self.setObjectName("wordNote")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(4)
        self.layout_style = None
        header = QHBoxLayout()
        heading = QLabel("拾词")
        heading.setObjectName("wordNoteHeading")
        header.addWidget(heading)
        header.addWidget(QLabel("本轮单词"))
        header.addStretch()
        header.addWidget(button("＋ 记词", lambda: self.open_book(True)))
        layout.addLayout(header)
        self.cards = QVBoxLayout()
        layout.addLayout(self.cards, 1)
        self.rows = []
        self.card_layouts = []
        for index in range(Rotation.BATCH_SIZE):
            card = QFrame()
            card.setObjectName("reviewCard")
            # The card switches to one line before reaching its minimum height.
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
            card.setMinimumHeight(25)
            card.setMaximumHeight(116)
            row = QHBoxLayout(card)
            row.setSizeConstraint(QHBoxLayout.SizeConstraint.SetNoConstraint)
            row.setSpacing(7)
            text_block = QWidget(card)
            text = QVBoxLayout(text_block)
            text.setContentsMargins(0, 0, 0, 0)
            text.setSpacing(0)
            word = button("", lambda checked=False, i=index: self.toggle_meaning(i))
            word.setObjectName("reviewWord")
            word.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            detail = QLabel()
            detail.setObjectName("reviewDetail")
            detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            text.addWidget(word)
            text.addWidget(detail)
            row.addWidget(text_block, 1, Qt.AlignmentFlag.AlignVCenter)
            reveal = button("释义", lambda checked=False, i=index: self.toggle_meaning(i))
            speak = button("🔊", lambda checked=False, i=index: self.speak(self.batch[i]["word"]))
            speak.setAccessibleName("朗读单词")
            speak.setToolTip("美式发音")
            row.addWidget(reveal, alignment=Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(speak, alignment=Qt.AlignmentFlag.AlignVCenter)
            self.cards.addWidget(card, 1)
            self.rows.append((word, detail, reveal, speak))
            self.card_layouts.append((card, row, text))
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.all_words = button("全部单词", lambda: self.open_book())
        self.hold_button = button("固定", self.toggle_hold)
        self.next_button = button("换一批 →", self.next_batch)
        footer.addWidget(self.all_words)
        footer.addStretch()
        footer.addWidget(self.hold_button)
        footer.addWidget(self.next_button)
        layout.addLayout(footer)
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self.tick)
        QShortcut(QKeySequence("Ctrl+N"), self, lambda: self.open_book(True),
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+L"), self, self.open_book,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Right"), self, self.next_batch,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def refresh(self):
        path = self.directory / "words.json"
        try:
            try:
                stat = path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                stamp = (0, 0)
            if stamp != self.file_stamp:
                try:
                    data = Store.read(path) if stamp != (0, 0) else {"words": [], "settings": {}}
                except (ValueError, OSError):
                    data = Store.read(path.with_suffix(".json.bak"))
                self.file_stamp = stamp
                self.load_data(data)
            self.error = ""
        except (OSError, ValueError) as exc:
            self.error = "读取单词本失败：" + str(exc)

    def load_data(self, data):
        self.data = data
        by_id = {entry["id"]: entry for entry in data["words"]}
        self.batch = [by_id[entry["id"]] for entry in self.batch if entry["id"] in by_id]
        remaining = [entry for entry in data["words"] if entry not in self.batch]
        self.batch.extend(self.rotation.pick_batch(remaining, size=Rotation.BATCH_SIZE - len(self.batch)))
        self.render()

    def fit_cards(self):
        compact = self.height() < 445
        dark = bool(self.data and self.data["settings"].get("dark"))
        if self.layout_style == (compact, dark):
            return
        self.layout_style = compact, dark
        self.cards.setSpacing(3 if compact else 6)
        for _, row, text in self.card_layouts:
            row.setContentsMargins(*(8, 0, 7, 0) if compact else (13, 4, 10, 4))
            text.setDirection(QBoxLayout.Direction.LeftToRight if compact else QBoxLayout.Direction.TopToBottom)
            text.setSpacing(7 if compact else 1)
            text.setStretch(0, 4 if compact else 0)
            text.setStretch(1, 5 if compact else 0)
        background, border, ink, muted = (
            ("#35473c", "#53675a", "#f0f5ed", "#cfdfd0") if dark
            else ("#f2f6f0", "#e0e9de", "#293d35", "#51705e")
        )
        self.setStyleSheet(f'''
            QFrame#reviewCard {{ background: {background}; border: 1px solid {border}; border-radius: 9px; }}
            QPushButton {{ padding: {'2px 7px' if compact else '4px 9px'}; }}
            QLabel#wordNoteHeading {{ font-size: 18px; font-weight: bold; color: #51705e; }}
            QPushButton#reviewWord {{ background: transparent; border: none; color: {ink};
                text-align: left; font-family: Georgia; font-size: {15 if compact else 23}px;
                font-weight: bold; padding: 0; }}
            QPushButton#reviewWord:hover {{ text-decoration: underline; }}
            QLabel#reviewDetail {{ color: {muted}; font-size: {12 if compact else 14}px; }}
        ''')

    def fit_text(self):
        for index, entry in enumerate(self.batch):
            word, detail, _, _ = self.rows[index]
            word.setText(word.fontMetrics().elidedText(entry["word"], Qt.TextElideMode.ElideRight, word.width()))
            value = entry["meaning"] if self.revealed == entry["id"] else entry["phonetic"]
            value = " ".join(value.split())
            detail.setText(detail.fontMetrics().elidedText(value, Qt.TextElideMode.ElideRight, detail.width()))

    def render(self):
        count = len(self.data["words"]) if self.data else 0
        self.fit_cards()
        for index, (word, detail, reveal, _) in enumerate(self.rows):
            entry = self.batch[index] if index < len(self.batch) else None
            self.card_layouts[index][0].setVisible(entry is not None)
            if entry:
                word.setAccessibleName(entry["word"])
                word.setToolTip(entry["word"])
                shown = self.revealed == entry["id"]
                detail.setToolTip(entry["meaning"] if shown else entry["phonetic"])
                reveal.setText("收起" if shown else "释义")
        QTimer.singleShot(0, self.fit_text)
        self.all_words.setText(f"全部单词（{count}）")
        self.hold_button.setEnabled(count > Rotation.BATCH_SIZE)
        self.next_button.setEnabled(count > Rotation.BATCH_SIZE)
        self.update_status()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_cards()
        QTimer.singleShot(0, self.fit_text)

    def update_status(self):
        count = len(self.data["words"]) if self.data else 0
        if self.error or self.speech_error:
            note = self.error or self.speech_error
        elif not count:
            note = "点「＋ 记词」添加第一个单词"
        elif count <= Rotation.BATCH_SIZE:
            note = f"已显示全部 {count} 个单词"
        elif self.hold:
            note = "已固定当前这批单词"
        else:
            seconds = int(self.rotation.remaining + .999)
            note = f"{len(self.batch)} / {count} 个词 · {seconds // 60:02}:{seconds % 60:02} 后换批"
        self.status.setText(note)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.last_tick = monotonic()
        self.render()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def tick(self):
        now = monotonic()
        self.refresh()
        paused = (self.hold or not self.next_button.isEnabled() or self.underMouse()
                  or QApplication.activeModalWidget() is not None)
        if self.rotation.advance(now - self.last_tick, paused):
            self.next_batch()
        self.last_tick = now
        if self.speech:
            while True:
                try:
                    kind, value = self.speech.events.get_nowait()
                except Empty:
                    break
                if kind in ("error", "unavailable"):
                    self.speech_error = "美式发音暂不可用：" + value
                elif kind == "spoken":
                    self.speech_error = ""
        self.update_status()

    def toggle_meaning(self, index):
        entry_id = self.batch[index]["id"]
        self.revealed = None if self.revealed == entry_id else entry_id
        self.render()

    def toggle_hold(self):
        self.hold = not self.hold
        self.hold_button.setText("已固定" if self.hold else "固定")
        self.update_status()

    def next_batch(self):
        if self.next_button.isEnabled():
            self.batch = self.rotation.pick_batch(self.data["words"], self.batch)
            self.revealed = None
            self.rotation.reset()
            self.render()

    def speak(self, word):
        if not word.strip():
            return
        if self.speech is None:
            self.speech = Speech()
        voice = self.data["settings"].get("voice", "") if self.data else ""
        self.speech.commands.put((word.strip(), voice))

    def shutdown(self):
        if self.speech:
            self.speech.commands.put(None)

    def open_book(self, new=False):
        try:
            with wordnote_writer(self.directory):
                store = Store(self.directory)
                dialog = WordNoteEditor(self, store, store.load(), new)
                try:
                    dialog.exec()
                finally:
                    dialog.deleteLater()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "拾词单词本", str(exc))
        self.refresh()
        self.update_status()


class WordNoteEditor(QDialog):
    def __init__(self, pane, store, data, new):
        super().__init__(pane.window())
        self.pane, self.store, self.data = pane, store, data
        self.original = None
        self.deleted = None
        self.auto_details = ("", "")
        self.setWindowTitle("拾词 · 我的单词本")
        self.resize(720, 465)
        body = QHBoxLayout(self)
        left, right = QVBoxLayout(), QVBoxLayout()
        body.addLayout(left, 2)
        body.addLayout(right, 3)
        self.search = QLineEdit(placeholderText="搜索单词或释义")
        self.search.textChanged.connect(self.refresh_list)
        left.addWidget(self.search)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.select_row)
        left.addWidget(self.list)
        tools = QHBoxLayout()
        self.undo = button("撤销删除", self.undo_delete)
        self.undo.setEnabled(False)
        for control in (button("导入", self.import_words), button("导出", self.export_words), self.undo):
            # Enter in the word fields already saves via returnPressed.
            control.setAutoDefault(False)
            tools.addWidget(control)
        left.addLayout(tools)
        form = QFormLayout()
        self.word = QLineEdit()
        self.phonetic = QLineEdit()
        self.meaning = QPlainTextEdit()
        self.learned = QCheckBox("这个词已经读熟了")
        form.addRow("单词", self.word)
        form.addRow("美式音标", self.phonetic)
        form.addRow("中文释义", self.meaning)
        form.addRow("", self.learned)
        right.addLayout(form, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        right.addWidget(self.status)
        actions = QHBoxLayout()
        self.delete = button("删除", self.delete_word)
        for control in (button("＋ 记词", self.add_word), button("试听", lambda: pane.speak(self.word.text())),
                        self.delete, button("保存单词", self.save), button("返回", self.reject)):
            control.setAutoDefault(False)
            actions.addWidget(control)
        right.addLayout(actions)
        self.word.textEdited.connect(self.autofill)
        self.word.returnPressed.connect(self.save)
        self.phonetic.returnPressed.connect(self.save)
        QShortcut(QKeySequence("Ctrl+S"), self, self.save)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.save)
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_word)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        first = next(iter(data["words"]), None)
        self.fill(None if new else first)

    def refresh_list(self):
        query = self.search.text().strip().casefold()
        self.filtered = [entry for entry in self.data["words"]
                         if query in entry["word"].casefold() or query in entry["meaning"].casefold()]
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([entry["word"] for entry in self.filtered])
        index = next((i for i, entry in enumerate(self.filtered) if entry == self.original), -1)
        self.list.setCurrentRow(index)
        self.list.blockSignals(False)

    def select_row(self, index):
        if index >= 0:
            selected = self.filtered[index]
            if self.can_leave():
                self.fill(selected)
            else:
                self.refresh_list()

    def add_word(self):
        if self.can_leave():
            self.fill(None)

    def fill(self, entry):
        self.original = entry
        values = entry or {"word": "", "phonetic": "", "meaning": "", "learned": False}
        self.word.setText(values["word"])
        self.phonetic.setText(values["phonetic"])
        self.meaning.setPlainText(values["meaning"])
        self.learned.setChecked(values["learned"])
        self.auto_details = ("", "")
        self.delete.setEnabled(entry is not None)
        self.status.setText("输入单词后自动查找音标和中文释义，均可修改。")
        self.refresh_list()
        self.word.setFocus()

    def autofill(self, word):
        phonetic, meaning = self.auto_details
        if self.phonetic.text().strip() in ("", phonetic):
            phonetic = lookup_american_ipa(word)
            self.phonetic.setText(phonetic)
        if self.meaning.toPlainText().strip() in ("", meaning):
            meaning = lookup_chinese_meaning(word)
            self.meaning.setPlainText(meaning)
        self.auto_details = (phonetic, meaning)

    def draft(self):
        return dict(word=self.word.text().strip(), phonetic=self.phonetic.text().strip(),
                    meaning=self.meaning.toPlainText().strip(), learned=self.learned.isChecked())

    def can_leave(self):
        draft = self.draft()
        if self.original:
            dirty = any(self.original[key] != value for key, value in draft.items())
        else:
            dirty = any(draft.values())
        if not dirty:
            return True
        choice = QMessageBox.question(self, "拾词", "保存当前词条的修改？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                                      QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        return choice == QMessageBox.StandardButton.No or (choice == QMessageBox.StandardButton.Yes and self.save())

    def reject(self):
        if self.can_leave():
            super().reject()

    def commit(self, words):
        try:
            self.data = self.store.save(dict(self.data, words=words))
            self.pane.load_data(self.data)
            return True
        except (OSError, ValueError) as exc:
            self.status.setText("保存失败，编辑内容已保留：" + str(exc))
            return False

    def save(self):
        draft = self.draft()
        if not draft["word"]:
            self.status.setText("先输入单词，再保存。")
            return False
        words = list(self.data["words"])
        original_id = self.original["id"] if self.original else None
        same = next((entry for entry in words if entry["id"] != original_id and
                     entry["word"].casefold() == draft["word"].casefold()), None)
        if same:
            phonetic, meaning = self.auto_details
            if (self.original is None and draft["phonetic"] in ("", phonetic, same["phonetic"])
                    and draft["meaning"] in ("", meaning, same["meaning"])
                    and (not draft["learned"] or same["learned"])):
                self.fill(same)
                self.status.setText("该单词已保存，已打开原词条。")
                return True
            self.status.setText("已有同名单词，请搜索并编辑原词条。")
            return False
        entry = dict(draft, id=original_id or uuid4().hex)
        if self.original:
            words[words.index(self.original)] = entry
        else:
            words.insert(0, entry)
        if not self.commit(words):
            return False
        saved = next(item for item in self.data["words"] if item["id"] == entry["id"])
        self.pane.batch = [saved] + [item for item in self.pane.batch if item["id"] != saved["id"]][:Rotation.BATCH_SIZE - 1]
        self.pane.rotation.reset()
        self.pane.render()
        self.fill(saved)
        self.status.setText("已保存到本机。")
        return True

    def delete_word(self):
        entry = self.original
        if entry and self.commit([word for word in self.data["words"] if word["id"] != entry["id"]]):
            self.deleted = entry
            self.undo.setEnabled(True)
            self.fill(None)
            self.status.setText("已删除，可以撤销。")

    def undo_delete(self):
        if not self.can_leave():
            return
        if any(item["word"].casefold() == self.deleted["word"].casefold() for item in self.data["words"]):
            self.status.setText("已有同名单词，无法重复恢复。")
        elif self.commit([self.deleted, *self.data["words"]]):
            self.fill(self.deleted)
            self.deleted = None
            self.undo.setEnabled(False)
            self.status.setText("已恢复词条。")

    def import_words(self):
        if not self.can_leave():
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入单词本", "", "单词本 (*.json *.txt)")
        if not path:
            return
        try:
            path = Path(path)
            if path.suffix.lower() == ".txt":
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("文件超过 16 MB。")
                entries = {}
                for line in path.read_text(encoding="utf-8-sig").splitlines():
                    word, meaning, phonetic, *_ = line.split("\t") + ["", ""]
                    if word.strip():
                        entries.setdefault(word.strip().casefold(), dict(word=word, meaning=meaning, phonetic=phonetic))
                incoming = {"version": 1, "words": list(entries.values())}
            else:
                incoming = Store.read(path)
            words = Store.merge(self.data, incoming)["words"]
            added = len(words) - len(self.data["words"])
            fill_missing_details(words[-added:] if added else [])
            if added and not self.commit(words):
                return
            self.fill(self.original)
            self.status.setText(f"已导入 {added} 个新单词。")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def export_words(self):
        if not self.can_leave():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出单词本", "拾词备份-" + strftime("%Y%m%d") + ".json", "JSON (*.json)")
        if not path:
            return
        try:
            if Path(path).resolve() in (self.store.path.resolve(), self.store.path.with_suffix(".json.bak").resolve()):
                raise ValueError("请选择另一处位置保存备份。")
            Store.atomic_write(path, {"version": 1, "words": self.data["words"]})
            self.status.setText(f"已导出 {len(self.data['words'])} 个单词。")
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
