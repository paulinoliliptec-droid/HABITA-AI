"""HR-011 reference table: cost of works per m², by request type.

There is no official source for the market price of works in Portugal. These ranges come from public price guides,
cited below, and are assumptions, never quotes or market prices (AC11.2). The owner approved having a table on
2026-10-31; the figures themselves stay marked as awaiting the owner's approval until ``APPROVED_ON`` is set.
"""

from dataclasses import dataclass

#: Set when the owner approves these figures; until then every use says they await approval.
APPROVED_ON: str | None = None
AUTHOR = "Claude Code for HABITA, from the public guides below"
COMPILED_ON = "2026-10-31"


@dataclass(frozen=True)
class CostRange:
    low: int  # €/m²
    high: int  # €/m²
    basis: str
    sources: tuple[tuple[str, str], ...]  # (title, url)

    @property
    def likely(self) -> float:
        return (self.low + self.high) / 2  # the midpoint, and said so


_RENOVATION = (
    ("idealista — Remodelação de casas: 500 a 1500 €/m²", "https://www.idealista.pt/obras-em-casa/remodelacao-de-casas/"),
    ("Habitissimo — orçamentos de remodelação de casa", "https://www.habitissimo.pt/orcamentos/remodelacao-de-casa"),
    ("Fixando — remodelação de casa de banho, média 2302 € (14/07/2025)",
     "https://www.fixando.pt/en/remodelacao-de-casa-de-banho/orcamento"),
)

COSTS: dict[str, CostRange] = {
    "interior_works": CostRange(500, 1500, "Interior renovation, per m² of the area renovated.", _RENOVATION),
    "change_of_use": CostRange(500, 1500, "Adapting the space to the new use, per m² of the area changed; the "
                                          "project and licensing are not included.", _RENOVATION),
    "unit_conversion": CostRange(800, 1500, "Dividing into units (new walls, a second kitchen and bathroom, separate "
                                            "entrances), per m² of the whole area.", _RENOVATION + (
        ("Portugal Property — Remodel Quinta: 800 to 1500+ €/m² with structural works (2025)",
         "https://www.portugalproperty.com/news-blog/remodeling-portuguese-quinta-budget-timeline-2025"),)),
}
