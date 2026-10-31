"""Optical spacing and kerning for Aleua Sans.

Side bearings are derived from the white next to each side of a glyph,
measured row by row inside its height zone, so straight, round and open
sides get consistent optical spacing. Kerning compares the white that a
pair really shows with the white its side bearings already compensated.
"""

from shapely.geometry import LineString

STEP = 10           # row spacing of the profiles, in font units
DEPTH = 120         # deepest white of one side that counts for spacing
FACTOR = 0.55       # share of the measured white taken off the target
CLOSEST = 0.75      # weight of the closest approach between a pair
NEAR_SHARE = 0.1    # share of rows that defines the closest approach
LOWER_TARGET = 50   # side white of lowercase; also used for mixed pairs
MIN_SB = -20        # lowest side bearing allowed
MIN_GAP = 40        # minimum clearance between kerned glyphs
MAX_KERN = 120      # largest negative kerning value
KERN_THRESHOLD = 10
ACCENT_MARGIN = 8   # minimum room between an accent and the advance edge


def profile(geom, low, high):
    """Return {y: (left depth, right depth)} measured from the bbox."""
    minx, _, maxx, _ = geom.bounds
    rows = {}
    for y in range(int(low), int(high) + 1, STEP):
        cut = geom.intersection(LineString([(minx - 10, y), (maxx + 10, y)]))
        if cut.is_empty:
            continue
        left, _, right, _ = cut.bounds
        rows[y] = (left - minx, maxx - right)
    return rows


def clamped_mean(values, limit):
    """Mean of values clamped to limit."""
    if not values:
        return 0.0
    return sum(min(v, limit) for v in values) / len(values)


def near(values):
    """Closest approach: a low percentile, so lone terminals do not rule."""
    ordered = sorted(values)
    return ordered[int(NEAR_SHARE * (len(ordered) - 1))]


def side_white(depths):
    """Perceived white of one side next to a straight stem."""
    closest = near(depths)
    beyond = clamped_mean([max(0.0, d - closest) for d in depths], DEPTH)
    return CLOSEST * closest + FACTOR * beyond


class Spaced:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """A glyph geometry with optical side bearings."""

    def __init__(self, geom, zone, target, case="other"):
        self.geom = geom
        self.target = target
        self.case = case
        minx, _, maxx, _ = geom.bounds
        self.minx = minx
        self.width = maxx - minx
        self.rows = profile(geom, -250, 1000)
        own = {y: v for y, v in self.rows.items() if zone[0] <= y <= zone[1]}
        if not own:
            own = self.rows
        self.lsb = max(MIN_SB, round(target - side_white(
            [v[0] for v in own.values()])))
        self.rsb = max(MIN_SB, round(target - side_white(
            [v[1] for v in own.values()])))

    @property
    def advance(self):
        """Advance width."""
        return int(round(self.width + self.lsb + self.rsb))

    @property
    def shift(self):
        """Horizontal offset that places the outline at its lsb."""
        return self.lsb - self.minx


def ideal_white(left, right):
    """White a pair of straight stems would show between these glyphs."""
    if {left.case, right.case} == {"upper", "lower"}:
        return 2 * LOWER_TARGET
    return left.target + right.target


def pair_kern(left, right):
    """Kerning value for a pair of spaced glyphs (0 if not needed).

    Uses the same white model as the side bearings, so a glyph next to
    a straight stem of its own case never needs kerning.
    """
    shared = set(left.rows) & set(right.rows)
    if not shared:
        return 0
    sums = [left.rows[y][1] + right.rows[y][0] for y in shared]
    perceived = left.rsb + right.lsb + side_white(sums)
    kern = ideal_white(left, right) - perceived
    gap = min(sums) + left.rsb + right.lsb
    if kern > 0:
        kern = max(0, MIN_GAP - gap)
    kern = max(kern, -MAX_KERN, MIN_GAP - gap)
    kern = int(round(kern / 5.0) * 5)
    return kern if abs(kern) >= KERN_THRESHOLD else 0


# ------------------------------------------------------- font helpers
KERN_GLYPHS = (list("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
               + ["dotlessi", "period", "comma", "hyphen", "quoteright",
                  "quoteleft", "quotesingle", "quotedbl", "quotedblleft",
                  "quotedblright", "parenleft", "parenright", "slash",
                  "guillemotleft", "guillemotright", "colon", "semicolon",
                  "question", "exclam", "questiondown", "exclamdown"])


def spacing_rule(name):
    """Return (height zone, target side white, case) for a glyph."""
    if name[0].isupper():
        return (0, 700), 62, "upper"
    if name[0].islower() and (len(name) == 1 or name == "dotlessi"):
        return (0, 510), 50, "lower"
    return (-250, 1000), 45, "other"


def fit_accents(geom, shift, advance):
    """Widen a composite so its accent never pokes into a neighbour."""
    minx, _, maxx, _ = geom.bounds
    extra_left = max(0.0, ACCENT_MARGIN - (minx + shift))
    extra_right = max(0.0, (maxx + shift) - (advance - ACCENT_MARGIN))
    return (shift + extra_left,
            int(round(advance + extra_left + extra_right)))


def kern_feature(spaced, bases):
    """Build the kern feature, kerning composites like their bases."""
    members = {}
    for name in KERN_GLYPHS:
        members[name] = [name] + sorted(c for c, b in bases.items()
                                        if b == name)
    lines = ["feature kern {"]
    for name, glyph_list in members.items():
        lines.append(f"  @K_{name.replace('.', '_')} = [{' '.join(glyph_list)}];")
    for left in KERN_GLYPHS:
        for right in KERN_GLYPHS:
            value = pair_kern(spaced[left], spaced[right])
            if value:
                lines.append(f"  pos @K_{left} @K_{right} {value};")
    lines.append("} kern;")
    return "\n".join(lines)
