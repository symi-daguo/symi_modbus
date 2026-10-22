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
