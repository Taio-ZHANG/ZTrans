STYLE = """
* { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #223747; }
QMainWindow, QDialog { background: #f4f7f9; }
QWidget#sidebar { background: #ffffff; border-right: 1px solid #e5ebef; }
QLabel#brand { font-size: 25px; font-weight: 700; color: #133d43; }
QLabel#title { font-size: 27px; font-weight: 700; color: #173442; }
QLabel#muted { color: #7a8c99; font-size: 12px; }
QLabel#eyebrow { color: #178679; font-size: 11px; font-weight: 700; }
QLabel#badge { background: #e2f3ec; color: #147362; border-radius: 13px; padding: 7px 13px; }
QLabel#remoteBadge { background: #fff0d8; color: #94601e; border-radius: 13px; padding: 7px 13px; }
QFrame#card, QWidget#card { background: #ffffff; border: 1px solid #e1e8ed; border-radius: 14px; }
QFrame#card QLabel { border: none; }
QPushButton { background: #ffffff; border: 1px solid #dce5eb; border-radius: 8px; padding: 9px 14px; }
QPushButton:hover { background: #edf5f3; border-color: #a1c9c0; }
QPushButton:pressed { background: #deeee9; }
QPushButton:disabled { color: #a6b4be; background: #f4f6f7; border-color: #e4e9ed; }
QPushButton#primary { background: #148577; border-color: #148577; color: white; font-weight: 600; padding: 11px 25px; }
QPushButton#primary:hover { background: #106e63; }
QPushButton#primary:disabled { background: #9dc6bd; border-color: #9dc6bd; }
QPushButton#nav { text-align: left; padding: 12px 16px; border: none; background: transparent; color: #6c808c; font-size: 14px; }
QPushButton#nav:checked { background: #e5f3ee; color: #127868; font-weight: 600; }
QPushButton#nav:hover { background: #f0f6f4; }
QPushButton#quiet { border: none; background: transparent; color: #5b7484; padding: 5px 9px; }
QPushButton#quiet:hover { background: #edf4f3; color: #127868; }
QComboBox, QLineEdit, QSpinBox { background: white; border: 1px solid #dce5eb; border-radius: 7px; padding: 8px 10px; min-height: 19px; selection-background-color: #b7ded3; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #dcefe8; selection-color: #143c36; }
QPlainTextEdit, QTextEdit { background: white; border: 1px solid #dce5eb; border-radius: 9px; padding: 11px; selection-background-color: #c4e5db; }
QPlainTextEdit#editor { border: none; border-radius: 0px; padding: 8px; background: transparent; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QProgressBar { border: none; background: #e3ebe9; border-radius: 3px; max-height: 5px; }
QProgressBar::chunk { background: #148577; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #d4dfe3; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: transparent; width: 14px; }
QToolTip { background: #203d48; color: white; border: none; padding: 8px; }
QMenu { background: white; border: 1px solid #e0e7eb; padding: 6px; }
QMenu::item { padding: 8px 22px; }
QMenu::item:selected { background: #e6f3ed; }
QTabWidget::pane { border: 1px solid #e1e8ed; background: white; border-radius: 8px; }
QTabBar::tab { padding: 10px 22px; margin: 4px; }
QTabBar::tab:selected { color: #107c6d; border-bottom: 2px solid #148577; }
"""
