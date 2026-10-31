"""Turn dense polygon outlines into clean cubic Bezier contours.

Each ring is split at corners, at the ends of straight segments and at
horizontal/vertical extrema. Every smooth run in between is fitted with
as few cubic curves as possible (Schneider's algorithm), with exact
axis-aligned tangents at extrema so nodes sit where type designers
expect them.
"""

import math

CORNER = 18.0      # turn (degrees) above which a vertex is a corner
LINE_MIN = 22.0    # segments longer than this are straight lines
MAX_ERROR = 1.0    # maximum fitting error in font units
MIN_SPAN = 14.0    # smooth breaks closer than this are merged
EPS = 1e-9


# --------------------------------------------------------------- vectors
def sub(lhs, rhs):
    """lhs - rhs."""
    return (lhs[0] - rhs[0], lhs[1] - rhs[1])


def add(a, b):
    """a + b."""
    return (a[0] + b[0], a[1] + b[1])


def mul(a, k):
    """a * k."""
    return (a[0] * k, a[1] * k)


def dot(a, b):
    """Dot product."""
    return a[0] * b[0] + a[1] * b[1]


def norm(a):
    """Euclidean length."""
    return math.hypot(a[0], a[1])


def unit(a):
    """Unit vector (zero vector stays zero)."""
    length = norm(a)
    return (a[0] / length, a[1] / length) if length > EPS else (0.0, 0.0)


def turn(a, b, c):
    """Turning angle in degrees at b for the path a-b-c."""
    u, v = sub(b, a), sub(c, b)
    lu, lv = norm(u), norm(v)
    if lu < EPS or lv < EPS:
        return 0.0
    cos_t = max(-1.0, min(1.0, dot(u, v) / (lu * lv)))
    return math.degrees(math.acos(cos_t))


# ----------------------------------------------------------- bezier math
def bezier(ctrl, t):
    """Point of a cubic Bezier at t."""
    u = 1 - t
    return (u ** 3 * ctrl[0][0] + 3 * u * u * t * ctrl[1][0]
            + 3 * u * t * t * ctrl[2][0] + t ** 3 * ctrl[3][0],
            u ** 3 * ctrl[0][1] + 3 * u * u * t * ctrl[1][1]
            + 3 * u * t * t * ctrl[2][1] + t ** 3 * ctrl[3][1])


def bezier_d1(ctrl, t):
    """First derivative of a cubic Bezier at t."""
    u = 1 - t
    d = [sub(ctrl[i + 1], ctrl[i]) for i in range(3)]
    return (3 * (u * u * d[0][0] + 2 * u * t * d[1][0] + t * t * d[2][0]),
            3 * (u * u * d[0][1] + 2 * u * t * d[1][1] + t * t * d[2][1]))


def bezier_d2(ctrl, t):
    """Second derivative of a cubic Bezier at t."""
    u = 1 - t
    a = add(sub(ctrl[2], mul(ctrl[1], 2)), ctrl[0])
    b = add(sub(ctrl[3], mul(ctrl[2], 2)), ctrl[1])
    return (6 * (u * a[0] + t * b[0]), 6 * (u * a[1] + t * b[1]))


def chord_params(points):
    """Chord-length parametrisation."""
    dist = [0.0]
    for i in range(1, len(points)):
        dist.append(dist[-1] + norm(sub(points[i], points[i - 1])))
    total = dist[-1] or 1.0
    return [d / total for d in dist]


