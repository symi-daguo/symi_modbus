"""Generate the brand assets of the Symi Modbus integration.

Produces the eight files the Home Assistant brands proxy expects inside
``custom_components/symi_modbus/brand``:

* ``icon.png`` / ``icon@2x.png``  - square 256 / 512 pixel icon
* ``logo.png`` / ``logo@2x.png``  - horizontal logo 256 / 512 pixel high
* ``dark_icon.png`` / ``dark_icon@2x.png``
* ``dark_logo.png`` / ``dark_logo@2x.png``

The source artwork is white glyphs on the brand orange. The orange becomes the
background of the icon, while the logo keeps the orange block for the mark and
sets the wordmark in orange on the page background.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "icon_source.png"
BRAND_DIR = ROOT / "custom_components" / "symi_modbus" / "brand"

BRAND_ORANGE = (225, 104, 43)
DARK_BACKGROUND = (24, 26, 31, 255)
LIGHT_BACKGROUND = (255, 255, 255, 255)

ICON_SIZE = 256
LOGO_HEIGHT = 256

# Fraction of the source height where the mark ends and the wordmark starts.
MARK_BOTTOM = 0.56
WORDMARK_TOP = 0.60


def _mask_of_artwork(source: Image.Image) -> Image.Image:
    """Return a mask that is opaque on the white glyphs and clear elsewhere."""
    mask = Image.new("L", source.size, 0)
    pixels = source.convert("RGB").load()
    mask_px = mask.load()
    width, height = source.size

    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            # The glyphs are white; everything else is the orange field.
            if red > 200 and green > 200 and blue > 200:
                mask_px[x, y] = 255

    return mask


def _glyphs(source: Image.Image, mask: Image.Image) -> Image.Image:
    """Return the white glyphs with a transparent background."""
    artwork = Image.new("RGBA", source.size, (255, 255, 255, 0))
    artwork.putalpha(mask)
    return artwork


def _split(artwork: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Cut the artwork into the mark (top) and the wordmark (bottom)."""
    width, height = artwork.size
    mark = artwork.crop((0, 0, width, int(height * MARK_BOTTOM)))
    wordmark = artwork.crop((0, int(height * WORDMARK_TOP), width, height))
    return mark, wordmark


def _trim(image: Image.Image) -> Image.Image:
    """Remove the transparent border around the artwork."""
    box = image.getbbox()
    if box is None:
        return image
    return image.crop(box)


def _solid(image: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Return the artwork recoloured to a single colour."""
    alpha = image.getchannel("A")
    filled = Image.new("RGBA", image.size, (*color, 255))
    filled.putalpha(alpha)
    return filled


def _make_icon(mark: Image.Image) -> Image.Image:
    """Return the square icon: white mark on the brand orange."""
    glyphs = _trim(mark)
    side = max(glyphs.size)
    canvas = Image.new("RGBA", (side, side), (*BRAND_ORANGE, 255))
    canvas.alpha_composite(glyphs, ((side - glyphs.width) // 2, (side - glyphs.height) // 2))
    return canvas.convert("RGB").resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)


def _make_logo(mark: Image.Image, wordmark: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """Return the horizontal logo: orange block with the mark, orange wordmark."""
    glyphs_mark = _trim(mark)
    glyphs_word = _trim(wordmark)

    mark_height = LOGO_HEIGHT
    mark_width = round(glyphs_mark.width * mark_height / glyphs_mark.height)
    mark_resized = glyphs_mark.resize((mark_width, mark_height), Image.LANCZOS)

    wordmark_height = round(LOGO_HEIGHT * 0.40)
    wordmark_width = round(glyphs_word.width * wordmark_height / glyphs_word.height)
    wordmark_resized = glyphs_word.resize((wordmark_width, wordmark_height), Image.LANCZOS)

    gap = round(LOGO_HEIGHT * 0.14)
    block_width = mark_width + round(LOGO_HEIGHT * 0.18)
    total_width = block_width + gap + wordmark_width

    canvas = Image.new("RGBA", (total_width, LOGO_HEIGHT), (background[0], background[1], background[2], 255))
    # The mark keeps its orange block so it stays recognisable.
    block = Image.new("RGBA", (block_width, LOGO_HEIGHT), (*BRAND_ORANGE, 255))
    block.alpha_composite(mark_resized, ((block_width - mark_width) // 2, 0))
    canvas.alpha_composite(block, (0, 0))

    # The wordmark is the white glyphs recoloured to the brand orange.
    orange_word = _solid(wordmark_resized, BRAND_ORANGE)
    canvas.alpha_composite(orange_word, (block_width + gap, LOGO_HEIGHT - wordmark_height))
    return canvas.convert("RGB")


def main() -> None:
    """Write every brand file."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGBA")
    mask = _mask_of_artwork(source)
    mark, wordmark = _split(_glyphs(source, mask))

    icon = _make_icon(mark)
    icon.save(BRAND_DIR / "icon.png", optimize=True)
    icon.resize((ICON_SIZE * 2, ICON_SIZE * 2), Image.LANCZOS).save(
        BRAND_DIR / "icon@2x.png", optimize=True
    )

    for suffix, background in (("", LIGHT_BACKGROUND), ("dark_", DARK_BACKGROUND)):
        logo = _make_logo(mark, wordmark, background)
        logo.save(BRAND_DIR / f"{suffix}logo.png", optimize=True)
        logo.resize((logo.width * 2, logo.height * 2), Image.LANCZOS).save(
            BRAND_DIR / f"{suffix}logo@2x.png", optimize=True
        )

        if suffix:
            # The dark icon keeps the brand block, it reads well on both themes.
            icon.save(BRAND_DIR / "dark_icon.png", optimize=True)
            icon.resize((ICON_SIZE * 2, ICON_SIZE * 2), Image.LANCZOS).save(
                BRAND_DIR / "dark_icon@2x.png", optimize=True
            )

    for path in sorted(BRAND_DIR.glob("*.png")):
        with Image.open(path) as image:
            print(f"{path.name:20s} {image.width}x{image.height}")


if __name__ == "__main__":
    main()
