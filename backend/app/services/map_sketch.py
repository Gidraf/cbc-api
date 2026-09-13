"""A sketch map drawn from data, not from a model's idea of what Kenya looks like.

Social Studies and Geography designs ask learners to "locate physical
features on a map of Kenya", "draw a sketch map of the school compound",
and read distance and direction off a map with a scale, a north arrow and
a key. The diagram station asked a language model for the SVG, and a
language model draws Kenya the way a person draws it from memory in the
dark: the coast on the wrong side, Lake Victoria in the middle, Nairobi
north of Mount Kenya. A map like that cannot be asked a question about,
because every answer on it is wrong.

So the map is drawn HERE, deterministically, from two things:

- a **gazetteer** of Kenya — the outline, the lakes, the rivers as paths,
  the mountains and the towns, each at its real position — and
- the **feature list** the lesson names. The model chooses WHAT goes on the
  map (the six towns the lesson is about, the one river it follows); the
  gazetteer decides WHERE. A named feature the gazetteer knows is placed
  where it is; one it does not know is placed where the model says, and
  said so in the scene.

Every map carries a title, a north arrow, a scale bar worked out from the
projection, a key naming only the symbols used, and a graticule — the four
things the KICD rubric marks. Feature labels are `<text>` elements, so the
scene builder makes each one an addressable part: "name the town marked A"
and "name the river marked B" come free, and the marking scheme reads the
answer off the map rather than the model.

An extent the gazetteer has no outline for — a county, a school compound —
is drawn schematically from positions the model gives on a 0–100 grid
inside a boundary it may also give. That is what a sketch map of a school
compound is: a plan, not a survey.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-map-sketch")

# ── the gazetteer ─────────────────────────────────────────────────────────────
#
# (lon, lat) pairs. A sketch, not a survey: the outline is some forty
# vertices, and a river is the handful of bends a Grade 6 atlas shows.

KENYA_OUTLINE: list[tuple[float, float]] = [
    (33.92, -1.00), (33.95, 0.10), (34.10, 0.45), (34.35, 0.75), (34.55, 1.13),
    (34.90, 1.60), (34.75, 2.20), (34.40, 2.90), (34.20, 3.60), (33.98, 4.22),
    (34.40, 4.60), (35.00, 5.00), (35.90, 4.62), (36.10, 4.45), (36.90, 4.42),
    (38.10, 3.60), (39.05, 3.52), (39.60, 3.50), (40.75, 4.25), (41.00, 3.97),
    (41.90, 3.98), (40.98, 2.80), (41.00, -0.85), (41.55, -1.70), (41.00, -2.20),
    (40.55, -2.50), (40.13, -3.20), (39.90, -3.60), (39.72, -4.05), (39.20, -4.68),
    (38.20, -4.00), (37.75, -3.60), (37.55, -3.30), (37.60, -3.05), (36.79, -2.55),
    (36.00, -2.16), (35.00, -1.60), (34.60, -1.35),
]

# Neighbours, for the labels a Kenya map carries round its edge.
NEIGHBOURS: list[tuple[str, float, float]] = [
    ("UGANDA", 33.4, 1.6), ("SOUTH SUDAN", 34.7, 5.3), ("ETHIOPIA", 38.5, 4.6),
    ("SOMALIA", 42.1, 1.5), ("TANZANIA", 35.5, -3.4), ("INDIAN OCEAN", 41.3, -3.9),
]

LAKES: dict[str, list[tuple[float, float]]] = {
    "lake victoria": [(33.92, -1.00), (33.95, 0.10), (34.20, 0.05), (34.55, -0.05),
                      (34.75, -0.15), (34.45, -0.45), (34.20, -0.85), (34.05, -1.00)],
    "lake turkana": [(36.05, 4.45), (35.95, 4.00), (36.00, 3.30), (36.20, 2.60),
                     (36.45, 2.40), (36.60, 2.80), (36.45, 3.60), (36.35, 4.20)],
}
SMALL_LAKES: dict[str, tuple[float, float]] = {
    "lake naivasha": (36.35, -0.77), "lake nakuru": (36.08, -0.37),
    "lake baringo": (36.08, 0.62), "lake bogoria": (36.10, 0.25),
    "lake magadi": (36.27, -1.90), "lake elementaita": (36.25, -0.45),
    "lake jipe": (37.75, -3.60), "lake chala": (37.70, -3.32),
    "lake kanyaboli": (34.15, 0.05), "lake ol bolossat": (36.43, -0.15),
}

RIVERS: dict[str, list[tuple[float, float]]] = {
    "river tana": [(36.75, -0.55), (37.30, -0.95), (38.20, -0.70), (38.90, -0.30),
                   (39.65, -0.45), (40.00, -1.30), (40.20, -2.00), (40.52, -2.52)],
    "river athi": [(36.75, -1.50), (37.30, -1.60), (38.00, -2.60), (38.90, -3.10),
                   (39.60, -3.20), (40.13, -3.15)],
    "river ewaso ng'iro": [(36.90, 0.00), (37.30, 0.30), (37.90, 0.60), (38.70, 0.90),
                           (39.50, 1.00)],
    "river nzoia": [(34.70, 1.10), (34.90, 0.80), (34.50, 0.40), (34.05, 0.05)],
    "river yala": [(35.20, 0.15), (34.70, 0.05), (34.20, -0.05)],
    "river mara": [(35.60, -0.90), (35.20, -1.30), (34.90, -1.50)],
    "river turkwel": [(35.00, 1.50), (35.40, 2.30), (35.90, 3.10)],
    "river kerio": [(35.50, 0.60), (35.60, 1.50), (35.90, 2.50)],
    "river sondu": [(35.30, -0.40), (34.90, -0.35), (34.75, -0.35)],
    "river galana": [(38.90, -3.10), (39.60, -3.20), (40.13, -3.15)],
}
RIVER_ALIASES = {
    "tana": "river tana", "athi": "river athi", "galana": "river galana",
    "sabaki": "river galana", "athi-galana": "river athi", "ewaso ngiro": "river ewaso ng'iro",
    "ewaso nyiro": "river ewaso ng'iro", "uaso nyiro": "river ewaso ng'iro",
    "nzoia": "river nzoia", "yala": "river yala", "mara": "river mara",
    "turkwel": "river turkwel", "kerio": "river kerio", "sondu": "river sondu",
    "sondu miriu": "river sondu",
}

MOUNTAINS: dict[str, tuple[float, float]] = {
    "mount kenya": (37.31, -0.15), "mount elgon": (34.55, 1.13),
    "aberdare range": (36.65, -0.45), "mau escarpment": (35.70, -0.50),
    "cherangani hills": (35.40, 1.15), "taita hills": (38.35, -3.40),
    "mount marsabit": (37.97, 2.30), "ngong hills": (36.65, -1.40),
    "mount longonot": (36.45, -0.91), "mount kulal": (36.93, 2.70),
    "chyulu hills": (37.85, -2.60), "nyambene hills": (37.90, 0.20),
    "ol donyo sabuk": (37.25, -1.15), "mount suswa": (36.35, -1.18),
    "kisii highlands": (34.80, -0.70), "nandi hills": (35.10, 0.10),
    "mount kilimanjaro": (37.35, -3.07), "mount nyiru": (36.85, 2.15),
    "matthews range": (37.30, 1.20), "huri hills": (37.90, 3.55),
    "mount kasigau": (38.65, -3.82), "shimba hills": (39.40, -4.25),
}
MOUNTAIN_ALIASES = {
    "mt kenya": "mount kenya", "mt. kenya": "mount kenya", "mt elgon": "mount elgon",
    "mt. elgon": "mount elgon", "aberdares": "aberdare range", "aberdare": "aberdare range",
    "aberdare ranges": "aberdare range", "nyandarua range": "aberdare range",
    "mau": "mau escarpment", "mau ranges": "mau escarpment", "mau range": "mau escarpment",
    "cherangani": "cherangani hills", "cherangany hills": "cherangani hills",
    "taita": "taita hills", "mt marsabit": "mount marsabit", "mt longonot": "mount longonot",
    "longonot": "mount longonot", "mt kulal": "mount kulal", "chyulu": "chyulu hills",
    "nyambene": "nyambene hills", "mt suswa": "mount suswa", "suswa": "mount suswa",
    "mt kilimanjaro": "mount kilimanjaro", "kilimanjaro": "mount kilimanjaro",
    "mt nyiru": "mount nyiru", "mathews range": "matthews range",
    "mt kasigau": "mount kasigau",
}

TOWNS: dict[str, tuple[float, float]] = {
    "nairobi": (36.82, -1.29), "mombasa": (39.67, -4.05), "kisumu": (34.77, -0.09),
    "nakuru": (36.07, -0.30), "eldoret": (35.27, 0.52), "thika": (37.08, -1.04),
    "malindi": (40.12, -3.22), "kitale": (35.00, 1.02), "garissa": (39.64, -0.45),
    "kakamega": (34.75, 0.28), "nyeri": (36.95, -0.42), "meru": (37.65, 0.05),
    "machakos": (37.26, -1.52), "embu": (37.45, -0.54), "kericho": (35.28, -0.37),
    "kisii": (34.77, -0.68), "bungoma": (34.56, 0.57), "busia": (34.11, 0.46),
    "isiolo": (37.58, 0.35), "marsabit": (37.99, 2.33), "lodwar": (35.60, 3.12),
    "wajir": (40.06, 1.75), "mandera": (41.86, 3.94), "moyale": (39.05, 3.52),
    "lamu": (40.90, -2.27), "voi": (38.56, -3.39), "naivasha": (36.43, -0.72),
    "narok": (35.87, -1.08), "kajiado": (36.78, -1.85), "nanyuki": (37.07, 0.02),
    "kilifi": (39.85, -3.63), "kwale": (39.45, -4.17), "homa bay": (34.46, -0.53),
    "migori": (34.47, -1.06), "kapenguria": (35.11, 1.24), "maralal": (36.70, 1.10),
    "kitui": (38.01, -1.37), "murang'a": (37.15, -0.72), "kerugoya": (37.28, -0.50),
    "nyahururu": (36.36, 0.04), "iten": (35.50, 0.67), "kabarnet": (35.74, 0.49),
    "hola": (40.03, -1.50), "lokichogio": (34.35, 4.20), "namanga": (36.79, -2.55),
    "taveta": (37.68, -3.40), "wundanyi": (38.36, -3.40), "siaya": (34.29, 0.06),
    "ol kalou": (36.38, -0.27), "kiambu": (36.83, -1.17), "ruiru": (36.96, -1.15),
    "limuru": (36.64, -1.11), "athi river": (36.98, -1.45), "makueni": (37.62, -1.80),
    "wote": (37.63, -1.78), "mwingi": (38.06, -0.93), "chuka": (37.65, -0.33),
    "nyamira": (34.93, -0.57), "bomet": (35.34, -0.78), "sotik": (35.12, -0.68),
    "kapsabet": (35.10, 0.20), "vihiga": (34.72, 0.05), "mumias": (34.49, 0.34),
    "webuye": (34.77, 0.62), "malaba": (34.27, 0.64), "kericho": (35.28, -0.37),
    "eldama ravine": (35.72, 0.05), "rumuruti": (36.54, 0.27), "archer's post": (37.67, 0.64),
    "el wak": (40.93, 2.80), "garsen": (40.11, -2.27), "kipini": (40.53, -2.52),
    "watamu": (40.02, -3.36), "diani": (39.58, -4.28), "vanga": (39.22, -4.66),
    "mtito andei": (38.17, -2.69), "kibwezi": (37.97, -2.41), "sultan hamud": (37.38, -2.02),
    "emali": (37.48, -2.10), "magadi": (36.29, -1.90), "loitokitok": (37.50, -2.93),
    "kalokol": (35.85, 3.55), "kakuma": (34.87, 3.72), "lokitaung": (35.75, 4.27),
    "north horr": (37.07, 3.32), "loiyangalani": (36.72, 2.75), "wamba": (37.32, 0.98),
    "baragoi": (36.78, 1.78), "samburu": (37.53, 0.60), "laisamis": (37.80, 1.60),
    "habaswein": (39.49, 1.01), "buna": (39.93, 2.79), "takaba": (40.22, 3.40),
    "rhamu": (41.22, 3.93), "liboi": (40.88, 0.35), "dadaab": (40.31, 0.05),
    "bura": (39.93, -1.10), "kinango": (39.32, -4.13), "lunga lunga": (39.12, -4.55),
    "mariakani": (39.47, -3.86), "kaloleni": (39.63, -3.82), "jomvu": (39.62, -4.00),
}
CAPITAL = "nairobi"

# What each symbol in the key means, and how it is drawn.
KEY_TEXT = {
    "capital": "Capital city", "town": "Town", "mountain": "Mountain / hills",
    "river": "River", "lake": "Lake", "road": "Road", "railway": "Railway",
    "boundary": "International boundary", "county_boundary": "County boundary",
    "relief": "Highland", "vegetation": "Forest", "settlement": "Settlement",
    "building": "Building", "feature": "Feature", "port": "Port", "airport": "Airport",
}

_SLUG = re.compile(r"[^a-z0-9]+")


def _norm(name: str) -> str:
    text = re.sub(r"\s+", " ", str(name or "").strip().lower().replace("’", "'"))
    return re.sub(r"^(the|river|lake|mount|mt\.?)\s+(the\s+)?", lambda m: m.group(1).rstrip(".") + " " if m.group(1) != "the" else "", text)


def _candidates(name: str, prefixes: tuple[str, ...], aliases: dict[str, str]) -> list[str]:
    """The spellings a name might be filed under: as given, with and without
    the kind word, with and without apostrophes, and through the aliases."""
    key = _norm(name)
    bare = key
    for prefix in prefixes:
        if bare.startswith(prefix + " "):
            bare = bare[len(prefix) + 1:]
    seen: list[str] = []
    for candidate in (key, bare, *(f"{p} {bare}" for p in prefixes)):
        for variant in (candidate, candidate.replace("'", "")):
            for resolved in (variant, aliases.get(variant, "")):
                if resolved and resolved not in seen:
                    seen.append(resolved)
    return seen


def _lookup(kind: str, name: str) -> tuple[str, Any] | None:
    """The gazetteer entry for a named feature, under whichever spelling."""
    if kind == "river":
        for key in _candidates(name, ("river", "r."), RIVER_ALIASES):
            if key in RIVERS:
                return key, RIVERS[key]
        return None
    if kind == "lake":
        for key in _candidates(name, ("lake", "l."), {}):
            if key in LAKES:
                return key, LAKES[key]
            if key in SMALL_LAKES:
                return key, SMALL_LAKES[key]
        return None
    if kind in ("mountain", "relief", "hills", "highland"):
        for key in _candidates(name, ("mount", "mt", "mt."), MOUNTAIN_ALIASES):
            if key in MOUNTAINS:
                return key, MOUNTAINS[key]
        return None
    if kind in ("town", "capital", "settlement", "city", "port", "airport"):
        for key in _candidates(name, (), {}):
            if key in TOWNS:
                return key, TOWNS[key]
        return None
    # Unknown kind: try everything.
    for other in ("town", "mountain", "lake", "river"):
        found = _lookup(other, name)
        if found:
            return found
    return None


# ── the spec ──────────────────────────────────────────────────────────────────

@dataclass
class Feature:
    kind: str
    name: str
    lon: float | None = None
    lat: float | None = None
    x: float | None = None          # 0–100, for a schematic extent
    y: float | None = None
    path: list[tuple[float, float]] = field(default_factory=list)   # (lon, lat) or (x, y)
    note: str = ""
    placed_by: str = ""             # "gazetteer" | "model" | "unplaced"


@dataclass
class MapSpec:
    extent: str = "Kenya"
    title: str = ""
    features: list[Feature] = field(default_factory=list)
    boundary: list[tuple[float, float]] = field(default_factory=list)   # schematic only
    grid: bool = True
    show_neighbours: bool = True

    @property
    def schematic(self) -> bool:
        return not _is_kenya(self.extent)


def _is_kenya(extent: str) -> bool:
    return _norm(extent) in ("kenya", "republic of kenya", "map of kenya", "the map of kenya", "")


def _pairs(value: Any, *, latlon: bool) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for point in value or []:
        try:
            if isinstance(point, dict):
                if latlon:
                    out.append((float(point.get("lon", point.get("lng"))), float(point.get("lat"))))
                else:
                    out.append((float(point.get("x")), float(point.get("y"))))
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                a, b = float(point[0]), float(point[1])
                # The model writes (lat, lon) as often as (lon, lat). Kenya's
                # longitudes are 33–42 and its latitudes −5–5, so the larger
                # number is the longitude.
                out.append((max(a, b), min(a, b)) if latlon else (a, b))
        except (TypeError, ValueError):
            continue
    return out


def from_model(content: Any) -> MapSpec | None:
    """The map the model asked for, if it asked for one.

    Reads `map` off the response (or off `diagram_json`), as the geography
    prompt fragment specifies it. Returns None where there is no map.
    """
    if not isinstance(content, dict):
        return None
    raw = content.get("map")
    if not isinstance(raw, dict):
        inner = content.get("diagram_json")
        raw = inner.get("map") if isinstance(inner, dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("features"), list):
        return None

    spec = MapSpec(extent=str(raw.get("extent") or "Kenya").strip(),
                   title=str(raw.get("title") or content.get("diagram_title") or "").strip())
    latlon = not spec.schematic
    grid = raw.get("grid")
    if isinstance(grid, dict):
        spec.grid = str(grid.get("kind") or "").lower() not in ("none", "")
    elif isinstance(grid, bool):
        spec.grid = grid
    spec.show_neighbours = bool(raw.get("neighbours", True))
    spec.boundary = _pairs(raw.get("boundary"), latlon=False)

    for item in raw["features"]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        kind = _norm(item.get("kind") or "feature").replace(" ", "_")
        if not name:
            continue
        feature = Feature(kind=kind, name=name, note=str(item.get("note") or "").strip())
        try:
            if item.get("lat") is not None and (item.get("lon") is not None or item.get("lng") is not None):
                feature.lat = float(item["lat"])
                feature.lon = float(item.get("lon", item.get("lng")))
            if item.get("x") is not None and item.get("y") is not None:
                feature.x, feature.y = float(item["x"]), float(item["y"])
        except (TypeError, ValueError):
            pass
        feature.path = _pairs(item.get("path") or item.get("points"), latlon=latlon)
        spec.features.append(feature)
    return spec if spec.features else None


# ── projection ────────────────────────────────────────────────────────────────

WIDTH, HEIGHT = 820, 900
MARGIN = {"top": 70, "right": 40, "bottom": 150, "left": 60}


@dataclass
class Frame:
    x0: float
    y0: float
    x1: float
    y1: float
    scale: float          # px per degree (or per grid unit)
    lon0: float
    lat1: float
    latlon: bool

    def to_px(self, a: float, b: float) -> tuple[float, float]:
        """(lon, lat) or (x, y) → page pixels."""
        if self.latlon:
            return (self.x0 + (a - self.lon0) * self.scale,
                    self.y0 + (self.lat1 - b) * self.scale)
        return (self.x0 + a * self.scale, self.y0 + b * self.scale)


def _frame(spec: MapSpec) -> Frame:
    inner_w = WIDTH - MARGIN["left"] - MARGIN["right"]
    inner_h = HEIGHT - MARGIN["top"] - MARGIN["bottom"]
    if spec.schematic:
        scale = min(inner_w, inner_h) / 100.0
        return Frame(MARGIN["left"] + (inner_w - 100 * scale) / 2, MARGIN["top"],
                     0, 0, scale, 0, 0, False)
    lons = [p[0] for p in KENYA_OUTLINE]
    lats = [p[1] for p in KENYA_OUTLINE]
    pad = 0.7
    lon0, lon1 = min(lons) - pad, max(lons) + pad
    lat0, lat1 = min(lats) - pad, max(lats) + pad
    scale = min(inner_w / (lon1 - lon0), inner_h / (lat1 - lat0))
    x0 = MARGIN["left"] + (inner_w - (lon1 - lon0) * scale) / 2
    y0 = MARGIN["top"] + (inner_h - (lat1 - lat0) * scale) / 2
    return Frame(x0, y0, x0 + (lon1 - lon0) * scale, y0 + (lat1 - lat0) * scale,
                 scale, lon0, lat1, True)


# ── drawing ───────────────────────────────────────────────────────────────────

def _esc(text: Any) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _poly(points: list[tuple[float, float]], frame: Frame) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in (frame.to_px(a, b) for a, b in points))


def _title_case(name: str) -> str:
    small = {"of", "the", "and"}
    words = name.split()
    return " ".join(w if (w.lower() in small and i) else w[:1].upper() + w[1:]
                    for i, w in enumerate(words))


def _label_for(feature: Feature, key: str | None) -> str:
    """How the feature is written on the map: the gazetteer's own name where
    it knows the feature, so "The Aberdares" and "Aberdare Ranges" both print
    as Aberdare Range and the marking scheme has one spelling to accept."""
    if not key:
        return feature.name.strip()
    if key.startswith("mount "):
        return "Mt " + _title_case(key[6:])
    if key.startswith("river "):
        return "R. " + _title_case(key[6:])
    if key.startswith("lake "):
        return "L. " + _title_case(key[5:])
    return _title_case(key)


def _place(spec: MapSpec, feature: Feature) -> tuple[str | None, Any]:
    """Where the feature goes: the gazetteer's word first, then the model's."""
    if not spec.schematic:
        found = _lookup(feature.kind, feature.name)
        if found:
            feature.placed_by = "gazetteer"
            return found
        if feature.path or (feature.lon is not None and feature.lat is not None):
            feature.placed_by = "model"
            return None, feature.path or (feature.lon, feature.lat)
        feature.placed_by = "unplaced"
        return None, None
    if feature.path or (feature.x is not None and feature.y is not None):
        feature.placed_by = "model"
        return None, feature.path or (feature.x, feature.y)
    feature.placed_by = "unplaced"
    return None, None


def _default_boundary() -> list[tuple[float, float]]:
    """An irregular outline for a schematic extent with none given."""
    return [(8, 12), (30, 4), (55, 6), (78, 2), (95, 18), (97, 45), (90, 72),
            (96, 90), (70, 97), (45, 92), (20, 98), (4, 80), (2, 50), (6, 28)]


def render(spec: MapSpec) -> dict[str, Any]:
    """The map as SVG, with the scene the question stations need.

    Returns `svg`, `scene` (parts with what each feature is, so a marking
    scheme can say more than the bare label), `key` (the symbols used) and
    `unplaced` (features named that nowhere could be found for).
    """
    frame = _frame(spec)
    base: list[str] = []
    water: list[str] = []
    lines: list[str] = []
    symbols: list[str] = []
    labels: list[str] = []
    parts: list[dict[str, Any]] = []
    used_symbols: list[str] = []
    unplaced: list[str] = []
    furniture_texts: list[str] = []

    def symbol(kind: str) -> None:
        if kind not in used_symbols:
            used_symbols.append(kind)

    def label(text: str, x: float, y: float, *, feature: Feature | None = None,
              size: float = 12, anchor: str = "start", weight: str = "normal",
              style: str = "", fill: str = "#111", function: str = "") -> None:
        labels.append(
            f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' text-anchor='{anchor}' "
            f"font-weight='{weight}' font-style='{style or 'normal'}' fill='{fill}' "
            f"font-family='Helvetica, Arial, sans-serif' paint-order='stroke' stroke='#fff' "
            f"stroke-width='3'>{_esc(text)}</text>")
        if feature is not None:
            parts.append({"label": text, "role": "label", "assessable": True, "occludable": True,
                          "function": function, "alt_text": text})
        else:
            furniture_texts.append(text)

    # ── the ground ──
    if spec.schematic:
        outline = spec.boundary or _default_boundary()
        base.append(f"<polygon points='{_poly(outline, frame)}' fill='#f7f4ea' stroke='#333' "
                    f"stroke-width='2' data-layer='base'/>")
    else:
        base.append(f"<polygon points='{_poly(KENYA_OUTLINE, frame)}' fill='#f7f4ea' stroke='#222' "
                    f"stroke-width='2.2' data-layer='base'/>")
        symbol("boundary")
        if spec.show_neighbours:
            for name, lon, lat in NEIGHBOURS:
                x, y = frame.to_px(lon, lat)
                label(name, x, y, size=10, anchor="middle", fill="#777",
                      style="italic" if "OCEAN" in name else "")

    # ── the graticule ──
    if spec.grid and not spec.schematic:
        lon = math.ceil(frame.lon0)
        lon += lon % 2
        while frame.x0 + (lon - frame.lon0) * frame.scale <= frame.x1:
            x, _ = frame.to_px(lon, 0)
            lines.append(f"<line x1='{x:.1f}' y1='{frame.y0:.1f}' x2='{x:.1f}' y2='{frame.y1:.1f}' "
                         f"stroke='#bbb' stroke-width='0.6' stroke-dasharray='3 3'/>")
            label(f"{lon}°E", x, frame.y1 + 14, size=9, anchor="middle", fill="#666")
            lon += 2
        lat = math.floor(frame.lat1)
        lat -= lat % 2      # even parallels, so the Equator is one of them
        while frame.y0 + (frame.lat1 - lat) * frame.scale <= frame.y1:
            _, y = frame.to_px(frame.lon0, lat)
            lines.append(f"<line x1='{frame.x0:.1f}' y1='{y:.1f}' x2='{frame.x1:.1f}' y2='{y:.1f}' "
                         f"stroke='#bbb' stroke-width='0.6' stroke-dasharray='3 3'/>")
            hemi = "N" if lat > 0 else "S" if lat < 0 else ""
            label(f"{abs(lat)}°{hemi}" if hemi else "0° (Equator)", frame.x0 - 6, y + 3,
                  size=9, anchor="end", fill="#666")
            lat -= 2

    # ── the features ──
    for feature in spec.features:
        key, where = _place(spec, feature)
        if where is None:
            unplaced.append(feature.name)
            continue
        text = _label_for(feature, key)
        what = feature.note or KEY_TEXT.get(feature.kind, feature.kind.replace("_", " "))
        kind = feature.kind

        if kind == "lake":
            if isinstance(where, list):
                water.append(f"<polygon points='{_poly(where, frame)}' fill='#bcd8ee' stroke='#3b78a8' "
                             f"stroke-width='1.2' data-layer='base'/>")
                cx = sum(frame.to_px(a, b)[0] for a, b in where) / len(where)
                cy = sum(frame.to_px(a, b)[1] for a, b in where) / len(where)
            else:
                cx, cy = frame.to_px(*where)
                water.append(f"<ellipse cx='{cx:.1f}' cy='{cy:.1f}' rx='7' ry='5' fill='#bcd8ee' "
                             f"stroke='#3b78a8' stroke-width='1.2' data-layer='base'/>")
                cx += 9
            symbol("lake")
            label(text, cx, cy + 4, feature=feature, size=10, anchor="middle" if isinstance(where, list) else "start",
                  style="italic", fill="#1f4e79", function=f"a lake: {what}")

        elif kind in ("river", "road", "railway", "county_boundary", "boundary", "path"):
            path = where if isinstance(where, list) else []
            if len(path) < 2:
                unplaced.append(feature.name)
                continue
            stroke = {"river": "#2f6fb0", "road": "#b3542b", "railway": "#333",
                      "county_boundary": "#777", "boundary": "#222"}.get(kind, "#555")
            dash = {"railway": "6 3", "county_boundary": "5 4", "boundary": "8 4"}.get(kind, "")
            lines.append(f"<polyline points='{_poly(path, frame)}' fill='none' stroke='{stroke}' "
                         f"stroke-width='{2.2 if kind == 'river' else 1.8}' stroke-linejoin='round' "
                         f"stroke-linecap='round'" + (f" stroke-dasharray='{dash}'" if dash else "") + "/>")
            if kind == "railway":
                lines.append(f"<polyline points='{_poly(path, frame)}' fill='none' stroke='#fff' "
                             f"stroke-width='1' stroke-dasharray='6 3' stroke-dashoffset='6'/>")
            symbol(kind)
            mid = path[len(path) // 2]
            mx, my = frame.to_px(*mid)
            label(text, mx + 4, my - 5, feature=feature, size=10, style="italic",
                  fill="#1f4e79" if kind == "river" else "#333", function=f"a {kind.replace('_', ' ')}: {what}")

        elif kind in ("mountain", "relief", "hills", "highland"):
            x, y = frame.to_px(*where)
            symbols.append(f"<polygon points='{x:.1f},{y - 7:.1f} {x - 7:.1f},{y + 5:.1f} {x + 7:.1f},{y + 5:.1f}' "
                           f"fill='#6b4f2a' stroke='#3d2b12' stroke-width='1'/>")
            symbol("mountain")
            label(text, x + 10, y + 4, feature=feature, size=10.5, function=f"a mountain or highland: {what}")

        elif kind in ("vegetation", "forest"):
            x, y = frame.to_px(*where)
            symbols.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='9' fill='#a9c99a' stroke='#3d6b2f' stroke-width='1'/>")
            symbol("vegetation")
            label(text, x + 12, y + 4, feature=feature, size=10, function=f"vegetation: {what}")

        elif kind in ("building", "block", "classroom", "office", "structure") and spec.schematic:
            x, y = frame.to_px(*where)
            symbols.append(f"<rect x='{x - 16:.1f}' y='{y - 9:.1f}' width='32' height='18' fill='#e8d9b5' "
                           f"stroke='#5a4a2a' stroke-width='1.2'/>")
            symbol("building")
            label(text, x, y + 26, feature=feature, size=10, anchor="middle", function=f"a building: {what}")

        else:  # towns, capital, settlements, ports, airports, anything else
            x, y = frame.to_px(*where)
            is_capital = kind == "capital" or (key == CAPITAL and kind in ("town", "city", "settlement"))
            if is_capital:
                symbols.append(f"<polygon points='{_star(x, y, 7)}' fill='#c0392b' stroke='#7a1f16' stroke-width='1'/>")
                symbol("capital")
            else:
                symbols.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='#111' stroke='#fff' stroke-width='1'/>")
                symbol("town" if kind in ("town", "city", "settlement", "capital") else kind)
            label(text, x + 8, y + 4, feature=feature, size=11 if is_capital else 10.5,
                  weight="bold" if is_capital else "normal",
                  function=("the capital city" if is_capital else f"a {KEY_TEXT.get(kind, kind).lower()}: {what}"))

    # ── the furniture: title, north arrow, scale bar, key ──
    title = spec.title or (f"Sketch map of {spec.extent}" if spec.schematic else "Sketch map of Kenya")
    label(title, WIDTH / 2, 36, size=18, anchor="middle", weight="bold")
    label("Sketch map — not to projection" if spec.schematic else "Sketch map — not drawn to survey accuracy",
          WIDTH / 2, 54, size=9.5, anchor="middle", fill="#666")

    nx, ny = WIDTH - MARGIN["right"] - 30, MARGIN["top"] + 30
    symbols.append(f"<polygon points='{nx},{ny - 22} {nx - 8},{ny + 8} {nx},{ny} {nx + 8},{ny + 8}' "
                   f"fill='#111'/>")
    label("N", nx, ny - 26, size=13, anchor="middle", weight="bold")

    bar_y = HEIGHT - MARGIN["bottom"] + 40
    bar_x = MARGIN["left"]
    if spec.schematic:
        units = 100
        px = 25 * frame.scale
        scale_text = f"Scale: 1 cm represents about {units} m"  # an assumption stated
        segments = [(f"{i * units // 4:g} m" if i else "0") for i in range(5)]
    else:
        km_per_px = 111.0 / frame.scale
        km = 200 if 200 / km_per_px >= 90 else 100
        px = km / km_per_px
        scale_text = f"Scale: 1 : {int(round(km_per_px * 100000 * 96 / 2.54, -5)):,}   ({km} km bar)"
        segments = [f"{i * km // 4}" for i in range(5)]
    for i in range(4):
        fill = "#111" if i % 2 == 0 else "#fff"
        symbols.append(f"<rect x='{bar_x + i * px / 4:.1f}' y='{bar_y:.1f}' width='{px / 4:.1f}' height='7' "
                       f"fill='{fill}' stroke='#111' stroke-width='1'/>")
    for i, text in enumerate(segments):
        label(text if i else "0", bar_x + i * px / 4, bar_y + 20, size=9, anchor="middle")
    label(scale_text if spec.schematic else scale_text.split("   ")[0], bar_x + px + 12, bar_y + 7, size=9.5)
    if not spec.schematic:
        label("km", bar_x + px + 12, bar_y + 20, size=9, fill="#666")

    key_x = WIDTH / 2 + 20
    key_y = HEIGHT - MARGIN["bottom"] + 22
    label("Key", key_x, key_y, size=12, weight="bold")
    row = key_y + 16
    for kind in used_symbols:
        glyph_x, glyph_y = key_x + 8, row - 4
        if kind == "capital":
            symbols.append(f"<polygon points='{_star(glyph_x, glyph_y, 6)}' fill='#c0392b' stroke='#7a1f16' stroke-width='1'/>")
        elif kind == "town":
            symbols.append(f"<circle cx='{glyph_x}' cy='{glyph_y}' r='4' fill='#111'/>")
        elif kind == "mountain":
            symbols.append(f"<polygon points='{glyph_x},{glyph_y - 6} {glyph_x - 6},{glyph_y + 5} {glyph_x + 6},{glyph_y + 5}' fill='#6b4f2a'/>")
        elif kind == "lake":
            symbols.append(f"<rect x='{glyph_x - 8}' y='{glyph_y - 5}' width='16' height='10' fill='#bcd8ee' stroke='#3b78a8'/>")
        elif kind == "river":
            symbols.append(f"<line x1='{glyph_x - 9}' y1='{glyph_y}' x2='{glyph_x + 9}' y2='{glyph_y}' stroke='#2f6fb0' stroke-width='2.2'/>")
        elif kind == "road":
            symbols.append(f"<line x1='{glyph_x - 9}' y1='{glyph_y}' x2='{glyph_x + 9}' y2='{glyph_y}' stroke='#b3542b' stroke-width='1.8'/>")
        elif kind == "railway":
            symbols.append(f"<line x1='{glyph_x - 9}' y1='{glyph_y}' x2='{glyph_x + 9}' y2='{glyph_y}' stroke='#333' stroke-width='1.8' stroke-dasharray='6 3'/>")
        elif kind in ("boundary", "county_boundary"):
            symbols.append(f"<line x1='{glyph_x - 9}' y1='{glyph_y}' x2='{glyph_x + 9}' y2='{glyph_y}' stroke='#222' stroke-width='1.8' stroke-dasharray='{'8 4' if kind == 'boundary' else '5 4'}'/>")
        elif kind == "vegetation":
            symbols.append(f"<circle cx='{glyph_x}' cy='{glyph_y}' r='6' fill='#a9c99a' stroke='#3d6b2f'/>")
        elif kind == "building":
            symbols.append(f"<rect x='{glyph_x - 8}' y='{glyph_y - 5}' width='16' height='10' fill='#e8d9b5' stroke='#5a4a2a'/>")
        else:
            symbols.append(f"<circle cx='{glyph_x}' cy='{glyph_y}' r='4' fill='#111'/>")
        label(KEY_TEXT.get(kind, kind.replace("_", " ").title()), key_x + 24, row, size=10)
        row += 15

    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {WIDTH} {HEIGHT}' role='img' "
        f"aria-label='{_esc(title)}'>"
        f"<rect x='0' y='0' width='{WIDTH}' height='{HEIGHT}' fill='#ffffff'/>"
        f"<rect x='{MARGIN['left'] - 30}' y='{MARGIN['top'] - 10}' width='{WIDTH - MARGIN['left'] - MARGIN['right'] + 60}' "
        f"height='{HEIGHT - MARGIN['top'] - MARGIN['bottom'] + 50}' fill='none' stroke='#111' stroke-width='1.2'/>"
        + "".join(base) + "".join(water) + "".join(lines) + "".join(symbols) + "".join(labels)
        + "</svg>"
    )

    # Everything that is not a feature is furniture: shown, never blanked.
    scene_parts = list(parts) + [
        {"label": text, "role": "furniture", "assessable": False, "occludable": False,
         "function": "", "alt_text": text} for text in furniture_texts]
    scene = {"title": title, "parts": scene_parts,
             "map": {"extent": spec.extent, "placed_by_gazetteer":
                     [f.name for f in spec.features if f.placed_by == "gazetteer"],
                     "placed_by_model": [f.name for f in spec.features if f.placed_by == "model"],
                     "unplaced": unplaced}}
    alt = (f"{title}: " + ", ".join(p["label"] for p in parts)) if parts else title
    return {"svg": svg, "scene": scene, "key": list(used_symbols), "unplaced": unplaced,
            "alt_text": alt, "title": title}


def _star(x: float, y: float, r: float) -> str:
    points = []
    for i in range(10):
        radius = r if i % 2 == 0 else r * 0.45
        angle = -math.pi / 2 + i * math.pi / 5
        points.append(f"{x + radius * math.cos(angle):.1f},{y + radius * math.sin(angle):.1f}")
    return " ".join(points)


# ── entry ─────────────────────────────────────────────────────────────────────

_MAP_SUBJECT = re.compile(r"geograph|social studies|environmental|history and government", re.I)
_MAP_WORD = re.compile(r"\bmaps?\b|\bsketch map\b|\blocat", re.I)


def wants_a_map(subject: str, title: str = "", content: Any = None) -> bool:
    """Whether this diagram should be a map drawn here."""
    if isinstance(content, dict) and from_model(content) is not None:
        return True
    return bool(_MAP_SUBJECT.search(subject or "") and _MAP_WORD.search(title or ""))


def render_from_model(content: Any) -> dict[str, Any] | None:
    """The map for a model response that carries map data, else None."""
    spec = from_model(content)
    if spec is None:
        return None
    try:
        return render(spec)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not draw the map: %s", exc)
        return None
