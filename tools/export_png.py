"""Export the logo SVG files to PNG.

Each SVG under logos/<family>/svg is rendered to logos/<family>/png with
the same file name, at a fixed resolution (default 100 dpi, the
resolution of the original exports).

Usage:
    python3 tools/export_png.py [--dpi DPI] [SVG ...]
"""

import argparse
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parent.parent
LOGOS = ROOT / "logos"
CSS_DPI = 96.0


def export(svg_path, dpi):
    """Render one SVG next to its siblings in the png folder."""
    out_dir = svg_path.parent.parent / "png"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (svg_path.stem + ".png")
    cairosvg.svg2png(url=str(svg_path), write_to=str(out_path),
                     scale=dpi / CSS_DPI)
    return out_path


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dpi", type=float, default=100.0)
    parser.add_argument("svg", type=Path, nargs="*",
                        help="files to export (default: every logo SVG)")
    args = parser.parse_args()
    files = args.svg or sorted(LOGOS.glob("*/svg/*.svg"))
    for svg_path in files:
        print(f"{svg_path.name} -> {export(svg_path, args.dpi).name}")


if __name__ == "__main__":
    main()
