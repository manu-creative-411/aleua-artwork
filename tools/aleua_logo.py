"""Keep the A of the ALEUA imagotype and the Aleua Sans font in sync.

The imagotype draws each A as the open A of Aleua Sans (no crossbar)
with a gap where the coloured swoosh ("rabo") crosses the right leg.

Commands:
    extract-swoosh  Measure the swoosh and the gap from an imagotype SVG
                    and store them, in font units, for the font build
                    (font/sources/logo_swoosh.json), so the ss01 A of
                    the font matches the logotype.
    fix-a           Rebuild every A in the given SVG files from the exact
                    open A of the font minus the measured gap, so the
                    stroke edges are single straight segments with
                    identical inner and outer slopes.

Usage:
    python3 tools/aleua_logo.py extract-swoosh SVG [--font OTF] [--out JSON]
    python3 tools/aleua_logo.py fix-a SVG [SVG ...] [--font OTF]
"""

import argparse
import json
import re
import sys
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from shapely.affinity import affine_transform
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from svgpathtools import parse_path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "font" / "sources"))
from aleua_curves import ring_to_segments  # noqa: E402  pylint: disable=wrong-import-position

DEFAULT_FONT = ROOT / "font" / "fonts" / "otf" / "AleuaSans-Bold.otf"
DEFAULT_JSON = ROOT / "font" / "sources" / "logo_swoosh.json"
OPEN_A = "A.ss02"
STEP = 0.02          # flattening step in SVG user units
SLIVER = 1.5         # font units: thinner differences are rounding noise
MIN_AREA = 200.0     # font units squared: smaller cut pieces are noise
CAP_HEIGHT = 700.0
EXTEND = 3.0         # font units the gap reaches past the A outline
BRIDGE = 1.0         # half width of hairlines removed after cutting
MITRE = 100.0        # keep sharp corners sharp when offsetting
STABLE = 1.0         # font units: closer results count as unchanged

GROUP_RE = re.compile(r'<g\b[^>]*inkscape:label="A"[^>]*>(.*?)</g>', re.S)
PATH_RE = re.compile(r'<path\b[^>]*>', re.S)
LABEL_RE = re.compile(r'inkscape:label="([^"]*)"')
D_RE = re.compile(r'\bd="([^"]*)"')


# ------------------------------------------------------------ geometry
def flatten_svg_path(d_attr):
    """SVG path data to a shapely geometry (SVG user units, y down)."""
    polygons = []
    for sub in parse_path(d_attr).continuous_subpaths():
        pts = []
        for seg in sub:
            steps = max(2, int(seg.length() / STEP))
            pts.extend(seg.point(i / steps) for i in range(steps))
        if len(pts) > 2:
            polygons.append(Polygon([(p.real, p.imag) for p in pts]))
    return unary_union([p.buffer(0) for p in polygons])


def cubic_points(ctrl, steps):
    """Points of a cubic Bezier (excluding its start point)."""
    p0, p1, p2, p3 = ctrl
    points = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        weights = (u ** 3, 3 * u * u * t, 3 * u * t * t, t ** 3)
        points.append((sum(w * p[0] for w, p in zip(weights, (p0, p1, p2, p3))),
                       sum(w * p[1] for w, p in zip(weights, (p0, p1, p2, p3)))))
    return points


def font_glyph(font_path, name, steps=200):
    """Outline of a glyph as a shapely geometry in font units (y up)."""
    font = TTFont(str(font_path))
    rec = RecordingPen()
    font.getGlyphSet()[name].draw(rec)
    rings, ring = [], []
    for op, args in rec.value:
        if op in ("moveTo", "lineTo"):
            ring = [args[0]] if op == "moveTo" else ring + [args[0]]
        elif op == "curveTo":
            ring += cubic_points((ring[-1],) + tuple(args), steps)
        elif op == "closePath":
            rings.append(Polygon(ring).buffer(0))
    return unary_union(rings)


