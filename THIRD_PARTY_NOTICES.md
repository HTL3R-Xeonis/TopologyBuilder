# Third-party notices

This project is licensed under the GNU GPL v3 (see `LICENSE`). No third-party source code is copied into the repository.
The dependencies pinned in `pyproject.toml` / `requirements.txt` are installed from PyPI; their licenses were read from the
installed packages (`pip-licenses`, November 2026).

| Package | License | Note |
| --- | --- | --- |
| paramiko | LGPL-2.1 | Used as an unmodified library. Compatible with GPL-3.0 (LGPL-2.1 section 3 allows the GPL terms). |
| certifi | MPL-2.0 | Unmodified; compatible with GPL-3.0. |
| pyvmomi, requests, cryptography, bcrypt, PyNaCl | Apache-2.0 (cryptography: Apache-2.0 or BSD-3-Clause) | Apache-2.0 is compatible with GPL-3.0 (not with GPL-2.0-only). |
| PyYAML, rich, typer, loguru, python-dotenv, markdown-it-py, mdurl, urllib3, idna, charset-normalizer, attrs | MIT / BSD / ISC | Permissive; keep the copyright notices when redistributing. |
| typing_extensions | PSF-2.0 | Permissive. |
| pytest, allure-python-commons, ruff | MIT / Apache-2.0 | Development and test only. |
