"""Checks a user's file from its bytes and makes the copy HABITA keeps (AC10.2, AC10.3).

The type comes from the content, never the name. Capture date and GPS are read first; the kept copy then has no
location or device data: images are re-encoded from their pixels, PDFs are rewritten without their document info."""

import io
import math
from dataclasses import dataclass
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject, StreamObject

MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 10
#: A GPS point farther than this from the property is shown as a mismatch.
NEAR_METRES = 250
#: The image HABITA sends for reading; large enough for a plan's labels.
READ_SIDE = 1600
#: Bounds on work per file: a small upload must not expand into a large one while it is checked.
MAX_PIXELS = 40_000_000
MAX_PAGES = 30
#: The only page entries kept: what draws the page. Actions, annotations, metadata and thumbnails are dropped.
_PAGE_KEYS = {"/Type", "/Parent", "/Contents", "/Resources", "/MediaBox", "/CropBox", "/BleedBox", "/TrimBox",
              "/ArtBox", "/Rotate", "/UserUnit", "/Group"}
#: Entries dropped from any dictionary reachable from a page's resources.
_DROP = {"/Metadata", "/PieceInfo", "/AA", "/OC", "/OPI", "/JS", "/JavaScript", "/A"}

_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"%PDF-", "application/pdf"))
_EXIF_GPS, _EXIF_IFD = 0x8825, 0x8769
_DATETIME_ORIGINAL, _DATETIME = 0x9003, 0x0132


class FileRejected(ValueError):
    """The file can't be accepted; the message is safe to show."""


@dataclass(frozen=True)
class Inspected:
    content_type: str
    kept: bytes
    #: A JPEG for the model to read, or None when the file has no image HABITA can read.
    readable: bytes | None
    captured_at: datetime | None
    gps: tuple[float, float] | None


def sniff(data: bytes) -> str:
    for magic, content_type in _MAGIC:
        if data.startswith(magic):
            return content_type
    raise FileRejected("Only JPEG, PNG and PDF files are accepted.")


def _degrees(value, ref) -> float | None:
    try:
        d, m, s = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if ref in ("S", "W") else deg


def _metadata(image: Image.Image) -> tuple[datetime | None, tuple[float, float] | None]:
    exif = image.getexif()
    raw = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
    try:
        captured = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S") if raw else None
    except ValueError:
        captured = None
    gps = exif.get_ifd(_EXIF_GPS)
    lat = _degrees(gps.get(2), gps.get(1)) if gps else None
    lng = _degrees(gps.get(4), gps.get(3)) if gps else None
    point = (lat, lng) if lat is not None and lng is not None and abs(lat) <= 90 and abs(lng) <= 180 else None
    return captured, point


def _jpeg(image: Image.Image, side: int | None = None, quality: int = 90) -> bytes:
    image = image.convert("RGB")
    if side:
        image.thumbnail((side, side))
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)  # no exif, no icc, no comments: only pixels
    return out.getvalue()


def _strip_jpeg(data: bytes) -> bytes:
    """A JPEG stream without its metadata segments (EXIF, XMP, IPTC, ICC, comments); APP0 and Adobe APP14 stay."""
    if not data.startswith(b"\xff\xd8"):
        return data
    out, i = bytearray(b"\xff\xd8"), 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: the rest is image data
            out += data[i:]
            return bytes(out)
        length = int.from_bytes(data[i + 2:i + 4], "big")
        segment = data[i:i + 2 + length]
        if not (0xE1 <= marker <= 0xED or marker == 0xEF or marker == 0xFE):
            out += segment
        i += 2 + length
    return data if i < len(data) else bytes(out)


def _scrub(obj, seen: set[int]) -> None:
    """Drop metadata and actions from every dictionary and stream reachable from a page's resources."""
    if isinstance(obj, IndirectObject):
        if obj.idnum in seen:
            return
        seen.add(obj.idnum)
        obj = obj.get_object()
    if isinstance(obj, DictionaryObject):  # StreamObject is one too
        for key in list(obj.keys()):
            if key in _DROP:
                del obj[key]
        if isinstance(obj, StreamObject) and obj.get("/Filter") in ("/DCTDecode", ArrayObject([NameObject("/DCTDecode")])):
            obj._data = _strip_jpeg(obj._data)  # encoded JPEG bytes: pypdf can't re-encode them, so edit in place
        for value in list(obj.values()):
            _scrub(value, seen)
    elif isinstance(obj, ArrayObject):
        for value in obj:
            _scrub(value, seen)


