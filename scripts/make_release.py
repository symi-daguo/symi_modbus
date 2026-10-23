"""Build the archive that is attached to a release.

The archive holds the integration with the layout of the repository, so it can
be unpacked into the ``custom_components`` directory of a configuration.

The version is taken from ``manifest.json``, the name of the archive follows
the pattern ``symi_modbus-<version>.zip``.

Only the files of the integration are packed. The caches of Python and the
files of the operating system are left out, and the archive is written by
Python itself, so it carries no extra files that macOS or Windows would add.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "symi_modbus"
MANIFEST = COMPONENT / "manifest.json"

# The folders and the files that never belong into an archive.
SKIP_NAMES = {"__pycache__", ".git", ".DS_Store", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def _version() -> str:
    """Return the version of the integration."""
    return str(json.loads(MANIFEST.read_text())["version"])


def _files() -> list[Path]:
    """Return the files of the integration, in a stable order."""
    found = []
    for path in sorted(COMPONENT.rglob("*")):
        if not path.is_file():
            continue
        if SKIP_NAMES & set(path.parts) or path.name in SKIP_NAMES:
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        found.append(path)
    return found


def build(target: Path | None = None) -> Path:
    """Write the archive and return the path it was written to."""
    version = _version()
    target = target or ROOT / f"symi_modbus-{version}.zip"
    files = _files()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
    return target


if __name__ == "__main__":
    archive = build()
    print(f"wrote {archive} ({archive.stat().st_size} bytes)")
