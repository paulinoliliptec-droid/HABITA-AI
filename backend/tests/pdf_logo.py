"""HABITA's logo on the PDF cover (2026-11-03) is the report's own image, not map imagery. Tests that count images
leave out exactly that image, recognised by its pixels, never by size alone (Codex logo r1)."""

from pathlib import Path

from PIL import Image

_MARK = Image.open(Path(__file__).parents[1] / "app/services/report/assets/habita-mark.png")
_MARK_RGB = _MARK.convert("RGB").tobytes()


def is_logo(pdf_image) -> bool:
    """A pypdf image object that is the cover's logo: same size and the same colour pixels (its alpha is stored apart)."""
    image = pdf_image.image
    return image.size == _MARK.size and image.convert("RGB").tobytes() == _MARK_RGB
