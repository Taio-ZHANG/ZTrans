from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'README.md'), '.'), (str(root / 'PRIVACY.md'), '.')]
datas += [(str(root.parent / 'LICENSE'), '.'), (str(root.parent / 'THIRD_PARTY_NOTICES.md'), '.'), (str(root.parent / 'THIRD_PARTY_LICENSES'), 'THIRD_PARTY_LICENSES')]
for folder in ("ipa", "meaning"):
    datas += [(str(path), folder) for path in (root / folder).iterdir()]
for package in ['requests', 'pymupdf', 'python-docx', 'PySide6', 'beautifulsoup4']:
    datas += copy_metadata(package)

a = Analysis([str(root / 'app.py')], pathex=[str(root)], binaries=[], datas=datas,
             hiddenimports=['win32timezone', 'win32crypt', 'pythoncom', 'win32com.client', 'smoke_test', 'test_compact'],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml',
                       'PySide6.QtQuick', 'PySide6.QtPdf', 'tkinter', 'pytest', 'numpy', 'PIL'], noarchive=False)
# Qt 6.12 uses Windows' unversioned ICU API. Do not ship unrelated ICU / API-set
# shims discovered on a developer machine's PATH (e.g. Poppler or image utilities).
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith(('api-ms-', 'ext-ms-', 'icudt'))
              and Path(entry[0]).name.lower() not in ('icuuc.dll', 'icuin.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ZTrans', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root / 'ztrans.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ZTrans')
