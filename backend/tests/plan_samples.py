"""HR-012 synthetic plans for the fidelity criterion (no private data, no paid call).

Each plan is stated once, as geometry in metres (north at the top of the drawing). The same geometry gives both the
drawing (``python -m tests.plan_samples`` writes the PNGs to ``docs/evidence/hr012/samples``) and the plan inventory
used by ``compare``, so the picture and the inventory can't drift apart.

Zones: a room covers a cell of the 3×3 grid of its floor when it covers more than half of that cell; the cell that
holds the room's centre always counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.concepts.fidelity import Inventory, Room

ZONES = (("NW", "N", "NE"), ("W", "C", "E"), ("SW", "S", "SE"))


@dataclass(frozen=True)
class Box:
    id: str
    type: str
    x0: float
    y0: float
    x1: float
    y1: float
    floor: int = 0

    @property
    def area(self) -> float:
        return round((self.x1 - self.x0) * (self.y1 - self.y0), 1)


@dataclass(frozen=True)
class Sample:
    key: str
    title: str
    rooms: tuple[Box, ...]
    doors: tuple[tuple[str, str], ...]
    windows: dict[str, list[str]]
    entrances: dict[str, list[str]]
    measured: bool = True
    #: Stairs as (floor, x0, y0, x1, y1); a plan with stairs is drawn with them on every floor.
    stairs: tuple[tuple[int, float, float, float, float], ...] = ()
    note: str = ""

    def floors(self) -> int:
        return max(r.floor for r in self.rooms) + 1

    def bbox(self, floor: int) -> tuple[float, float, float, float]:
        rs = [r for r in self.rooms if r.floor == floor]
        return min(r.x0 for r in rs), min(r.y0 for r in rs), max(r.x1 for r in rs), max(r.y1 for r in rs)

    def room(self, rid: str) -> Box:
        return next(r for r in self.rooms if r.id == rid)


def zones(sample: Sample, box: Box) -> list[str]:
    bx0, by0, bx1, by1 = sample.bbox(box.floor)
    cw, ch = (bx1 - bx0) / 3, (by1 - by0) / 3
    cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    out = []
    for row in range(3):
        for col in range(3):
            x0, y0 = bx0 + col * cw, by0 + row * ch
            ov = max(0, min(box.x1, x0 + cw) - max(box.x0, x0)) * max(0, min(box.y1, y0 + ch) - max(box.y0, y0))
            centre = x0 <= cx < x0 + cw + 1e-9 and y0 <= cy < y0 + ch + 1e-9
            if ov > cw * ch / 2 + 1e-9 or centre:
                out.append(ZONES[row][col])
    return out


def inventory(sample: Sample) -> Inventory:
    return Inventory(
        rooms=[Room(id=r.id, type=r.type, area=r.area if sample.measured else None, zones=zones(sample, r),
                    floor=r.floor if sample.floors() > 1 else None) for r in sample.rooms],
        connections=list(sample.doors),
        windows={k: list(v) for k, v in sample.windows.items()},
        entrances={k: list(v) for k, v in sample.entrances.items()},
        floors=sample.floors(),
        stairs=bool(sample.stairs),
    )


def shared_wall(a: Box, b: Box) -> tuple[str, float, float, float] | None:
    """The wall two rooms share: ('v', x, y_from, y_to) or ('h', y, x_from, x_to); None if they don't touch."""
    if a.floor != b.floor:
        return None
    for x in {a.x1, a.x0} & {b.x0, b.x1}:
        if (x == a.x1 and x == b.x0) or (x == a.x0 and x == b.x1):
            lo, hi = max(a.y0, b.y0), min(a.y1, b.y1)
            if hi - lo > 0.8:
                return "v", x, lo, hi
    for y in {a.y1, a.y0} & {b.y0, b.y1}:
        if (y == a.y1 and y == b.y0) or (y == a.y0 and y == b.y1):
            lo, hi = max(a.x0, b.x0), min(a.x1, b.x1)
            if hi - lo > 0.8:
                return "h", y, lo, hi
    return None


def on_outer_wall(sample: Sample, box: Box, side: str) -> bool:
    bx0, by0, bx1, by1 = sample.bbox(box.floor)
    return {"N": box.y0 == by0, "S": box.y1 == by1, "W": box.x0 == bx0, "E": box.x1 == bx1}[side]


def B(rid, kind, x0, y0, x1, y1, floor=0):  # noqa: N802 - short constructor for the tables below
    return Box(rid, kind, x0, y0, x1, y1, floor)


