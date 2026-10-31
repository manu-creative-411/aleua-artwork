"""The A of the ALEUA logotype, used by the ss01 stylistic set.

The swoosh and the gap it leaves in the right leg are measured from the
imagotype SVG by tools/aleua_logo.py and stored in logo_swoosh.json,
relative to the bounding box of the open A (A.ss02).
"""

import json
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

SWOOSH_DATA = Path(__file__).resolve().parent / "logo_swoosh.json"
MITRE = 100.0   # keep sharp corners sharp when offsetting
REACH = 3.0     # font units the gap extends past the A outline
BRIDGE = 1.0    # half width of hairlines removed after cutting


def load_rings(items, origin):
    """Shapely polygons from JSON rings stored relative to origin."""
    ox, oy = origin
    polys = []
    for item in items:
        shell = [(x + ox, y + oy) for x, y in item["exterior"]]
        holes = [[(x + ox, y + oy) for x, y in ring]
                 for ring in item["interiors"]]
        polys.append(Polygon(shell, holes).buffer(0))
    return unary_union(polys)


def logo_a(open_a):
    """A of the logotype: open A, gap where the swoosh crosses, swoosh.

    The swoosh and the gap are measured from the imagotype SVG by
    tools/aleua_logo.py and stored relative to the open A bounding box.
    """
    data = json.loads(SWOOSH_DATA.read_text(encoding="utf-8"))
    origin = open_a.bounds[:2]
    cut = load_rings(data["cut"], origin)
    swoosh = load_rings(data["swoosh"], origin)
    # extend the gap past the outline only, so no hairline bridge remains
    reach = cut.buffer(REACH, join_style="mitre",
                       mitre_limit=MITRE).difference(open_a)
    legs = open_a.difference(unary_union([cut, reach]))
    legs = legs.buffer(-BRIDGE, join_style="mitre", mitre_limit=MITRE).buffer(
        BRIDGE, join_style="mitre", mitre_limit=MITRE)
    return unary_union([legs, swoosh])
