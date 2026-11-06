from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                              QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                              QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from core import Settings, UserError, get_models, is_loopback, normalize_url, validate_destination
from jobs import Job
from theme import STYLE


class EngineSelector(QWidget):
    """Both choices stay visible; no native combo popup to clip on scaled screens."""
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = 0
        self._values = ("ollama", "api")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.group = QButtonGroup(self)
        self.buttons = []
        for index, text in enumerate(("Ollama · 本机模型\n连接本机 Ollama 服务", "在线 / 自建 API\n兼容 OpenAI 接口")):
            button = QPushButton(text)
            button.setObjectName("engineOption")
            button.setCheckable(True)
            button.setMinimumHeight(64)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(button, index)
            row.addWidget(button, 1)
            self.buttons.append(button)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.setCurrentIndex)

    def currentIndex(self):
        return self._index

    def currentData(self):
        return self._values[self._index]

    def setCurrentIndex(self, index):
        if index not in (0, 1):
            return
        changed = index != self._index
        self._index = index
        self.buttons[index].setChecked(True)
        if changed:
            self.currentIndexChanged.emit(index)


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        # Settings is parented to the compact window. Give it its own form style
        # so the compact window's borderless combo rules do not leak into it.
        self.setStyleSheet(STYLE + """
QPushButton#engineOption { text-align: left; padding: 8px 14px; border: 1px solid #dce5eb; border-radius: 9px; background: #ffffff; color: #526975; }
QPushButton#engineOption:hover { background: #f0f7f5; border-color: #97c6ba; }
QPushButton#engineOption:checked { background: #e7f4ef; border: 2px solid #148577; padding: 7px 13px; color: #116e62; font-weight: 600; }
QPushButton#engineOption:focus { border-color: #116e62; }
QPushButton#engineOption:disabled { color: #96a7ae; border-color: #dce5eb; background: #f4f7f9; }
""")
        self.original = replace(cfg)
        self.value = replace(cfg)
        self.job = None
        self.setWindowTitle("ZTrans · 设置")
        self.setMinimumWidth(680)
        self.resize(720, 690)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 22, 25, 22)
        title = QLabel("让翻译按你的方式工作")
        title.setObjectName("title")
        layout.addWidget(title)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        service = QWidget()
        form = QFormLayout(service)
        form.setContentsMargins(22, 22, 22, 22)
        form.setVerticalSpacing(16)
        self.provider = EngineSelector()
        self.provider.setCurrentIndex(0 if cfg.provider == "ollama" else 1)
        form.addRow("翻译引擎", self.provider)
        self.url = QLineEdit(cfg.base_url)
        form.addRow("服务地址", self.url)
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem(cfg.model)
        model_row.addWidget(self.model, 1)
        self.refresh = QPushButton("检测 / 获取模型")
        self.refresh.clicked.connect(self.fetch_models)
        model_row.addWidget(self.refresh)
        form.addRow("模型名称", model_row)
        self.key = QLineEdit(cfg.api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("只保存在这台电脑，不读取其他软件的密钥")
        self.key_label = QLabel("API 密钥")
        form.addRow(self.key_label, self.key)
        self.remember = QCheckBox("记住密钥（使用 Windows 当前账户加密）")
        self.remember.setChecked(cfg.remember_key)
        form.addRow("", self.remember)
        self.remote = QCheckBox("允许原文和匹配的术语发送到此服务地址")
        self.remote.setChecked(cfg.remote_consent == cfg.consent_id)
        form.addRow("", self.remote)
        self.destination = QLabel()
        self.destination.setWordWrap(True)
        form.addRow("数据去向", self.destination)
        self.status = QLabel("可直接使用已有的 hy-mt1.5:7b。在线 API 请填写服务商的基础地址与模型名。")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        form.addRow(self.status)
        tabs.addTab(service, "翻译服务")
        preference = QWidget()
        pf = QFormLayout(preference)
        pf.setContentsMargins(22, 22, 22, 22)
        pf.setVerticalSpacing(18)
        self.startup = QCheckBox("登录 Windows 后在托盘启动")
        self.startup.setChecked(cfg.startup)
        pf.addRow("开机自启", self.startup)
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 22)
        self.font_size.setValue(cfg.font_size)
        self.font_size.setSuffix(" pt")
        pf.addRow("正文大小", self.font_size)
        self.glossary = QPlainTextEdit(cfg.glossary)
        self.glossary.setPlaceholderText("每行一个术语，例如：\nsolvation = 溶剂化\ncoordination number = 配位数\nsolid electrolyte interphase = 固体电解质界面膜")
        self.glossary.setMinimumHeight(175)
        pf.addRow("术语表", self.glossary)
        note = QLabel("术语只在本机保存；在线翻译时只发送当前原文中匹配的条目。\n\nF1：翻译选中文字\nCtrl + Alt + Z：显示小窗口\n悬浮窗闲置 60 秒后显示拾词\nCtrl + Enter：翻译；Esc：停止任务")
        note.setWordWrap(True)
        note.setObjectName("muted")
        pf.addRow(note)
        tabs.addTab(preference, "偏好与术语")
        privacy = QLabel("无账号、无统计上报、无后台剪贴板监听、无自动历史记录。\n本地模式直连本机；在线模式由你选择服务商。导出的文件由你自行保管。")
        privacy.setWordWrap(True)
        privacy.setObjectName("muted")
        layout.addWidget(privacy)
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.save = QPushButton("保存设置")
        self.save.setObjectName("primary")
        self.save.clicked.connect(self.commit)
        footer.addWidget(cancel)
        footer.addWidget(self.save)
        layout.addLayout(footer)
        self.provider.currentIndexChanged.connect(self.switch_provider)
        self.url.textEdited.connect(self.endpoint_changed)
        self.update_destination()

    def switch_provider(self):
        if self.provider.currentData() == "ollama":
            self.value.api_url = self.url.text()
            self.value.api_model = self.model.currentText()
            self.value.api_key = self.key.text()
            self.url.setText(self.value.ollama_url)
            self.model.setCurrentText(self.value.ollama_model)
        else:
            self.value.ollama_url = self.url.text()
            self.value.ollama_model = self.model.currentText()
            self.url.setText(self.value.api_url)
            self.model.setCurrentText(self.value.api_model)
        self.remote.setChecked(False)
        self.update_destination()

    def endpoint_changed(self):
        self.remote.setChecked(False)
        if self.provider.currentData() == "api":
            self.key.clear()
        self.update_destination()

    def update_destination(self):
        online = self.provider.currentData() == "api"
        self.key.setVisible(online)
        self.key_label.setVisible(online)
        self.remember.setVisible(online)
        try:
            local = is_loopback(self.url.text())
            self.remote.setVisible(not local)
            self.destination.setText("本机服务 · 原文直接交给本机模型；请使用实际在本机运行的模型。" if local else "远程服务 · 翻译原文会发送到上方地址。请仅使用你信任的服务商。")
        except UserError:
            self.remote.setVisible(True)
            self.destination.setText("请填写完整服务地址。")

    def collect(self):
        cfg = replace(self.value)
        cfg.provider = self.provider.currentData()
        if cfg.provider == "ollama":
            cfg.ollama_url = normalize_url(self.url.text())
            cfg.ollama_model = self.model.currentText().strip()
        else:
            cfg.api_url = normalize_url(self.url.text())
            cfg.api_model = self.model.currentText().strip()
            cfg.api_key = self.key.text().strip()
        cfg.remote_consent = cfg.consent_id if self.remote.isChecked() else ""
        cfg.remember_key = self.remember.isChecked()
        cfg.startup = self.startup.isChecked()
        cfg.font_size = self.font_size.value()
        cfg.glossary = self.glossary.toPlainText()
        return cfg

    def fetch_models(self):
        try:
            cfg = self.collect()
            if not cfg.model:
                if cfg.provider == "ollama":
                    cfg.ollama_model = "detect"
                else:
                    cfg.api_model = "detect"
            validate_destination(cfg)
        except UserError as e:
            self.status.setText(str(e))
            return
        self.refresh.setEnabled(False)
        self.save.setEnabled(False)
        self.provider.setEnabled(False)
        self.url.setEnabled(False)
        self.status.setText("正在连接所选服务…")
        self.job = Job(lambda job: get_models(cfg), self)
        self.job.result.connect(self.models_ready)
        self.job.error.connect(self.status.setText)
        self.job.finished.connect(self.model_finished)
        self.job.start()

    def models_ready(self, models):
        current = self.model.currentText()
        self.model.clear()
        self.model.addItems(models)
        if current in models:
            self.model.setCurrentText(current)
        self.status.setText(f"连接成功，发现 {len(models)} 个模型。" if models else "连接成功，但没有发现可用模型；也可以直接填写模型名。")

    def model_finished(self):
        self.refresh.setEnabled(True)
        self.save.setEnabled(True)
        self.provider.setEnabled(True)
        self.url.setEnabled(True)
        self.job.deleteLater()
        self.job = None

    def commit(self):
        try:
            cfg = self.collect()
            validate_destination(cfg)
        except UserError as e:
            QMessageBox.warning(self, "检查设置", str(e))
            return
        self.value = cfg
        self.accept()

    def reject(self):
        if self.job and self.job.isRunning():
            self.status.setText("正在检测连接，请稍候再关闭（最多 20 秒）。")
            return
        super().reject()
