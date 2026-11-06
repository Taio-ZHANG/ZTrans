# Third-party notices

ZTrans project code: Copyright (c) 2026 Taio-ZHANG, AGPL-3.0-only.
This project license does not replace any upstream component or data license.

| Component | Upstream / terms |
| --- | --- |
| PyMuPDF / MuPDF | [PyMuPDF](https://github.com/pymupdf/PyMuPDF), AGPL-3.0 or separate commercial license; this snapshot uses the AGPL route |
| PySide6 / Shiboken / Qt | [Qt for Python](https://doc.qt.io/qtforpython-6/licenses.html), upstream LGPL/GPL/commercial terms; retain Qt module notices when redistributing binaries |
| requests, Beautiful Soup, python-docx, lxml and build dependencies | Original package license notices retained in `THIRD_PARTY_LICENSES/`; versions in `source/requirements-lock.txt` |
| Offline English IPA list | `source/ipa/en_US.txt`; original MIT notice in `IPA-DICT-LICENSE.txt`, attribution: dohliam/ipa-dict; associated CMU notice retained in `CMUDICT-LICENSE.txt` |
| Offline Chinese dictionary | `source/meaning/ecdict.sqlite`; local public dictionary resource and supplied MIT notice preserved in `ECDICT-LICENSE.txt` (Copyright 2025 Linwei) |

The preserved wheel notices use flattened filenames; links inside upstream notices may refer to their original installed package layout. Full accompanying license texts are retained in the same component directories.

Dictionary files are separate third-party data, not the user's vocabulary history. The SQLite resource contains only the `meanings(word, meaning)` table.
Dictionary data were supplied with the current installed application; the repository preserves the accompanying notices and does not claim authorship of those datasets.

Ollama and model weights are not bundled. Obtain them separately and follow their own licenses.
When distributing a new binary, collect notices from the actual build environment, retain Qt licenses, and provide corresponding application source under AGPL-3.0.
Official PyMuPDF licensing information: https://pymupdf.readthedocs.io/en/latest/about.html