def _clean_image(data: bytes, content_type: str) -> Inspected:
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise FileRejected("This image is too large to process.")
            source.load()
            captured, gps = _metadata(source)
            upright = ImageOps.exif_transpose(source)  # keep how it looks once orientation data is gone
            if content_type == "image/png":
                # A new image carries no info dict, so no exif, text or icc chunk can follow the pixels.
                pixels = Image.new(upright.mode, upright.size)
                if upright.mode == "P":
                    pixels.putpalette(upright.getpalette())
                pixels.paste(upright)
                out = io.BytesIO()
                pixels.save(out, "PNG")
                kept = out.getvalue()
            else:
                kept = _jpeg(upright)
            readable = _jpeg(upright, READ_SIDE, 85)
    except FileRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise FileRejected("This image could not be opened.") from None
    return Inspected(content_type, kept, readable, captured, gps)


def _page_images(page) -> list:
    resources = page.get("/Resources")
    resources = resources.get_object() if resources is not None else {}
    xobjects = resources.get("/XObject")
    xobjects = xobjects.get_object() if xobjects is not None else {}
    found = []
    for ref in xobjects.values():
        obj = ref.get_object()
        if isinstance(obj, StreamObject) and obj.get("/Subtype") == "/Image":
            found.append(obj)
    return found


def _decode(xobj) -> Image.Image | None:
    """One image within the pixel limit, read only when it is a plain JPEG stream: Pillow reads its real size from the
    JPEG header and refuses it past the limit before decoding. Any other encoding is not read (the file is still kept),
    because its decoded size is only what the PDF claims."""
    try:
        if xobj.get("/Filter") not in ("/DCTDecode", ArrayObject([NameObject("/DCTDecode")])):
            return None
        image = Image.open(io.BytesIO(xobj._data))
        if image.width * image.height > MAX_PIXELS:
            return None
        image.load()
        return image
    except Exception:  # noqa: BLE001 - an image HABITA can't decode is simply not read
        return None


def _clean_pdf(data: bytes) -> Inspected:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise FileRejected("Password-protected PDFs are not accepted.")
        if len(reader.pages) > MAX_PAGES:
            raise FileRejected(f"PDFs can have at most {MAX_PAGES} pages.")
        # A new document: the catalogue (open actions, scripts, forms, document metadata) is never copied.
        # Pages are cleaned before they are copied, so what was dropped is never copied at all: no orphaned objects
        # and no pass over the streams (pruning orphans afterwards made pypdf decode every stream to compare them).
        writer = PdfWriter()
        seen: set[int] = set()
        for source in reader.pages:
            for key in list(source.keys()):
                if key not in _PAGE_KEYS:
                    del source[key]
            _scrub(source.get(NameObject("/Resources")), seen)
            writer.add_page(source)
        out = io.BytesIO()
        writer.write(out)
        # A scanned plan is usually one large image: HABITA reads the largest image of the first pages. Sizes are read
        # from each image's dictionary, and only the chosen one, within the pixel limit, is ever decoded.
        best = None
        for page in reader.pages[:3]:
            for xobj in _page_images(page):
                pixels = int(xobj.get("/Width", 0)) * int(xobj.get("/Height", 0))
                if 0 < pixels <= MAX_PIXELS and (best is None or pixels > best[0]):
                    best = (pixels, xobj)
        readable = (best[0], _decode(best[1])) if best is not None else None
    except FileRejected:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError):
        raise FileRejected("This PDF could not be opened.") from None
    picture = None
    if readable is not None and readable[1] is not None:
        try:
            picture = _jpeg(readable[1], READ_SIDE, 85)
        except (OSError, ValueError):
            picture = None
    return Inspected("application/pdf", out.getvalue(), picture, None, None)


def inspect(data: bytes) -> Inspected:
    if not data:
        raise FileRejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise FileRejected("Files can have at most 10 MB.")
    content_type = sniff(data)
    return _clean_pdf(data) if content_type == "application/pdf" else _clean_image(data, content_type)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> int:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return round(2 * 6_371_000 * math.asin(math.sqrt(h)))
