"""Render the specimen images used in the README.

Usage:
    python3 tools/make_specimen.py [--font PATH] [--output-dir DIR]

Requires Pillow built with libraqm so OpenType features (kerning and
stylistic sets) are applied.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FONT = ROOT / "fonts" / "otf" / "AleuaSans-Bold.otf"
DEFAULT_OUT = ROOT / "docs" / "images"

INK = (16, 82, 172)
ACCENT = (82, 168, 232)
GOLD = (250, 186, 0)
MUTED = (120, 130, 150)
PAPER = (255, 255, 255)
WIDTH = 2400

CHARSET = [
    "ABCDEFGHIJKLMNÑOPQRSTUVWXYZ",
    "abcdefghijklmnñopqrstuvwxyz",
    "ÁÀÂÄÃÇÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÝ",
    "áàâäãçéèêëíìîïóòôöõúùûüýÿ",
    "0123456789 ªº % € $ # & @",
    ". , : ; ! ¡ ? ¿ ' \" ‘ ’ “ ” « » ( ) / - – — _ + = *",
]


def font(path, size):
    """Load the font at a pixel size."""
    return ImageFont.truetype(str(path), size)


def text(draw, xy, value, typeface, fill, feats=None):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Draw text with optional OpenType features."""
    draw.text(xy, value, font=typeface, fill=fill, features=feats)


def hero(path, out):
    """Title, motto and running text."""
    img = Image.new("RGB", (WIDTH, 1150), PAPER)
    draw = ImageDraw.Draw(img)
    text(draw, (90, 60), "ALEUA", font(path, 360), INK, ["ss01"])
    text(draw, (95, 470), "Asociación de Lazos Europeos y Acción",
         font(path, 110), INK)
    text(draw, (95, 640), "Aleua Sans Bold · rounded geometric monoline",
         font(path, 64), ACCENT)
    text(draw, (95, 760),
         "El veloz murciélago hindú comía feliz cardillo y kiwi.",
         font(path, 84), INK)
    text(draw, (95, 880),
         "La cigüeña tocaba el saxofón detrás del palenque de paja.",
         font(path, 84), INK)
    text(draw, (95, 1010), "Mengíbar · Jaén · España · 2026",
         font(path, 56), MUTED)
    img.save(out / "specimen.png")


def charset(path, out):
    """Every encoded character, grouped by line."""
    size = 92
    img = Image.new("RGB", (WIDTH, 80 + len(CHARSET) * int(size * 1.55)),
                    PAPER)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(CHARSET):
        text(draw, (90, 40 + i * int(size * 1.55)), line, font(path, size),
             INK)
    img.save(out / "charset.png")


def alternates(path, out):
    """Default A and the two stylistic sets."""
    rows = [("default", None), ("ss01 · logo swoosh A", ["ss01"]),
            ("ss02 · open A", ["ss02"])]
    row_height = 300
    img = Image.new("RGB", (WIDTH, 40 + row_height * len(rows)), PAPER)
    draw = ImageDraw.Draw(img)
    big, label = font(path, 240), font(path, 60)
    for i, (name, feats) in enumerate(rows):
        y = 20 + i * row_height
        text(draw, (90, y - 50), "ALEUA Acción", big, INK, feats)
        text(draw, (1720, y + 110), name, label, GOLD if feats else MUTED)
    img.save(out / "alternates.png")


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not features.check("raqm"):
        print("warning: Pillow lacks libraqm; kerning and ss01/ss02 "
              "will not be shown")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    hero(args.font, args.output_dir)
    charset(args.font, args.output_dir)
    alternates(args.font, args.output_dir)
    print(f"specimen images written to {args.output_dir}")


if __name__ == "__main__":
    main()