def svg_to_font(geom, logo_a, open_a):
    """Map SVG user units onto font units using the A bounding boxes."""
    sx0, sy0, _, sy1 = logo_a.bounds
    fx0, fy0, _, _ = open_a.bounds
    scale = (sy1 - sy0) / CAP_HEIGHT
    # x_font = (x - sx0) / scale + fx0 ; y_font = (sy1 - y) / scale + fy0
    return affine_transform(geom, [1 / scale, 0, 0, -1 / scale,
                                   fx0 - sx0 / scale, fy0 + sy1 / scale])


def font_to_svg_matrix(logo_a, open_a):
    """Affine parameters (a, b, d, e, xoff, yoff) from font units to SVG."""
    sx0, sy0, _, sy1 = logo_a.bounds
    fx0, fy0, _, _ = open_a.bounds
    scale = (sy1 - sy0) / CAP_HEIGHT
    return [scale, 0, 0, -scale, sx0 - fx0 * scale, sy1 + fy0 * scale]


def clean(geom):
    """Drop rounding slivers and tiny pieces."""
    geom = geom.buffer(-SLIVER / 2, join_style="mitre",
                       mitre_limit=MITRE).buffer(
        SLIVER / 2, join_style="mitre", mitre_limit=MITRE)
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    return unary_union([p for p in parts if p.area >= MIN_AREA])


def apply_cut(open_a, cut):
    """Open A minus the gap, with no zero-width bridges left behind.

    The gap is extended a little beyond the A outline (never inside it)
    and strips thinner than two BRIDGE widths are opened away, so no
    hairline can join both parts of the leg. Straight edges survive the
    opening unchanged.
    """
    reach = cut.buffer(EXTEND, join_style="mitre",
                       mitre_limit=MITRE).difference(open_a)
    result = open_a.difference(unary_union([cut, reach]))
    result = result.buffer(-BRIDGE, join_style="mitre",
                           mitre_limit=MITRE).buffer(
        BRIDGE, join_style="mitre", mitre_limit=MITRE)
    parts = result.geoms if isinstance(result, MultiPolygon) else [result]
    return unary_union([p for p in parts if p.area >= MIN_AREA])


def measure(group_xml, open_a):
    """Return (logo A, swoosh, gap cut) of one A group, in font units."""
    logo_d = swoosh_d = None
    for tag in PATH_RE.findall(group_xml):
        label = LABEL_RE.search(tag)
        d_attr = D_RE.search(tag).group(1)
        if label and label.group(1) == "rabo":
            swoosh_d = d_attr
        else:
            logo_d = d_attr
    logo_svg = flatten_svg_path(logo_d)
    logo = svg_to_font(logo_svg, logo_svg, open_a)
    swoosh = svg_to_font(flatten_svg_path(swoosh_d), logo_svg, open_a)
    cut = clean(open_a.difference(logo))
    return logo_svg, swoosh, cut


# ------------------------------------------------------------- writing
def contours_to_d(geom, matrix):
    """Fit Bezier contours to a font-unit geometry and emit SVG path data."""
    a, _, _, e, xoff, yoff = matrix

    def fmt(point):
        return f"{a * point[0] + xoff:.5f},{e * point[1] + yoff:.5f}"

    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    commands = []
    for poly in parts:
        poly = orient(poly.simplify(0.02), sign=1.0)
        for ring in [poly.exterior] + list(poly.interiors):
            segs = ring_to_segments(list(ring.coords))
            if not segs:
                continue
            commands.append("M " + fmt(segs[0]))
            for seg in segs[1:]:
                if seg[0] == "line":
                    commands.append("L " + fmt(seg[1]))
                else:
                    commands.append("C " + " ".join(fmt(p) for p in seg[1:]))
            commands.append("Z")
    return " ".join(commands)


