"""Generate the brand assets of the Symi Modbus integration.

Produces the eight files the Home Assistant brands proxy expects inside
``custom_components/symi_modbus/brand``:

* ``icon.png`` / ``icon@2x.png``  - square 256 / 512 pixel icon
* ``logo.png`` / ``logo@2x.png``  - horizontal logo 256 / 512 pixel high
* ``dark_icon.png`` / ``dark_icon@2x.png``
* ``dark_logo.png`` / ``dark_logo@2x.png``

The source artwork holds the mark in its upper half and the wordmark in its
lower half, both as white shapes on the brand orange. The icon keeps the
orange field, the logo sets the wordmark in orange on a light field next to
the mark.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "icon_source.png"
BRAND_DIR = ROOT / "custom_components" / "symi_modbus" / "brand"

BRAND_ORANGE = (225, 104, 43)
LIGHT_BACKGROUND = (255, 255, 255, 255)
DARK_BACKGROUND = (24, 26, 31, 255)

ICON_SIZE = 256
LOGO_HEIGHT = 256

# Boxes in the 1800 x 1800 source artwork, in source pixels.
MARK_BOX = (600, 440, 1200, 1040)
WORDMARK_BOX = (140, 1100, 1660, 1300)


def _white_mask(image: Image.Image) -> Image.Image:
    """Return a mask that is opaque on the white shapes of the artwork."""
    mask = Image.new("L", image.size, 0)
    pixels = image.convert("RGB").load()
    mask_pixels = mask.load()

    for y in range(image.height):
        for x in range(image.width):
            red, green, blue = pixels[x, y]
            if red > 200 and green > 200 and blue > 200:
                mask_pixels[x, y] = 255

    return mask


def _crop(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    """Crop the artwork to a box."""
    return image.crop(box)


def _make_icon(mark: Image.Image) -> Image.Image:
    """Return the square icon: the mark on the brand orange."""
    side = max(mark.size)
    canvas = Image.new("RGB", (side, side), BRAND_ORANGE)
    canvas.paste(mark.convert("RGB"), ((side - mark.width) // 2, (side - mark.height) // 2))
    return canvas.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)


def _wordmark_in_orange(wordmark: Image.Image) -> Image.Image:
    """Return the wordmark as orange shapes on a transparent background."""
    mask = _white_mask(wordmark)
    filled = Image.new("RGBA", wordmark.size, (*BRAND_ORANGE, 0))
    filled.putalpha(mask)
    return filled


def _make_logo(mark: Image.Image, wordmark: Image.Image, background: tuple[int, int, int, int]) -> Image.Image:
    """Return the horizontal logo: the mark on orange next to the wordmark."""
    mark_height = LOGO_HEIGHT
    mark_width = round(mark.width * mark_height / mark.height)
    mark_resized = mark.convert("RGB").resize((mark_width, mark_height), Image.LANCZOS)

    wordmark_height = round(LOGO_HEIGHT * 0.30)
    wordmark_width = round(wordmark.width * wordmark_height / wordmark.height)
    wordmark_resized = _wordmark_in_orange(wordmark).resize(
        (wordmark_width, wordmark_height), Image.LANCZOS
    )

    gap = round(LOGO_HEIGHT * 0.12)
    block_width = mark_width + round(LOGO_HEIGHT * 0.16)
    total_width = block_width + gap + wordmark_width

    canvas = Image.new("RGBA", (total_width, LOGO_HEIGHT), background)
    block = Image.new("RGB", (block_width, LOGO_HEIGHT), BRAND_ORANGE)
    block.paste(mark_resized, ((block_width - mark_width) // 2, 0))
    canvas.paste(block.convert("RGBA"), (0, 0))
    canvas.alpha_composite(
        wordmark_resized, (block_width + gap, LOGO_HEIGHT - wordmark_height)
    )
    return canvas.convert("RGB")


def main() -> None:
    """Write every brand file."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGB")

    mark = _crop(source, MARK_BOX)
    wordmark = _crop(source, WORDMARK_BOX)

    icon = _make_icon(mark)
    icon.save(BRAND_DIR / "icon.png", optimize=True)
    icon.resize((ICON_SIZE * 2, ICON_SIZE * 2), Image.LANCZOS).save(
        BRAND_DIR / "icon@2x.png", optimize=True
    )
    # The mark is an orange field, so it reads the same on a dark background.
    icon.save(BRAND_DIR / "dark_icon.png", optimize=True)
    icon.resize((ICON_SIZE * 2, ICON_SIZE * 2), Image.LANCZOS).save(
        BRAND_DIR / "dark_icon@2x.png", optimize=True
    )

    for suffix, background in (("", LIGHT_BACKGROUND), ("dark_", DARK_BACKGROUND)):
        logo = _make_logo(mark, wordmark, background)
        logo.save(BRAND_DIR / f"{suffix}logo.png", optimize=True)
        logo.resize((logo.width * 2, logo.height * 2), Image.LANCZOS).save(
            BRAND_DIR / f"{suffix}logo@2x.png", optimize=True
        )

    for path in sorted(BRAND_DIR.glob("*.png")):
        with Image.open(path) as image:
            print(f"{path.name:20s} {image.width}x{image.height}")


if __name__ == "__main__":
    main()