def generate(points, params, t_left, t_right):  # pylint: disable=too-many-locals
    """Least-squares cubic with fixed end points and tangent directions."""
    first, last = points[0], points[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for p, t in zip(points, params):
        u = 1 - t
        a1 = mul(t_left, 3 * u * u * t)
        a2 = mul(t_right, 3 * u * t * t)
        c00 += dot(a1, a1)
        c01 += dot(a1, a2)
        c11 += dot(a2, a2)
        base = add(mul(first, u ** 3 + 3 * u * u * t),
                   mul(last, 3 * u * t * t + t ** 3))
        tmp = sub(p, base)
        x0 += dot(a1, tmp)
        x1 += dot(a2, tmp)
    det = c00 * c11 - c01 * c01
    seg = norm(sub(last, first))
    if abs(det) > EPS:
        alpha_l = (x0 * c11 - x1 * c01) / det
        alpha_r = (c00 * x1 - c01 * x0) / det
    else:
        alpha_l = alpha_r = 0.0
    if alpha_l < seg * 1e-3 or alpha_r < seg * 1e-3:
        alpha_l = alpha_r = seg / 3
    return [first, add(first, mul(t_left, alpha_l)),
            add(last, mul(t_right, alpha_r)), last]


def max_error(points, params, ctrl):
    """Largest squared distance between points and the curve."""
    worst, split = 0.0, len(points) // 2
    for i, (p, t) in enumerate(zip(points, params)):
        dist = sub(bezier(ctrl, t), p)
        err = dot(dist, dist)
        if err > worst:
            worst, split = err, i
    return worst, split


def reparameterize(points, params, ctrl):
    """One Newton-Raphson step for every parameter."""
    out = []
    for p, t in zip(points, params):
        diff = sub(bezier(ctrl, t), p)
        d1, d2 = bezier_d1(ctrl, t), bezier_d2(ctrl, t)
        den = dot(d1, d1) + dot(diff, d2)
        out.append(min(1.0, max(0.0, t - dot(diff, d1) / den))
                   if abs(den) > EPS else t)
    return out


def fit(points, t_left, t_right, error=MAX_ERROR):
    """Fit cubic Beziers through points; returns list of control quads."""
    if len(points) == 2:
        seg = norm(sub(points[1], points[0])) / 3
        return [[points[0], add(points[0], mul(t_left, seg)),
                 add(points[1], mul(t_right, seg)), points[1]]]
    params = chord_params(points)
    ctrl = generate(points, params, t_left, t_right)
    err, split = max_error(points, params, ctrl)
    if err < error * error:
        return [ctrl]
    if err < (error * 4) ** 2:
        for _ in range(12):
            params = reparameterize(points, params, ctrl)
            ctrl = generate(points, params, t_left, t_right)
            err, split = max_error(points, params, ctrl)
            if err < error * error:
                return [ctrl]
    split = max(1, min(len(points) - 2, split))
    centre = unit(sub(points[split - 1], points[split + 1]))
    if centre == (0.0, 0.0):
        centre = unit(sub(points[split - 1], points[split]))
    return (fit(points[:split + 1], t_left, centre, error)
            + fit(points[split:], mul(centre, -1), t_right, error))


# ------------------------------------------------------- ring splitting
def dedupe(points):
    """Drop consecutive duplicates and the closing repeat."""
    out = []
    for p in points:
        if not out or norm(sub(p, out[-1])) > 1e-6:
            out.append(p)
    if len(out) > 1 and norm(sub(out[0], out[-1])) < 1e-6:
        out.pop()
    return out


def insert_flat_midpoints(pts):
    """Add midpoints to short axis-parallel segments (extremum spots)."""
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        out.append(a)
        d = sub(b, a)
        length = norm(d)
        if EPS < length <= LINE_MIN and (abs(d[0]) < 1e-3 or abs(d[1]) < 1e-3):
            out.append(mul(add(a, b), 0.5))
    return out


def extrema(pts, is_line, axis):
    """Vertices where the coordinate on the other axis turns back."""
    n = len(pts)
    other = 1 - axis
    found = {}
    last_sign, last_idx = 0, None
    for step in range(2 * n):
        i = step % n
        if is_line[i]:
            last_sign, last_idx = 0, None
            continue
        delta = pts[(i + 1) % n][other] - pts[i][other]
        sign = (delta > 0.02) - (delta < -0.02)
        if sign == 0:
            continue
        if last_sign and sign != last_sign and last_idx is not None:
            span = (i - last_idx) % n
            mid = (last_idx + 1 + (span - 1) // 2) % n if span > 1 else i
            found[mid] = axis
        last_sign, last_idx = sign, i
    return found


def axis_tangent(pts, i, axis, forward):
    """Exact horizontal (axis 0) or vertical (axis 1) tangent at vertex i."""
    n = len(pts)
    d = sub(pts[(i + 1) % n], pts[(i - 1) % n])
    if not forward:
        d = mul(d, -1)
    if axis == 0:
        return (1.0 if d[0] >= 0 else -1.0, 0.0)
    return (0.0, 1.0 if d[1] >= 0 else -1.0)


def merge_breaks(pts, breaks, hard):
    """Drop smooth breaks that sit too close to a previous break."""
    if not breaks:
        return [0]
    kept = []
    for i in breaks:
        if kept and i not in hard and norm(sub(pts[i], pts[kept[-1]])) < MIN_SPAN:
            continue
        if kept and i in hard and kept[-1] not in hard and \
                norm(sub(pts[i], pts[kept[-1]])) < MIN_SPAN:
            kept.pop()
        kept.append(i)
    if len(kept) > 1 and kept[-1] not in hard and \
            norm(sub(pts[kept[-1]], pts[kept[0]])) < MIN_SPAN:
        kept.pop()
    return kept


def ring_to_segments(ring):  # pylint: disable=too-many-locals
    """Return a closed contour as [start, (kind, ...), ...] segments."""
    pts = insert_flat_midpoints(dedupe(ring))
    n = len(pts)
    if n < 3:
        return None
    seg_len = [norm(sub(pts[(i + 1) % n], pts[i])) for i in range(n)]
    is_line = [length > LINE_MIN for length in seg_len]
    corner = {i for i in range(n)
              if turn(pts[i - 1], pts[i], pts[(i + 1) % n]) > CORNER}
    line_end = set()
    for i in range(n):
        if is_line[i]:
            line_end.update((i, (i + 1) % n))
    ext = extrema(pts, is_line, 0)          # horizontal tangents (y extrema)
    ext.update(extrema(pts, is_line, 1))    # vertical tangents (x extrema)
    hard = corner | line_end
    breaks = merge_breaks(pts, sorted(hard | set(ext)), hard)
    for i in list(ext):
        if i not in breaks:
            del ext[i]

    def tangent(i, forward):
        """Unit tangent leaving (forward) or entering (backward) vertex i."""
        if i in ext and i not in corner:
            return axis_tangent(pts, i, ext[i], forward)
        if i not in corner:
            if forward and is_line[(i - 1) % n]:
                return unit(sub(pts[i], pts[(i - 1) % n]))
            if not forward and is_line[i]:
                return unit(sub(pts[i], pts[(i + 1) % n]))
        k = 3
        if forward:
            return unit(sub(pts[(i + min(k, n - 1)) % n], pts[i]))
        return unit(sub(pts[(i - min(k, n - 1)) % n], pts[i]))

    start = breaks[0]
    segments = [pts[start]]
    for j, b0 in enumerate(breaks):
        b1 = breaks[(j + 1) % len(breaks)]
        span = (b1 - b0) % n or n
        run = [pts[(b0 + k) % n] for k in range(span + 1)]
        if span == 1:
            segments.append(("line", run[-1]))
            continue
        for ctrl in fit(run, tangent(b0, True), tangent(b1, False)):
            segments.append(("curve", ctrl[1], ctrl[2], ctrl[3]))
    return merge_collinear(segments)


def merge_collinear(segments):
    """Join consecutive straight segments that point the same way."""
    start, segs = segments[0], list(segments[1:])
    changed = True
    while changed and len(segs) > 2:
        changed = False
        for k, seg in enumerate(segs):
            nxt = segs[(k + 1) % len(segs)]
            if seg[0] != "line" or nxt[0] != "line":
                continue
            prev_pt = segs[k - 1][-1] if k else start
            if turn(prev_pt, seg[1], nxt[1]) >= 0.01:
                continue
            if k == len(segs) - 1:
                # the redundant node is the contour start itself
                start = segs[0][1]
                del segs[0]
                segs[-1] = ("line", start)
            else:
                del segs[k]
            changed = True
            break
    return [start] + segs
