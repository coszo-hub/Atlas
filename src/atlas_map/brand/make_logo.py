"""The atlas logo in the sizes the map uses, from brand/atlas-logo.png (the ring and the word "Atlas").

The map's panels are dark, where the logo's navy lettering would all but vanish, so the header's copy keeps the
gradient ring as it is and draws the lettering in the panels' text colour (--text-primary). The browser icons
keep the original colours on a white tile, since the navy lettering would vanish on a dark tab bar; the tile is
rounded for tabs and square for iOS, which rounds home-screen icons itself.

    python3 brand/make_logo.py      # from src/atlas_map
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
TEXT_PRIMARY = (0xEC, 0xEB, 0xE6)
LETTERING_MAX = 120   # the lettering's brightest channel is 40-80, the ring's 150 or more


def square(im: Image.Image, pad: float = 0.03) -> Image.Image:
    a = np.asarray(im).copy()
    a[a[..., 3] < 8] = 0                                   # stray near-transparent specks around the drawing
    ys, xs = np.nonzero(a[..., 3])
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 * (1 + pad)
    return Image.fromarray(a).crop((round(cx - half), round(cy - half), round(cx + half), round(cy + half)))


def main() -> None:
    logo = square(Image.open(HERE / "atlas-logo.png").convert("RGBA"))
    a = np.asarray(logo).copy()
    lettering = (a[..., 3] > 0) & (a[..., :3].max(-1) < LETTERING_MAX)
    a[lettering, :3] = TEXT_PRIMARY
    Image.fromarray(a).resize((192, 192), Image.LANCZOS).save(HERE.parent / "src/assets/atlas-logo-dark.png", optimize=True)

    out = HERE.parent / "public/brand"
    out.mkdir(exist_ok=True)
    tile = Image.new("RGBA", logo.size, "white")
    tile.alpha_composite(logo)
    tile.convert("RGB").resize((180, 180), Image.LANCZOS).save(out / "apple-touch-icon.png", optimize=True)
    mask = Image.new("L", logo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, logo.width - 1, logo.height - 1), radius=round(logo.width * 0.18), fill=255)
    rounded = Image.new("RGBA", logo.size, (0, 0, 0, 0))
    rounded.paste(tile, mask=mask)
    for size in (32, 192):
        rounded.resize((size, size), Image.LANCZOS).save(out / f"icon-{size}.png", optimize=True)


if __name__ == "__main__":
    main()
