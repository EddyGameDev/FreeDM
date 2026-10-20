"""Generate the FreeDM application icon (``icon.ico``).

The icon is generated, not hand-drawn, so it can be rebuilt and changed at
any time:

    python scripts/make_icon.py            # writes icon.ico
    python scripts/make_icon.py --preview  # also writes icon-preview.png

Design: a rounded blue tile with a white download arrow, drawn at 256 px and
written at every size Windows wants (16 to 256).
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ICON = os.path.join(ROOT, "icon.ico")

# The FreeDM blue.
BLUE = (37, 99, 235)
BLUE_DARK = (29, 78, 216)
WHITE = (255, 255, 255)

SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int):
    """Draw the icon at one size and return the image."""
    from PIL import Image, ImageDraw

    scale = 4                       # draw big, then shrink: crisp edges
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw_ctx = ImageDraw.Draw(image)

    radius = int(big * 0.22)
    # Rounded tile with a subtle vertical gradient.
    for y in range(big):
        ratio = y / max(1, big - 1)
        colour = tuple(int(BLUE[i] + (BLUE_DARK[i] - BLUE[i]) * ratio)
                        for i in range(3))
        draw_ctx.rectangle([0, y, big, y], fill=colour + (255,))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=radius, fill=255)
    image.putalpha(mask)

    # The download arrow: a stem plus a solid chevron head.
    cx = big // 2
    stem_w = max(2, int(big * 0.10))
    stem_top = int(big * 0.22)
    stem_bottom = int(big * 0.55)
    draw_ctx.rectangle(
        [cx - stem_w // 2, stem_top, cx + stem_w // 2, stem_bottom],
        fill=WHITE + (255,))
    head_w = int(big * 0.30)
    head_top = int(big * 0.45)
    head_bottom = int(big * 0.72)
    draw_ctx.polygon(
        [(cx - head_w // 2, head_top), (cx + head_w // 2, head_top),
         (cx, head_bottom)],
        fill=WHITE + (255,))

    # The base line the arrow lands on.
    base_w = int(big * 0.46)
    base_y = int(big * 0.78)
    base_h = max(2, int(big * 0.075))
    draw_ctx.rounded_rectangle(
        [cx - base_w // 2, base_y, cx + base_w // 2, base_y + base_h],
        radius=base_h // 2, fill=WHITE + (255,))

    return image.resize((size, size), Image.LANCZOS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=ICON, help="the .ico to write")
    parser.add_argument("--preview", action="store_true",
                        help="also write a PNG preview")
    args = parser.parse_args(argv)

    try:
        from PIL import Image
    except ImportError:
        print("Pillow is needed to build the icon: pip install Pillow",
              file=sys.stderr)
        return 2

    images = [draw(size) for size in SIZES]
    # Pillow derives every size from the image it is given, so hand it the
    # largest one and let it scale down.
    images[-1].save(args.output, format="ICO",
                    sizes=[(s, s) for s in SIZES])
    print(f"wrote {args.output} ({os.path.getsize(args.output)} bytes)")
    if args.preview:
        preview = os.path.join(ROOT, "icon-preview.png")
        Image.open(args.output).size  # make sure it reads back
        draw(256).save(preview)
        print(f"wrote {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
