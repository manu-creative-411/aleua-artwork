"""Font file output for Aleua Sans: Bezier contours, TTF and OTF."""

import math

from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.timeTools import timestampNow
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from shapely.geometry import MultiPolygon
from shapely.geometry.polygon import orient

from aleua_curves import ring_to_segments

UPM = 1000
VERSION = 1.4
AUTHOR = "Asociación ALEUA"
COPYRIGHT = f"Copyright 2026 {AUTHOR}"
DESCRIPTION = ("Aleua Sans is a rounded geometric monoline typeface designed "
               "for the visual identity of Asociación ALEUA (Asociación de "
               "Lazos Europeos y Acción), Mengíbar, Jaén, Spain.")
LICENSE = ("This Font Software is licensed under the SIL Open Font License, "
           "Version 1.1. This license is available with a FAQ at: "
           "https://openfontlicense.org")
LICENSE_URL = "https://openfontlicense.org"

ZONES = (-222, 0, 510, 700, 752)


def snap(y):
    """Snap a y coordinate onto the alignment zones it is close to."""
    for zone in ZONES:
        if abs(y - zone) <= 2.5:
            return zone
    return y


def outline(geom, shift):
    """Cubic contours of a glyph, shifted and snapped to the zones."""
    contours = []
    if geom.is_empty:
        return contours
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]

    def place(p):
        return (p[0] + shift, snap(p[1]))

    for poly in polys:
        poly = orient(poly.simplify(0.02), sign=-1.0)
        for ring in [poly.exterior] + list(poly.interiors):
            segs = ring_to_segments(list(ring.coords))
            if not segs:
                continue
            contour = [place(segs[0])]
            for seg in segs[1:]:
                contour.append((seg[0],) + tuple(place(p) for p in seg[1:]))
            contours.append(contour)
    return contours


def draw_contours(contours, pen):
    """Draw cubic contours into any segment pen."""
    for contour in contours:
        pen.moveTo(contour[0])
        for seg in contour[1:]:
            if seg[0] == "line":
                pen.lineTo(seg[1])
            else:
                pen.curveTo(*seg[1:])
        pen.closePath()


def left_edge(contours):
    """Smallest on-curve x of a set of contours (0 when empty)."""
    xs = [contour[0][0] for contour in contours]
    xs += [seg[-1][0] for contour in contours for seg in contour[1:]]
    return int(math.floor(min(xs))) if xs else 0


def notdef_contours():
    """Box contours for .notdef."""
    contours = []
    for ring in ([(50, 0), (50, 700), (450, 700), (450, 0)],
                 [(110, 60), (390, 60), (390, 640), (110, 640)]):
        contours.append([ring[0]] + [("line", p) for p in ring[1:]])
    return contours


def setup_common(fb, feature_text):
    """Tables shared by the TTF and OTF builds."""
    fb.setupHorizontalHeader(ascent=1000, descent=-250)
    fb.setupNameTable({
        "copyright": COPYRIGHT,
        "familyName": "Aleua Sans",
        "styleName": "Bold",
        "uniqueFontIdentifier": f"{VERSION:.3f};ALEU;AleuaSans-Bold",
        "fullName": "Aleua Sans Bold",
        "version": f"Version {VERSION:.3f}",
        "psName": "AleuaSans-Bold",
        "manufacturer": AUTHOR,
        "designer": AUTHOR,
        "description": DESCRIPTION,
        "licenseDescription": LICENSE,
        "licenseInfoURL": LICENSE_URL,
    })
    fb.setupOS2(sTypoAscender=1000, sTypoDescender=-250, sTypoLineGap=0,
                usWinAscent=1000, usWinDescent=250, sxHeight=510,
                sCapHeight=700, usWeightClass=700, fsSelection=0x20,
                fsType=0, achVendID="ALEU")
    fb.setupPost()
    now = timestampNow()
    fb.setupHead(unitsPerEm=UPM, macStyle=1, created=now, modified=now,
                 fontRevision=VERSION)
    addOpenTypeFeaturesFromString(fb.font, feature_text)


def straight_lines(contours):
    """Exact straight segments (start, end) of float contours."""
    lines = []
    for contour in contours:
        prev = contour[0]
        for seg in contour[1:]:
            if seg[0] == "line":
                lines.append((prev, seg[1]))
            prev = seg[-1]
    return lines


