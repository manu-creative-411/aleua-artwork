"""Build the Aleua Sans fonts from monoline stroke skeletons.

Each glyph is described as a set of centre-line strokes on a design
grid. Strokes are expanded with round caps and joins (like the ALEUA
logotype), merged, made exactly symmetric where applicable, spaced and
kerned optically, fitted with Bezier curves and saved as OTF and TTF.

Usage:
    python3 sources/build_aleua.py [--output-dir DIR]
"""

import argparse
import math
from pathlib import Path

from shapely.affinity import scale as shp_scale
from shapely.affinity import translate
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from aleua_logo_a import logo_a
from aleua_output import notdef_contours, outline, save_otf, save_ttf
from aleua_spacing import Spaced, fit_accents, kern_feature, spacing_rule
from aleua_symmetry import detect, symmetrize_contours, symmetrize_geom

FILE_STEM = "AleuaSans-Bold"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "fonts"
UPM = 1000
DIGITS = ["zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine"]
HW = 55            # half stroke width (logo: 110 units per stem)
BASE = 70          # design-grid baseline (see to_font)
CAP = 630          # skeleton cap height (outline 700)
MID = 350
XT = 450           # skeleton x-height (outline 520)
ASC = 680          # skeleton ascender (outline 750)
DESC = -140        # skeleton descender (outline -210)
RADIUS = 125       # soft corner radius on the design grid
BOWL_RADIUS = 55   # tighter outer corner for B, P and R
CLOSE = 95         # inner corner radius for soft-cornered strokes
SCALE = 590 / 560  # design grid (70..630) -> font units (55..645)
TAB_WIDTH = 560    # advance width of tabular figures
ACC_HW = 48        # accent half width
NARROW_SPREAD = 0.8  # tighter circumflex/dieresis over I and i
CAP_ACC = 800      # skeleton bottom of capital accents
LOW_ACC = 625      # skeleton bottom of lowercase accents


def to_font(x, y):
    """Map a design-grid point to font units."""
    return (x * SCALE, HW + (y - BASE) * SCALE)


def grid_y(y):
    """Map a design-grid height to font units."""
    return to_font(0, y)[1]


# --------------------------------------------------------------- geometry
def arc(cx, cy, rx, ry, a0, a1, steps=None):  # pylint: disable=too-many-arguments,too-many-positional-arguments
    """Sample an elliptic arc from angle a0 to a1 (degrees)."""
    if steps is None:
        steps = max(16, int(abs(a1 - a0)))
    pts = []
    for i in range(steps + 1):
        ang = math.radians(a0 + (a1 - a0) * i / steps)
        pts.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
    return pts