def fix_svg(path, open_a):
    """Rewrite every A of an imagotype SVG; returns the number changed.

    An A that already matches the clean geometry within the curve fitting
    tolerance is left untouched, so running the command again is a no-op.
    """
    text = path.read_text(encoding="utf-8")
    fixed = 0
    for group in GROUP_RE.finditer(text):
        group_xml = group.group(1)
        logo_svg, _, cut = measure(group_xml, open_a)
        new_a = apply_cut(open_a, cut)
        current = svg_to_font(logo_svg, logo_svg, open_a)
        new_d = contours_to_d(new_a, font_to_svg_matrix(logo_svg, open_a))
        for tag in PATH_RE.findall(group_xml):
            label = LABEL_RE.search(tag)
            if label and label.group(1) == "rabo":
                continue
            old_d = D_RE.search(tag).group(1)
            if (current.hausdorff_distance(new_a) < STABLE
                    and len(parse_path(old_d)) == len(parse_path(new_d))):
                continue  # already clean: keep the file byte-identical
            new_tag = D_RE.sub(f'd="{new_d}"', tag, count=1)
            text = text.replace(tag, new_tag, 1)
            fixed += 1
    path.write_text(text, encoding="utf-8")
    return fixed


def ring_list(geom, origin):
    """Exterior and interior rings relative to origin, rounded."""
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    out = []
    for poly in parts:
        poly = orient(poly.simplify(0.05), sign=1.0)
        out.append({
            "exterior": [[round(x - origin[0], 2), round(y - origin[1], 2)]
                         for x, y in poly.exterior.coords[:-1]],
            "interiors": [[[round(x - origin[0], 2), round(y - origin[1], 2)]
                           for x, y in ring.coords[:-1]]
                          for ring in poly.interiors],
        })
    return out


def rings_to_geom(items, origin):
    """Shapely geometry from rings stored relative to origin."""
    polys = []
    for item in items:
        shell = [(x + origin[0], y + origin[1]) for x, y in item["exterior"]]
        holes = [[(x + origin[0], y + origin[1]) for x, y in ring]
                 for ring in item["interiors"]]
        polys.append(Polygon(shell, holes).buffer(0))
    return unary_union(polys)


def extract(svg_path, open_a, out_path):
    """Store the swoosh and gap of the first A, relative to the A bbox."""
    text = svg_path.read_text(encoding="utf-8")
    group = GROUP_RE.search(text)
    if group is None:
        raise SystemExit(f"no A group found in {svg_path}")
    _, swoosh, cut = measure(group.group(1), open_a)
    origin = open_a.bounds[:2]
    if out_path.exists():
        stored = json.loads(out_path.read_text(encoding="utf-8"))
        known_cut = rings_to_geom(stored["cut"], origin)
        known_swoosh = rings_to_geom(stored["swoosh"], origin)
        if (known_cut.hausdorff_distance(cut) < STABLE
                and known_swoosh.hausdorff_distance(swoosh) < STABLE):
            print(f"{out_path} already matches {svg_path.name}; unchanged")
            return
    data = {
        "source": svg_path.name,
        "units": "font units relative to the bounding box of A.ss02",
        "swoosh": ring_list(swoosh, origin),
        "cut": ring_list(cut, origin),
    }
    out_path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out_path}: swoosh area {swoosh.area:.0f}, "
          f"cut area {cut.area:.0f} (font units^2)")


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ext = sub.add_parser("extract-swoosh")
    ext.add_argument("svg", type=Path)
    ext.add_argument("--font", type=Path, default=DEFAULT_FONT)
    ext.add_argument("--out", type=Path, default=DEFAULT_JSON)
    fix = sub.add_parser("fix-a")
    fix.add_argument("svg", type=Path, nargs="+")
    fix.add_argument("--font", type=Path, default=DEFAULT_FONT)
    args = parser.parse_args()
    open_a = font_glyph(args.font, OPEN_A)
    if args.command == "extract-swoosh":
        extract(args.svg, open_a, args.out)
    else:
        for path in args.svg:
            print(f"{path.name}: {fix_svg(path, open_a)} A paths rebuilt")


if __name__ == "__main__":
    main()