def rounding_options(point):
    """The four integer points around a float point."""
    xs = {math.floor(point[0]), math.ceil(point[0])}
    ys = {math.floor(point[1]), math.ceil(point[1])}
    return [(x, y) for x in xs for y in ys]


def angle_error(start, end, target):
    """Angular distance between a segment and a target angle (radians)."""
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    return abs((angle - target + math.pi) % (2 * math.pi) - math.pi)


def keep_line_slopes(glyph, contours):  # pylint: disable=too-many-locals
    """Round straight-segment end points so each keeps its exact slope.

    TrueType only stores integers. Instead of rounding every point to
    the nearest integer, the end points of diagonal lines (longest
    first) are rounded to whichever neighbouring integer best preserves
    the angle of the exact line, so parallel edges stay parallel.
    """
    coords = glyph.coordinates
    if not coords:
        return
    index = {}
    for i, (point, flag) in enumerate(zip(coords, glyph.flags)):
        if flag & 1:
            index.setdefault(tuple(point), i)
    fixed = {}
    lines = sorted(straight_lines(contours),
                   key=lambda ln: -math.dist(ln[0], ln[1]))
    for start, end in lines:
        if abs(end[0] - start[0]) < 1 or abs(end[1] - start[1]) < 1:
            continue
        i = index.get((round(start[0]), round(start[1])))
        j = index.get((round(end[0]), round(end[1])))
        if i is None or j is None or i == j:
            continue
        target = math.atan2(end[1] - start[1], end[0] - start[0])
        starts = [fixed[i]] if i in fixed else rounding_options(start)
        ends = [fixed[j]] if j in fixed else rounding_options(end)
        best = min(((a, b) for a in starts for b in ends),
                   key=lambda pair, aim=target: angle_error(pair[0], pair[1],
                                                          aim))
        fixed[i], fixed[j] = best
        coords[i], coords[j] = best


def fix_integer_symmetry(glyph, kind):  # pylint: disable=too-many-locals
    """Make rounded TrueType points exactly symmetric again."""
    coords = glyph.coordinates
    if not coords:
        return
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    sum_x, sum_y = min(xs) + max(xs), min(ys) + max(ys)

    def image(point):
        if kind == "mirror":
            return (sum_x - point[0], point[1])
        return (sum_x - point[0], sum_y - point[1])

    fixed = set()
    points = list(coords)
    for i, point in enumerate(points):
        if i in fixed:
            continue
        target = image(point)
        best, best_d = None, 1.5
        for j, other in enumerate(points):
            if j in fixed or j == i:
                continue
            dist = abs(other[0] - target[0]) + abs(other[1] - target[1])
            if dist < best_d:
                best, best_d = j, dist
        if best is not None:
            coords[best] = target
            points[best] = target
            fixed.update((i, best))


def save_ttf(path, order, cmap, metrics, contours, feature_text,  # pylint: disable=too-many-arguments,too-many-positional-arguments
             symmetry=None):
    """Write a TrueType (quadratic) font."""
    symmetry = symmetry or {}
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        draw_contours(contours[name], Cu2QuPen(pen, max_err=0.5))
        glyphs[name] = pen.glyph()
        keep_line_slopes(glyphs[name], contours[name])
        if name in symmetry:
            fix_integer_symmetry(glyphs[name], symmetry[name])
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    glyf = fb.font["glyf"]
    fb.setupHorizontalMetrics({
        n: (metrics[n], glyf[n].xMin if glyf[n].numberOfContours else 0)
        for n in order})
    setup_common(fb, feature_text)
    fb.save(path)


def save_otf(path, order, cmap, metrics, contours, feature_text):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Write a CFF (cubic) OpenType font."""
    charstrings = {}
    lsbs = {}
    for name in order:
        pen = T2CharStringPen(metrics[name], None, roundTolerance=0)
        draw_contours(contours[name], ReverseContourPen(pen))
        charstrings[name] = pen.getCharString()
        lsbs[name] = left_edge(contours[name])
    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupCFF("AleuaSans-Bold", {"FullName": "Aleua Sans Bold",
                                   "FamilyName": "Aleua Sans",
                                   "Weight": "Bold",
                                   "Notice": COPYRIGHT,
                                   "version": f"{VERSION:.3f}"},
                charstrings, {})
    fb.setupHorizontalMetrics({n: (metrics[n], lsbs[n]) for n in order})
    setup_common(fb, feature_text)
    fb.save(path)