T1_ROOMS = (B("SALA", "living", 0, 0, 5, 8), B("COZINHA", "kitchen", 5, 0, 10, 3), B("HALL", "hall", 5, 3, 7, 5),
            B("WC", "bathroom", 7, 3, 10, 5), B("QUARTO", "bedroom", 5, 5, 10, 8))
T1_DOORS = (("SALA", "COZINHA"), ("SALA", "HALL"), ("HALL", "WC"), ("HALL", "QUARTO"))
T1_WINDOWS = {"SALA": ["W"], "COZINHA": ["N"], "QUARTO": ["S", "E"]}

SAMPLES: dict[str, Sample] = {s.key: s for s in (
    Sample("t1", "Planta T1", T1_ROOMS, T1_DOORS, T1_WINDOWS, {"SALA": ["S"]},
           note="one bedroom; the living room is clearly the largest"),
    Sample("t3", "Planta T3",
           (B("SALA", "living", 0, 0, 7, 6), B("COZINHA", "kitchen", 7, 0, 14, 4), B("WC 2", "bathroom", 7, 4, 10, 6),
            B("ARRUMOS", "storage", 10, 4, 14, 6), B("HALL", "hall", 0, 6, 14, 7.5),
            B("QUARTO 1", "bedroom", 0, 7.5, 5, 10), B("QUARTO 2", "bedroom", 5, 7.5, 9, 10),
            B("WC", "bathroom", 9, 7.5, 11, 10), B("QUARTO 3", "bedroom", 11, 7.5, 14, 10)),
           (("SALA", "COZINHA"), ("SALA", "HALL"), ("HALL", "WC 2"), ("HALL", "ARRUMOS"), ("HALL", "QUARTO 1"),
            ("HALL", "QUARTO 2"), ("HALL", "WC"), ("HALL", "QUARTO 3")),
           {"SALA": ["N", "W"], "COZINHA": ["N", "E"], "QUARTO 1": ["S", "W"], "QUARTO 2": ["S"],
            "QUARTO 3": ["S", "E"]},
           {"HALL": ["E"]}, note="three bedrooms, a corridor and a small store room"),
    Sample("t1-unmeasured", "Planta T1 sem medidas", T1_ROOMS, T1_DOORS, T1_WINDOWS, {"SALA": ["S"]}, measured=False,
           note="the same T1 without areas: no room can be called the largest"),
    Sample("t2-tie", "Planta T2 com empate",
           (B("SALA", "living", 0, 0, 6, 5), B("QUARTO 1", "bedroom", 6, 0, 12, 5), B("HALL", "hall", 0, 5, 12, 6.5),
            B("COZINHA", "kitchen", 0, 6.5, 5, 10), B("WC", "bathroom", 5, 6.5, 8, 10),
            B("QUARTO 2", "bedroom", 8, 6.5, 12, 10)),
           (("SALA", "HALL"), ("QUARTO 1", "HALL"), ("HALL", "COZINHA"), ("HALL", "WC"), ("HALL", "QUARTO 2")),
           {"SALA": ["N"], "QUARTO 1": ["N"], "COZINHA": ["S"], "QUARTO 2": ["S", "E"]}, {"HALL": ["W"]},
           note="the living room and bedroom 1 have the same area (30 m²)"),
    Sample("duplex", "Planta duplex (2 pisos)",
           (B("SALA", "living", 0, 0, 7, 6), B("COZINHA", "kitchen", 7, 0, 10, 6), B("HALL", "hall", 0, 6, 10, 8),
            B("QUARTO 1", "bedroom", 0, 0, 6, 6, 1), B("QUARTO 2", "bedroom", 6, 0, 10, 6, 1),
            B("PATAMAR", "hall", 0, 6, 8, 8, 1), B("WC", "bathroom", 8, 6, 10, 8, 1)),
           (("SALA", "COZINHA"), ("SALA", "HALL"), ("PATAMAR", "QUARTO 1"), ("PATAMAR", "QUARTO 2"),
            ("PATAMAR", "WC")),
           {"SALA": ["N", "W"], "COZINHA": ["N", "E"], "QUARTO 1": ["N", "W"], "QUARTO 2": ["N", "E"]},
           {"HALL": ["S"]}, stairs=((0, 0.3, 6.3, 3, 7.7), (1, 0.3, 6.3, 3, 7.7)),
           note="two floors joined by stairs"),
)}


# --- drawing -------------------------------------------------------------------------------------------------------

PX, MARGIN = 70, 100
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BLUE, BLACK, WHITE = (100, 150, 255), (0, 0, 0), (255, 255, 255)