def bez(p0, p1, p2, p3, steps=120):
    """Sample a cubic Bezier curve."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append((
            u ** 3 * p0[0] + 3 * u * u * t * p1[0]
            + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1]
            + 3 * u * t * t * p2[1] + t ** 3 * p3[1],
        ))
    return pts


def fillet(points, radius):  # pylint: disable=too-many-locals
    """Round every sharp corner (turn > 30 degrees) of a polyline."""
    if radius <= 0 or len(points) < 3:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        ax, ay = points[i - 1]
        bx, by = points[i]
        cx, cy = points[i + 1]
        v1 = (ax - bx, ay - by)
        v2 = (cx - bx, cy - by)
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        cos_t = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
        theta = math.acos(max(-1.0, min(1.0, cos_t)))
        if math.degrees(math.pi - theta) < 30 or math.degrees(theta) < 75:
            out.append((bx, by))
            continue
        dist = min(radius / math.tan(theta / 2), l1 / 2, l2 / 2)
        rad = dist * math.tan(theta / 2)
        u1 = (v1[0] / l1, v1[1] / l1)
        u2 = (v2[0] / l2, v2[1] / l2)
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        blen = math.hypot(*bis)
        centre = (bx + bis[0] / blen * rad / math.sin(theta / 2),
                  by + bis[1] / blen * rad / math.sin(theta / 2))
        p1 = (bx + u1[0] * dist, by + u1[1] * dist)
        p2 = (bx + u2[0] * dist, by + u2[1] * dist)
        a1 = math.atan2(p1[1] - centre[1], p1[0] - centre[0])
        a2 = math.atan2(p2[1] - centre[1], p2[0] - centre[0])
        delta = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        for j in range(33):
            ang = a1 + delta * j / 32
            out.append((centre[0] + rad * math.cos(ang),
                        centre[1] + rad * math.sin(ang)))
    out.append(points[-1])
    return out


def has_soft_corner(points):
    """True if the polyline has a right-ish corner that gets a fillet."""
    for i in range(1, len(points) - 1):
        v1 = (points[i - 1][0] - points[i][0], points[i - 1][1] - points[i][1])
        v2 = (points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        cos_t = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
        theta = math.degrees(math.acos(max(-1.0, min(1.0, cos_t))))
        if 75 <= theta <= 150:
            return True
    return False


class Stroke:  # pylint: disable=too-few-public-methods
    """A centre-line stroke with its own corner radius and half width."""

    def __init__(self, points, radius=RADIUS, half=HW, close=None):
        self.points = [to_font(x, y) for x, y in points]
        self.radius = radius * SCALE
        self.half = half
        self.close = (radius >= RADIUS) if close is None else close

    def shape(self):
        """Expand the stroke into a polygon."""
        if len(self.points) == 1:
            return Point(self.points[0]).buffer(self.half, 64)
        line = LineString(fillet(self.points, self.radius))
        geom = line.buffer(self.half, quad_segs=32, cap_style="round",
                           join_style="round")
        if self.close and has_soft_corner(self.points):
            geom = geom.buffer(CLOSE, quad_segs=32).buffer(-CLOSE,
                                                           quad_segs=32)
        return geom


def S(points, radius=RADIUS, half=HW, close=None):  # pylint: disable=invalid-name
    """Shorthand for Stroke."""
    return Stroke(points, radius, half, close)


def dot(x, y, r=68):
    """A round dot."""
    return Stroke([(x, y)], half=r)


def merge(items):
    """Union of strokes and raw shapely geometries."""
    geoms = [it.shape() if isinstance(it, Stroke) else it for it in items]
    return unary_union(geoms)


def flip(geom, centre_y):
    """Rotate a glyph by 180 degrees (used for inverted punctuation)."""
    minx, _, maxx, _ = geom.bounds
    rotated = shp_scale(geom, -1, -1, origin=((minx + maxx) / 2, centre_y))
    return rotated


# ------------------------------------------------------------- uppercase
def cap_a_bare():
    """A without crossbar, as in the logotype."""
    return [S([(0, BASE), (258, CAP), (516, BASE)], radius=0)]


def cap_a():
    """Text A with a crossbar for legibility."""
    return cap_a_bare() + [S([(78, 225), (438, 225)])]


def cap_b():
    """B."""
    frame = [(170, CAP), (0, CAP), (0, BASE), (190, BASE)]
    top = arc(170, 490, 140, 140, 90, -90) + [(0, MID)]
    low = [(0, MID), (190, MID)] + arc(190, 210, 140, 140, 90, -90)
    return [S(frame, radius=BOWL_RADIUS, close=False),
            S(top, radius=0), S(low, radius=0)]


def cap_c():
    """C."""
    return [S(arc(280, MID, 270, 280, 42, 318))]


def cap_d():
    """D."""
    bowl_pts = [(0, CAP), (130, CAP)] + arc(130, MID, 280, 280, 90, -90)
    bowl_pts += [(0, BASE)]
    return [S([(0, CAP), (0, BASE)]), S(bowl_pts, radius=0)]


def cap_e():
    """E with soft left corners like the logotype."""
    return [S([(370, CAP), (0, CAP), (0, BASE), (370, BASE)]),
            S([(0, MID), (280, MID)])]


def cap_f():
    """F."""
    return [S([(370, CAP), (0, CAP), (0, BASE)]), S([(0, MID), (280, MID)])]


def cap_g():
    """G."""
    pts = arc(290, MID, 280, 280, 40, 360) + [(330, MID)]
    return [S(pts, close=False)]


def cap_h():
    """H."""
    return [S([(0, CAP), (0, BASE)]), S([(420, CAP), (420, BASE)]),
            S([(0, MID), (420, MID)])]


def cap_i():
    """I."""
    return [S([(0, CAP), (0, BASE)])]


def cap_j():
    """J."""
    return [S([(320, CAP), (320, 230)] + arc(160, 230, 160, 160, 0, -180))]


def cap_k():
    """K."""
    return [S([(0, CAP), (0, BASE)]), S([(370, CAP), (30, 320)]),
            S([(150, 420), (390, BASE)])]


def cap_l():
    """L with soft corner like the logotype."""
    return [S([(0, CAP), (0, BASE), (307, BASE)])]


def cap_m():
    """M."""
    return [S([(0, BASE), (0, CAP), (270, 230), (540, CAP), (540, BASE)],
              radius=0)]


def cap_n():
    """N."""
    return [S([(0, BASE), (0, CAP), (430, BASE), (430, CAP)], radius=0)]


def cap_o():
    """O."""
    return [S(arc(290, MID, 290, 280, 0, 360, 120))]


def cap_p():
    """P."""
    frame = [(0, BASE), (0, CAP), (180, CAP)]
    bowl_pts = arc(180, 455, 175, 175, 90, -90) + [(0, 280)]
    return [S(frame, radius=BOWL_RADIUS, close=False),
            S(bowl_pts, radius=0)]


def cap_q():
    """Q."""
    return cap_o() + [S([(380, 180), (580, 0)])]


def cap_r():
    """R."""
    return cap_p() + [S([(200, 280), (390, BASE)])]


def cap_s():
    """S built from two tangent elliptic arcs."""
    pts = arc(210, 490, 190, 140, 20, 270) + arc(210, 210, 210, 140, 90, -160)
    return [S(pts)]


def cap_t():
    """T."""
    return [S([(0, CAP), (460, CAP)]), S([(230, CAP), (230, BASE)])]


def cap_u():
    """U with round bottom like the logotype."""
    pts = [(0, CAP), (0, 262)] + arc(192, 262, 192, 192, 180, 360)
    pts += [(384, CAP)]
    return [S(pts)]


def cap_v():
    """V."""
    return [S([(0, CAP), (250, BASE), (500, CAP)], radius=0)]


def cap_w():
    """W."""
    return [S([(0, CAP), (170, BASE), (340, CAP), (510, BASE), (680, CAP)],
              radius=0)]


def cap_x():
    """X."""
    return [S([(0, CAP), (440, BASE)]), S([(440, CAP), (0, BASE)])]


def cap_y():
    """Y."""
    return [S([(0, CAP), (230, 320), (460, CAP)], radius=0),
            S([(230, 320), (230, BASE)])]


def cap_z():
    """Z."""
    return [S([(0, CAP), (410, CAP), (0, BASE), (410, BASE)], radius=0)]


# ------------------------------------------------------------- lowercase
RO = 190  # lowercase bowl radius
CY = BASE + RO


def bowl(cx):
    """Round lowercase bowl."""
    return S(arc(cx, CY, RO - 5, RO, 0, 360, 100))


def low_a():
    """Single-storey geometric a."""
    return [bowl(185), S([(370, XT), (370, BASE)])]


def low_b():
    """b."""
    return [S([(0, ASC), (0, BASE)]), bowl(185)]


def low_c():
    """c."""
    return [S(arc(190, CY, 185, RO, 45, 315))]


def low_d():
    """d."""
    return [bowl(185), S([(370, ASC), (370, BASE)])]


def low_e():
    """e."""
    return [S([(10, CY), (375, CY)]), S(arc(190, CY, 185, RO, 0, 315))]


def low_f():
    """f."""
    pts = [(110, BASE), (110, ASC - 110)] + arc(220, ASC - 110, 110, 110,
                                                180, 50)
    return [S(pts), S([(0, XT), (260, XT)])]


def low_g():
    """g."""
    stem = [(370, XT), (370, -10)] + arc(240, -10, 130, 130, 0, -165)
    return [bowl(185), S(stem)]


def low_h():
    """h."""
    arch = arc(175, 275, 175, 175, 180, 0) + [(350, BASE)]
    return [S([(0, ASC), (0, BASE)]), S(arch)]


def low_i():
    """i."""
    return [S([(0, XT), (0, BASE)]), dot(0, 625, 62)]


def low_dotlessi():
    """Dotless i, base for accented i."""
    return [S([(0, XT), (0, BASE)])]


def low_j():
    """j."""
    pts = [(0, XT), (0, -40)] + arc(-80, -40, 80, 100, 0, -150)
    return [S(pts), dot(0, 625, 62)]


def low_k():
    """k."""
    return [S([(0, ASC), (0, BASE)]), S([(310, XT), (30, 250)]),
            S([(130, 310), (330, BASE)])]


def low_l():
    """l."""
    return [S([(0, ASC), (0, BASE)])]


def low_m():
    """m."""
    a1 = arc(140, 310, 140, 140, 180, 0) + [(280, BASE)]
    a2 = arc(420, 310, 140, 140, 180, 0) + [(560, BASE)]
    return [S([(0, XT), (0, BASE)]), S(a1), S(a2)]


def low_n():
    """n."""
    arch = arc(175, 275, 175, 175, 180, 0) + [(350, BASE)]
    return [S([(0, XT), (0, BASE)]), S(arch)]


def low_o():
    """o."""
    return [bowl(190)]


def low_p():
    """p."""
    return [S([(0, XT), (0, DESC)]), bowl(185)]


def low_q():
    """q."""
    return [bowl(185), S([(370, XT), (370, DESC)])]


def low_r():
    """r."""
    return [S([(0, XT), (0, BASE)]),
            S(arc(185, 265, 185, 185, 180, 65))]


def low_s():
    """s."""
    pts = arc(150, 355, 140, 95, 25, 270) + arc(150, 165, 150, 95, 90, -155)
    return [S(pts)]


def low_t():
    """t."""
    pts = [(100, ASC - 40), (100, 170)] + arc(200, 170, 100, 100, 180, 300)
    return [S(pts), S([(0, XT), (250, XT)])]


def low_u():
    """u."""
    pts = [(0, XT), (0, 260)] + arc(175, 260, 175, 190, 180, 360)
    return [S(pts), S([(350, XT), (350, BASE)])]


def low_v():
    """v."""
    return [S([(0, XT), (210, BASE), (420, XT)], radius=0)]


def low_w():
    """w."""
    return [S([(0, XT), (150, BASE), (300, XT), (450, BASE), (600, XT)],
              radius=0)]


def low_x():
    """x."""
    return [S([(0, XT), (380, BASE)]), S([(380, XT), (0, BASE)])]


def low_y():
    """y."""
    top_r, bot = (420, XT), (90, DESC)
    t = (XT - BASE) / (XT - DESC)
    join = (top_r[0] + (bot[0] - top_r[0]) * t, BASE)
    return [S([top_r, bot]), S([(0, XT), join])]


def low_z():
    """z."""
    return [S([(0, XT), (360, XT), (0, BASE), (360, BASE)], radius=0)]


# ---------------------------------------------------------------- digits
# Figures share one width (FIG_W on the design grid) and one bowl radius
# (FIG_R), so they sit on a common rhythm and fit tabular advances.
FIG_W = 330
FIG_R = FIG_W / 2
FIG_CX = FIG_W / 2
LOW_BOWL = BASE + FIG_R      # centre height of lower bowls (3, 5, 6)
TOP_BOWL = CAP - FIG_R       # centre height of upper bowls (0, 2)
FLAG_Y = CAP - 137           # height of the end of the flag of the 1
# the open bowl of the 2 starts at the height of the flag of the 1
TWO_START = 180 - math.degrees(math.asin((FLAG_Y - TOP_BOWL) / FIG_R))


def tangent_angle(centre, radius, point, side):
    """Angle (degrees) of the point where a line from point touches a circle.

    side=+1 picks the tangent counter-clockwise from the centre-to-point
    direction, side=-1 the clockwise one.
    """
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    base = math.degrees(math.atan2(dy, dx))
    return base + side * math.degrees(math.acos(radius / math.hypot(dx, dy)))


def d0():
    """0: a stadium, straight sides and round ends of the figure radius."""
    pts = ([(0, LOW_BOWL), (0, TOP_BOWL)]
           + arc(FIG_CX, TOP_BOWL, FIG_R, FIG_R, 180, 0)
           + [(FIG_W, LOW_BOWL)]
           + arc(FIG_CX, LOW_BOWL, FIG_R, FIG_R, 0, -180))
    return [S(pts, radius=0)]


def d1():
    """1: stem with a straight flag and a horizontal base."""
    flag = (FIG_CX - 155, FLAG_Y)
    base_half = 130
    return [S([flag, (FIG_CX, CAP), (FIG_CX, BASE)], radius=0),
            S([(FIG_CX - base_half, BASE), (FIG_CX + base_half, BASE)])]


def d2(start=TWO_START):
    """2: open upper bowl, straight diagonal tangent to it, flat base."""
    corner = (0, BASE)
    leave = tangent_angle((FIG_CX, TOP_BOWL), FIG_R, corner, 1)
    leave = (leave - start) % 360 - 360 + start  # clockwise, under a turn
    pts = arc(FIG_CX, TOP_BOWL, FIG_R, FIG_R, start, leave)
    return [S(pts + [corner, (FIG_W, BASE)], radius=0)]


def d3():
    """3: flat top, diagonal down to a short bar that enters the bowl."""
    top_of_bowl = LOW_BOWL + FIG_R
    pts = [(10, CAP), (FIG_W - 10, CAP), (95, top_of_bowl),
           (FIG_CX, top_of_bowl)]
    pts += arc(FIG_CX, LOW_BOWL, FIG_R, FIG_R, 90, -150)[1:]
    return [S(pts, radius=0)]


def d4():
    """4: stem, diagonal and crossbar."""
    stem = FIG_W - 75
    return [S([(stem, BASE), (stem, CAP), (0, 230), (FIG_W, 230)], radius=0)]


def d5():
    """5: flat top meeting the stem at a square corner, like the F bars."""
    top_of_bowl = LOW_BOWL + FIG_R
    frame = [(FIG_W - 10, CAP), (25, CAP), (25, top_of_bowl)]
    lower = [(25, top_of_bowl), (FIG_CX, top_of_bowl)]
    lower += arc(FIG_CX, LOW_BOWL, FIG_R, FIG_R, 90, -150)[1:]
    return [S(frame, radius=0), S(lower, radius=0)]


def d6():
    """6: lower bowl with a straight stroke tangent to it."""
    start = (FIG_W - 55, CAP)
    touch = tangent_angle((FIG_CX, LOW_BOWL), FIG_R, start, 1)
    pts = [start] + arc(FIG_CX, LOW_BOWL, FIG_R, FIG_R, touch, touch + 360,
                        180)
    return [S(pts, radius=0)]


def d7():
    """7: bar and straight diagonal."""
    return [S([(0, CAP), (FIG_W, CAP), (110, BASE)], radius=0)]


def d8():
    """8: two stacked circles, the lower one slightly larger."""
    upper_r, lower_r = 130, 150
    return [S(arc(FIG_CX, CAP - upper_r, upper_r, upper_r, 0, 360, 120)),
            S(arc(FIG_CX, BASE + lower_r, lower_r, lower_r, 0, 360, 120))]


def d9():
    """9: the 6 turned by 180 degrees, exactly."""
    return [flip(merge(d6()), grid_y(MID))]


# ----------------------------------------------------------- punctuation
def p_period():
    """Full stop."""
    return [dot(0, 75)]


def p_comma():
    """Comma."""
    return [S([(30, 120), (-20, -90)])]


def p_colon():
    """Colon."""
    return [dot(0, 75), dot(0, 400)]


def p_semicolon():
    """Semicolon."""
    return p_comma() + [dot(10, 400)]


def p_exclam():
    """Exclamation mark."""
    return [S([(0, CAP), (0, 280)]), dot(0, 75)]


def p_question():
    """Question mark."""
    pts = arc(180, 475, 160, 155, 160, -65) + [(180, 300), (180, 275)]
    return [S(pts, radius=60), dot(180, 75)]


def p_periodcentered():
    """Middle dot (Catalan l·l, separators)."""
    return [dot(0, 330)]


def p_hyphen():
    """Hyphen."""
    return [S([(0, 290), (190, 290)])]


def p_endash():
    """En dash."""
    return [S([(0, 290), (380, 290)])]


def p_emdash():
    """Em dash."""
    return [S([(0, 290), (760, 290)])]


def p_quotesingle():
    """Straight apostrophe."""
    return [S([(0, ASC), (0, 520)])]


def p_quotedbl():
    """Straight double quote."""
    return [S([(0, ASC), (0, 520)]), S([(170, ASC), (170, 520)])]


def p_quoteright():
    """Typographic apostrophe."""
    return [S([(30, ASC), (-10, 500)])]


def p_parenleft():
    """Left parenthesis."""
    return [S(arc(330, 300, 330, 450, 118, 242))]


def p_parenright():
    """Right parenthesis."""
    return [S(arc(0, 300, 330, 450, 62, -62))]


def p_slash():
    """Slash."""
    return [S([(0, -60), (330, 720)])]


def p_guillemotleft():
    """Left guillemet."""
    return [S([(130, 430), (0, 280), (130, 130)], radius=20),
            S([(310, 430), (180, 280), (310, 130)], radius=20)]


def p_guillemotright():
    """Right guillemet."""
    return [S([(0, 430), (130, 280), (0, 130)], radius=20),
            S([(180, 430), (310, 280), (180, 130)], radius=20)]


def p_plus():
    """Plus sign."""
    return [S([(0, 300), (380, 300)]), S([(190, 110), (190, 490)])]


def p_equal():
    """Equals sign."""
    return [S([(0, 380), (380, 380)]), S([(0, 200), (380, 200)])]


def p_percent():
    """Percent sign."""
    return [S(arc(110, 520, 95, 110, 0, 360, 60), half=50),
            S(arc(470, 180, 95, 110, 0, 360, 60), half=50),
            S([(70, BASE), (510, CAP)], half=55)]


def p_euro():
    """Euro sign."""
    return [S(arc(330, MID, 270, 280, 42, 318)),
            S([(0, 420), (290, 420)], half=55),
            S([(0, 270), (260, 270)], half=55)]


def p_dollar():
    """Dollar sign."""
    return cap_s() + [S([(210, CAP + 60), (210, BASE - 60)], half=50)]


def p_ordmasculine():
    """Masculine ordinal indicator."""
    return [S(arc(110, 545, 100, 105, 0, 360, 60), half=45),
            S([(10, 360), (210, 360)], half=45)]


def p_ordfeminine():
    """Feminine ordinal indicator."""
    return [S(arc(105, 545, 95, 105, 0, 360, 60), half=45),
            S([(200, 650), (200, 440)], half=45),
            S([(10, 360), (210, 360)], half=45)]


def p_underscore():
    """Underscore."""
    return [S([(0, -110), (460, -110)])]


def p_asterisk():
    """Asterisk."""
    cx, cy, r = 150, 560, 130
    strokes = []
    for k in range(3):
        ang = math.radians(90 + 60 * k)
        strokes.append(S([(cx + r * math.cos(ang), cy + r * math.sin(ang)),
                          (cx - r * math.cos(ang), cy - r * math.sin(ang))],
                         half=50))
    return strokes


def p_at():
    """At sign: a geometric single-storey a wrapped by an open ring."""
    cx, cy, ring, bowl_r = 330, 300, 310, 112
    stem_x = cx + bowl_r
    ring_start = -12
    start = (cx + ring * math.cos(math.radians(ring_start)),
             cy + ring * math.sin(math.radians(ring_start)))
    tangent = (-math.sin(math.radians(ring_start)),
               math.cos(math.radians(ring_start)))
    hook = bez((stem_x, 225), (stem_x, 140),
               (start[0] - tangent[0] * 100, start[1] - tangent[1] * 100),
               start)
    tail = [(stem_x, cy + bowl_r), (stem_x, 225)] + hook[1:]
    tail += arc(cx, cy, ring, ring, ring_start, 283)[1:]
    inner = arc(cx, cy, bowl_r, bowl_r, 0, 360, 120)
    return [S(inner, half=50), S(tail, half=50, radius=0, close=False)]


def p_ampersand():
    """Ampersand."""
    pts = ([(440, BASE), (110, 440)] + arc(200, 520, 120, 110, 220, -40)
           + [(60, 230)] + arc(200, 210, 150, 140, 175, 320) + [(430, 330)])
    return [S(pts, radius=40)]


def p_numbersign():
    """Number sign."""
    return [S([(120, BASE), (190, CAP)], half=55),
            S([(300, BASE), (370, CAP)], half=55),
            S([(30, 440), (450, 440)], half=55),
            S([(10, 260), (430, 260)], half=55)]


# --------------------------------------------------------------- accents
def acc_acute(x, y0, _spread=1.0):
    """Acute accent."""
    return [S([(x - 50, y0), (x + 60, y0 + 100)], half=ACC_HW)]


def acc_grave(x, y0, _spread=1.0):
    """Grave accent."""
    return [S([(x + 50, y0), (x - 60, y0 + 100)], half=ACC_HW)]


def acc_circumflex(x, y0, spread=1.0):
    """Circumflex accent."""
    half = 100 * spread
    return [S([(x - half, y0), (x, y0 + 90), (x + half, y0)], radius=20,
              half=ACC_HW)]


def acc_dieresis(x, y0, spread=1.0):
    """Dieresis."""
    half = 105 * spread
    return [dot(x - half, y0 + 45, 62), dot(x + half, y0 + 45, 62)]


def acc_tilde(x, y0, _spread=1.0):
    """Tilde."""
    pts = bez((x - 130, y0 + 20), (x - 60, y0 + 140), (x + 50, y0 - 60),
              (x + 130, y0 + 70))
    return [S(pts, half=ACC_HW)]


def acc_cedilla(x, _y0, _spread=1.0):
    """Cedilla, attached under the base glyph."""
    pts = [(x, 20), (x, -50)] + arc(x - 30, -110, 70, 60, 70, -160)
    return [S(pts, half=50)]


ACCENTS = {
    "acute": (acc_acute, 0x301),
    "grave": (acc_grave, 0x300),
    "circumflex": (acc_circumflex, 0x302),
    "dieresis": (acc_dieresis, 0x308),
    "tilde": (acc_tilde, 0x303),
    "cedilla": (acc_cedilla, 0x327),
}


# ---------------------------------------------------------- glyph table
def build_table():  # pylint: disable=too-many-locals
    """Return ({name: (codepoint, geometry)}, {composite: base name})."""
    table = {}
    bases = {"A.ss01": "A", "A.ss02": "A"}
    caps = {c: globals()["cap_" + c.lower()] for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    lows = {c: globals()["low_" + c] for c in "abcdefghijklmnopqrstuvwxyz"}
    for name, func in list(caps.items()) + list(lows.items()):
        table[name] = (ord(name), merge(func()))
    table["dotlessi"] = (0x131, merge(low_dotlessi()))
    table["A.ss01"] = (None, logo_a(merge(cap_a_bare())))
    table["A.ss02"] = (None, merge(cap_a_bare()))
    for i, name in enumerate(DIGITS):
        table[name] = (0x30 + i, merge(globals()[f"d{i}"]()))
    punct = {
        "period": 0x2E, "comma": 0x2C, "colon": 0x3A, "semicolon": 0x3B,
        "exclam": 0x21, "question": 0x3F, "hyphen": 0x2D, "periodcentered": 0xB7, "endash": 0x2013,
        "emdash": 0x2014, "quotesingle": 0x27, "quotedbl": 0x22,
        "quoteright": 0x2019, "parenleft": 0x28, "parenright": 0x29,
        "slash": 0x2F, "guillemotleft": 0xAB, "guillemotright": 0xBB,
        "plus": 0x2B, "equal": 0x3D, "percent": 0x25, "euro": 0x20AC,
        "dollar": 0x24, "ordmasculine": 0xBA, "ordfeminine": 0xAA,
        "underscore": 0x5F, "asterisk": 0x2A, "at": 0x40,
        "ampersand": 0x26, "numbersign": 0x23,
    }
    for name, code in punct.items():
        table[name] = (code, merge(globals()["p_" + name]()))
    table["quoteleft"] = (0x2018, flip(table["quoteright"][1], grid_y(610)))
    table["quotedblleft"] = (0x201C, merge(
        [table["quoteleft"][1], translate(table["quoteleft"][1], 170)]))
    table["quotedblright"] = (0x201D, merge(
        [table["quoteright"][1], translate(table["quoteright"][1], 170)]))
    table["questiondown"] = (0xBF, flip(table["question"][1], grid_y(245)))
    table["exclamdown"] = (0xA1, flip(table["exclam"][1], grid_y(245)))

    # accented letters
    combos = {
        "acute": "AEIOUYaeiouy", "grave": "AEIOUaeiou",
        "circumflex": "AEIOUaeiou", "dieresis": "AEIOUaeiouy",
        "tilde": "ANOano", "cedilla": "Cc",
    }
    names = {"acute": "acute", "grave": "grave", "circumflex": "circumflex",
             "dieresis": "dieresis", "tilde": "tilde", "cedilla": "cedilla"}
    import unicodedata  # pylint: disable=import-outside-toplevel
    for acc, letters in combos.items():
        func, comb = ACCENTS[acc]
        for letter in letters:
            base_name = "dotlessi" if letter == "i" else letter
            base = table[base_name][1]
            minx, _, maxx, _ = base.bounds
            x_mid = (minx + maxx) / 2 / SCALE
            if acc == "cedilla":
                y0 = 0
            else:
                y0 = CAP_ACC if letter.isupper() else LOW_ACC
            composed = unicodedata.normalize("NFC", letter + chr(comb))
            spread = NARROW_SPREAD if letter in "Ii" else 1.0
            geom = merge([base] + func(x_mid, y0, spread))
            table[letter + names[acc]] = (ord(composed), geom)
            bases[letter + names[acc]] = base_name
    return table, bases


def build(out_dir):  # pylint: disable=too-many-locals
    """Assemble and save the OTF and TTF fonts under out_dir."""
    table, bases = build_table()
    order = [".notdef", "space", "nbspace"] + list(table)
    cmap = {0x20: "space", 0xA0: "nbspace"}
    contours = {".notdef": notdef_contours(), "space": [], "nbspace": []}
    metrics = {".notdef": 500, "space": 270, "nbspace": 270}

    symmetry = {}
    for name, (code, geom) in list(table.items()):
        found = detect(geom)
        if found:
            symmetry[name] = found
            table[name] = (code, symmetrize_geom(geom, *found))

    spaced = {}
    for name, (code, geom) in table.items():
        if name not in bases and name not in DIGITS:
            spaced[name] = Spaced(geom, *spacing_rule(name))
    unmatched = {}
    for name, (code, geom) in table.items():
        if name in DIGITS:
            minx, _, maxx, _ = geom.bounds
            shift = (TAB_WIDTH - (maxx - minx)) / 2 - minx
            advance = TAB_WIDTH
        else:
            ref = spaced[bases.get(name, name)]
            shift, advance = ref.shift, ref.advance
            if name in bases and not name.startswith("A.ss"):
                shift, advance = fit_accents(geom, shift, advance)
        if name in symmetry:
            kind, (cx, cy) = symmetry[name]
            shift += round(cx + shift) - (cx + shift)
            contours[name], missing = symmetrize_contours(
                outline(geom, shift), kind, (cx + shift, cy))
            if missing:
                unmatched[name] = missing
        else:
            contours[name] = outline(geom, shift)
        metrics[name] = advance
        if code is not None:
            cmap[code] = name
    print(f"{len(symmetry)} symmetric glyphs; unmatched points: {unmatched}")

    feature_text = """
languagesystem DFLT dflt;
languagesystem latn dflt;
""" + kern_feature(spaced, bases) + """
feature ss01 { sub A by A.ss01; } ss01;
feature ss02 { sub A by A.ss02; } ss02;
feature salt { sub A by A.ss01; } salt;
"""
    otf_path = out_dir / "otf" / f"{FILE_STEM}.otf"
    ttf_path = out_dir / "ttf" / f"{FILE_STEM}.ttf"
    otf_path.parent.mkdir(parents=True, exist_ok=True)
    ttf_path.parent.mkdir(parents=True, exist_ok=True)
    save_ttf(str(ttf_path), order, cmap, metrics, contours, feature_text,
             {n: kind for n, (kind, _) in symmetry.items()})
    save_otf(str(otf_path), order, cmap, metrics, contours, feature_text)
    nodes = sum(len(c) for cs in contours.values() for c in cs)
    print(f"saved {otf_path} and {ttf_path}: {len(order)} glyphs, "
          f"{nodes} on-curve nodes")


def main():
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT,
                        help="directory that receives otf/ and ttf/ "
                             "(default: the repository fonts/ folder)")
    build(parser.parse_args().output_dir)


if __name__ == "__main__":
    main()
