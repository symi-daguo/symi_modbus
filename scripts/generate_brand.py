"""Generate the brand assets of the Symi Modbus integration.

Produces the eight files the Home Assistant brands proxy expects inside
``custom_components/symi_modbus/brand``:

* ``icon.png`` / ``icon@2x.png``  - square 256 / 512 pixel icon
* ``logo.png`` / ``logo@2x.png``  - logo 256 / 512 pixel high
* ``dark_icon.png`` / ``dark_icon@2x.png``
* ``dark_logo.png`` / ``dark_logo@2x.png``

The whole artwork is scaled to the target size, nothing is cut off, and the
corners are rounded so the images sit nicely in the Home Assistant interface.
The dark variants are the same artwork on a dark background.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "icon_source.png"
BRAND_DIR = ROOT / "custom_components" / "symi_modbus" / "brand"

BRAND_ORANGE = (225, 104, 43)
DARK_BACKGROUND = (24, 26, 31, 255)

ICON_SIZE = 256
LOGO_HEIGHT = 256

# The corner radius as a share of the shorter side.
CORNER_RADIUS = 0.26


def _flatten(image: Image.Image, background: tuple[int, int, int, int]) -> Image.Image:
    """Place the artwork on a solid background."""
    canvas = Image.new("RGBA", image.size, background)
    canvas.alpha_composite(image.convert("RGBA"))
    return canvas.convert("RGB")


def _rounded_mask(size: tuple[int, int]) -> Image.Image:
    """Return a mask with rounded corners."""
    mask = Image.new("L", size, 0)
    radius = round(min(size) * CORNER_RADIUS)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255
    )
    return mask


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale the whole artwork to the given size, keeping the ratio."""
    return image.resize(size, Image.LANCZOS)


def _with_rounded_corners(image: Image.Image) -> Image.Image:
    """Round the corners of the artwork."""
    result = image.convert("RGBA")
    result.putalpha(_rounded_mask(result.size))
    return result


def _make_icon(source: Image.Image) -> Image.Image:
    """Return the square icon: the whole artwork scaled to a square."""
    return _with_rounded_corners(_fit(source, (ICON_SIZE, ICON_SIZE)))


def _make_logo(source: Image.Image) -> Image.Image:
    """Return the logo: the whole artwork scaled to the logo height."""
    width = round(source.width * LOGO_HEIGHT / source.height)
    return _with_rounded_corners(_fit(source, (width, LOGO_HEIGHT)))


def main() -> None:
    """Write every brand file."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGB")
    dark = _flatten(source, DARK_BACKGROUND)

    icon = _make_icon(source)
    icon.save(BRAND_DIR / "icon.png", optimize=True)
    _fit(icon, (ICON_SIZE * 2, ICON_SIZE * 2)).save(
        BRAND_DIR / "icon@2x.png", optimize=True
    )

    dark_icon = _make_icon(dark)
    dark_icon.save(BRAND_DIR / "dark_icon.png", optimize=True)
    _fit(dark_icon, (ICON_SIZE * 2, ICON_SIZE * 2)).save(
        BRAND_DIR / "dark_icon@2x.png", optimize=True
    )

    logo = _make_logo(source)
    logo.save(BRAND_DIR / "logo.png", optimize=True)
    _fit(logo, (logo.width * 2, logo.height * 2)).save(
        BRAND_DIR / "logo@2x.png", optimize=True
    )

    dark_logo = _make_logo(dark)
    dark_logo.save(BRAND_DIR / "dark_logo.png", optimize=True)
    _fit(dark_logo, (dark_logo.width * 2, dark_logo.height * 2)).save(
        BRAND_DIR / "dark_logo@2x.png", optimize=True
    )

    for path in sorted(BRAND_DIR.glob("*.png")):
        with Image.open(path) as image:
            print(f"{path.name:20s} {image.width}x{image.height}")


if __name__ == "__main__":
    main()
