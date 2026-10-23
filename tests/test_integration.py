"""Smoke tests: the integration must import cleanly and expose the HA API."""
from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "custom_components.symi_modbus",
        "custom_components.symi_modbus.config_flow",
        "custom_components.symi_modbus.connection",
        "custom_components.symi_modbus.const",
        "custom_components.symi_modbus.frames",
        "custom_components.symi_modbus.linkage",
        "custom_components.symi_modbus.modbus",
        "custom_components.symi_modbus.panels",
        "custom_components.symi_modbus.panels.clowire",
        "custom_components.symi_modbus.panels.connection",
        "custom_components.symi_modbus.panels.lf",
        "custom_components.symi_modbus.panels.manager",
        "custom_components.symi_modbus.panels.symi",
        "custom_components.symi_modbus.switch",
    ],
)
def test_module_imports(module: str) -> None:
    """Every module imports without a NameError or a missing constant."""
    assert importlib.import_module(module) is not None


def test_manifest_is_valid() -> None:
    """The manifest carries the keys Home Assistant needs."""
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "custom_components" / "symi_modbus" / "manifest.json").read_text()
    )
    for key in ("domain", "name", "codeowners", "documentation", "issue_tracker", "version"):
        assert key in manifest, f"manifest is missing {key}"
    assert manifest["config_flow"] is True
    assert manifest["version"]


def test_translations_have_the_same_shape() -> None:
    """The English and Chinese translations carry the same keys."""
    import json
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "custom_components" / "symi_modbus"
    strings = json.loads((base / "strings.json").read_text())
    english = json.loads((base / "translations" / "en.json").read_text())
    chinese = json.loads((base / "translations" / "zh-Hans.json").read_text())

    def keys(value, prefix=""):
        found = set()
        if isinstance(value, dict):
            for key, item in value.items():
                found.add(f"{prefix}.{key}")
                found |= keys(item, f"{prefix}.{key}")
        return found

    assert keys(strings) == keys(english)
    assert keys(strings) == keys(chinese)


def test_brand_assets_use_the_official_sizes() -> None:
    """The brand images follow the sizes the brands proxy expects."""
    from pathlib import Path

    from PIL import Image

    brand = (
        Path(__file__).resolve().parent.parent / "custom_components" / "symi_modbus" / "brand"
    )
    expected = {
        "icon.png": (256, 256),
        "icon@2x.png": (512, 512),
        "dark_icon.png": (256, 256),
        "dark_icon@2x.png": (512, 512),
    }
    for name, size in expected.items():
        path = brand / name
        assert path.is_file(), f"missing {name}"
        with Image.open(path) as image:
            assert image.size == size, f"{name} is {image.size}, expected {size}"

    for name in ("logo.png", "dark_logo.png"):
        path = brand / name
        assert path.is_file(), f"missing {name}"
        with Image.open(path) as image:
            assert image.height == 256, f"{name} height is {image.height}, expected 256"

    for name in ("logo@2x.png", "dark_logo@2x.png"):
        path = brand / name
        assert path.is_file(), f"missing {name}"
        with Image.open(path) as image:
            assert image.height == 512, f"{name} height is {image.height}, expected 512"


def test_the_document_shows_the_version_of_the_manifest() -> None:
    """The version in the document is the version that is released."""
    import json
    import re
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "custom_components" / "symi_modbus"
    manifest = json.loads((base / "manifest.json").read_text())
    readme = (base.parent.parent / "README.md").read_text()

    shown = re.search(r"\| Version \| \*\*([^*]+)\*\* \|", readme)
    assert shown is not None, "the document does not show a version"
    assert shown.group(1) == manifest["version"], (
        f"the document shows {shown.group(1)}, the manifest {manifest['version']}"
    )


def test_the_hacs_file_follows_the_rules_of_hacs() -> None:
    """The HACS file only uses the keys HACS knows and names the same version."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    hacs = json.loads((root / "hacs.json").read_text())
    manifest = json.loads(
        (root / "custom_components" / "symi_modbus" / "manifest.json").read_text()
    )

    allowed = {
        "content_in_root",
        "country",
        "filename",
        "hacs",
        "hide_default_branch",
        "homeassistant",
        "persistent_directory",
        "render_readme",
        "zip_release",
        "name",
    }
    assert set(hacs) <= allowed, f"hacs.json has keys HACS does not know: {set(hacs) - allowed}"
    assert hacs["name"]
    assert hacs["homeassistant"] == manifest["homeassistant"]
    # HACS refuses a zip_release without a filename, and a fixed filename
    # breaks with the next release, so the installation follows the tag of
    # the repository instead.
    assert not hacs.get("zip_release"), (
        "zip_release needs a filename that has to be changed with every release"
    )