def draw(sample: Sample, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font, small = ImageFont.truetype(FONT, 22), ImageFont.truetype(FONT, 18)
    floors = sample.floors()
    widths = [sample.bbox(f)[2] - sample.bbox(f)[0] for f in range(floors)]
    height = max(sample.bbox(f)[3] - sample.bbox(f)[1] for f in range(floors))
    img = Image.new("RGB", (int(sum(widths) * PX + MARGIN * (floors + 1)), int(height * PX + MARGIN * 2)), WHITE)
    d = ImageDraw.Draw(img)
    d.text((MARGIN, 30), f"{sample.title} — exemplo sintético", font=font, fill=BLACK)
    offsets, ox = [], MARGIN
    for f in range(floors):
        offsets.append(ox)
        ox += widths[f] * PX + MARGIN

    def P(f, x, y):  # noqa: N802
        bx0, by0, *_ = sample.bbox(f)
        return offsets[f] + (x - bx0) * PX, MARGIN + (y - by0) * PX

    for r in sample.rooms:
        d.rectangle([*P(r.floor, r.x0, r.y0), *P(r.floor, r.x1, r.y1)], outline=BLACK, width=6)
    for f, x0, y0, x1, y1 in sample.stairs:
        (a, b), (c, e) = P(f, x0, y0), P(f, x1, y1)
        d.rectangle([a, b, c, e], outline=BLACK, width=2)
        for i in range(1, 8):
            xx = a + (c - a) * i / 8
            d.line([xx, b, xx, e], fill=BLACK, width=2)
        d.text((c + 6, b), "ESCADA", font=small, fill=BLACK)
    for a_id, b_id in sample.doors:
        a, b = sample.room(a_id), sample.room(b_id)
        wall = shared_wall(a, b)
        assert wall, f"{sample.key}: {a_id} and {b_id} share no wall"
        kind, at, lo, hi = wall
        mid, half = (lo + hi) / 2, 0.45
        if kind == "v":
            (p, q), (s, t) = P(a.floor, at, mid - half), P(a.floor, at, mid + half)
            d.rectangle([p - 5, q, s + 5, t], fill=WHITE)
        else:
            (p, q), (s, t) = P(a.floor, mid - half, at), P(a.floor, mid + half, at)
            d.rectangle([p, q - 5, s, t + 5], fill=WHITE)
    for r in sample.rooms:
        for side in "NESW":
            items = ["w"] * sample.windows.get(r.id, []).count(side) + \
                    ["e"] * sample.entrances.get(r.id, []).count(side)
            if not items:
                continue
            assert on_outer_wall(sample, r, side), f"{sample.key}: {r.id} {side} is not an outer wall"
            for i, what in enumerate(items):
                t = (i + 1) / (len(items) + 1)
                if side in "NS":
                    y = r.y0 if side == "N" else r.y1
                    x = r.x0 + (r.x1 - r.x0) * t
                    (p, q), (s, u) = P(r.floor, x - 0.6, y), P(r.floor, x + 0.6, y)
                    box = [p, q - 5, s, u + 5]
                else:
                    x = r.x0 if side == "W" else r.x1
                    y = r.y0 + (r.y1 - r.y0) * t
                    (p, q), (s, u) = P(r.floor, x, y - 0.6), P(r.floor, x, y + 0.6)
                    box = [p - 5, q, s + 5, u]
                if what == "w":
                    d.rectangle(box, fill=BLUE)
                else:
                    d.rectangle(box, fill=WHITE)
                    w = d.textlength("ENTRADA", font=small)
                    d.text({"N": (box[0], box[1] - 26), "S": (box[0], box[3] + 4), "E": (box[2] + 6, box[1]),
                            "W": (box[0] - w - 6, box[1])}[side], "ENTRADA", font=small, fill=BLACK)
    for r in sample.rooms:
        label = r.id + (f" {r.area:g} m²" if sample.measured else "")
        cx, cy = P(r.floor, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        w = d.textlength(label, font=small)
        d.text((cx - w / 2, cy - 10), label, font=small, fill=BLACK)
    if floors > 1:
        for f in range(floors):
            d.text((offsets[f], MARGIN - 34), f"PISO {f}", font=small, fill=BLACK)
    img.save(out)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[2] / "docs" / "evidence" / "hr012" / "samples"
    target.mkdir(parents=True, exist_ok=True)
    for s in SAMPLES.values():
        draw(s, target / f"plan-{s.key}.png")
        print(target / f"plan-{s.key}.png")
