import os
import shutil
from pathlib import Path

# doc_engine/src/doc_engine/config.py -> parents[3] is the repo root
# (config.py -> doc_engine -> src -> doc_engine (package dir) -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATES_DIR = REPO_ROOT / "templates"

# Linux (apt/dnf `libreoffice` packages, incl. the Docker image) puts `soffice`
# on PATH; the macOS .app bundle does not, so that path is only the fallback
# for local macOS dev. DOC_ENGINE_SOFFICE_BIN overrides both for a nonstandard
# install location.
SOFFICE_BIN = (
    os.environ.get("DOC_ENGINE_SOFFICE_BIN")
    or shutil.which("soffice")
    or shutil.which("libreoffice")
    or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
)
