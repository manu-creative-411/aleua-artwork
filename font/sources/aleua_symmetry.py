"""Exact mirror and point symmetry for Aleua Sans glyphs.

Symmetric glyphs are detected automatically. Their geometry is rebuilt
from one half, and after curve fitting every node and handle is
averaged with its symmetric counterpart, so both halves end up
numerically identical.
"""

from shapely.affinity import scale as shp_scale
from shapely.geometry import box
from shapely.ops import unary_union

TOLERANCE = 0.002   # max symmetric-difference area ratio to count as symmetric
MATCH = 6.0         # max distance between a point and its counterpart

MIRROR = "mirror"   # symmetric about a vertical axis
ROTATE = "rotate"   # symmetric under a 180 degree rotation


def transform(kind, centre):
    """Return the symmetry mapping as a function on points."""
    cx, cy = centre
    if kind == MIRROR:
        return lambda p: (2 * cx - p[0], p[1])
    return lambda p: (2 * cx - p[0], 2 * cy - p[1])


def apply_geom(geom, kind, centre):
    """Apply the symmetry mapping to a shapely geometry."""
    yfact = 1 if kind == MIRROR else -1
    return shp_scale(geom, -1, yfact, origin=centre)


def detect(geom):
    """Return (kind, centre) if the glyph is symmetric, else None."""
    if geom.is_empty or geom.area <= 0:
        return None
    minx, miny, maxx, maxy = geom.bounds
    centre = ((minx + maxx) / 2, (miny + maxy) / 2)
    for kind in (MIRROR, ROTATE):
        image = apply_geom(geom, kind, centre)
        if geom.symmetric_difference(image).area / geom.area < TOLERANCE:
            return kind, centre
    return None


def symmetrize_geom(geom, kind, centre):
    """Rebuild geom from its left half so the symmetry is exact."""
    minx, miny, _, maxy = geom.bounds
    half = geom.intersection(box(minx - 10, miny - 10, centre[0],
                                 maxy + 10))
    return unary_union([half, apply_geom(half, kind, centre)]).buffer(0)


def symmetrize_contours(contours, kind, centre):  # pylint: disable=too-many-locals
    """Average every point with its counterpart; returns unmatched count."""
    mapping = transform(kind, centre)
    refs = []
    for ci, contour in enumerate(contours):
        refs.append((ci, 0, None))
        for si, seg in enumerate(contour[1:], start=1):
            for pi in range(1, len(seg)):
                refs.append((ci, si, pi))

    def get(ref):
        ci, si, pi = ref
        return contours[ci][0] if pi is None else contours[ci][si][pi]

    points = [get(r) for r in refs]
    new_points = list(points)
    unmatched = 0
    for i, p in enumerate(points):
        target = mapping(p)
        best, best_d = None, MATCH
        for j, q in enumerate(points):
            dist = abs(q[0] - target[0]) + abs(q[1] - target[1])
            if dist < best_d:
                best, best_d = j, dist
        if best is None:
            unmatched += 1
            continue
        image = mapping(points[best])
        new_points[i] = ((p[0] + image[0]) / 2, (p[1] + image[1]) / 2)

    out = [list(contour) for contour in contours]
    for ref, value in zip(refs, new_points):
        ci, si, pi = ref
        if pi is None:
            out[ci][0] = value
        else:
            seg = list(out[ci][si])
            seg[pi] = value
            out[ci][si] = tuple(seg)
    return out, unmatched
