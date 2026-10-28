"""Builds small text-based PDFs for tests (one Helvetica text block per page, WinAnsi encoding)."""


def _escape(line: str) -> bytes:
    return line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make_pdf(pages: list[str]) -> bytes:
    objects: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(pages):
        content = b"BT /F1 10 Tf 12 TL 50 800 Td " + b" ".join(b"(" + _escape(line) + b") '" for line in text.splitlines()) + b" ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {4 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


HEADER = "Regulamento PDM-Cascais {n}"

#: A small stand-in for the PDM-Cascais Regulamento: a table of contents, then articles across pages.
REGULAMENTO_PAGES = [
    HEADER.format(n=1) + "\nÍndice\nArtigo 1.º ........................ 2\nArtigo 61.º ....................... 3",
    HEADER.format(n=2) + "\nArtigo 1.º\nObjeto, âmbito territorial e vinculação\n1 - O presente Regulamento constitui o "
    "elemento normativo do Plano Diretor Municipal de Cascais.\nArtigo 2.º\nEstratégia e objetivos\nO PDM estabelece "
    "as orientações de ordenamento e de urbanismo.",
    HEADER.format(n=3) + "\nArtigo 61.º\nPrincípios gerais do solo urbano\n1 - Em solo urbano os espaços destinam-se "
    "predominantemente à urbanização e edificação, designadamente de habitação, comércio e serviços.\n"
    "2 - A qualificação do solo urbano consta da Planta de Ordenamento.",
    HEADER.format(n=4) + "\nArtigo 62.º\nEstacionamento\n1 - As operações urbanísticas asseguram lugares de "
    "estacionamento por fogo, nos termos do quadro anexo.\nArtigo 63.º-A\nLicenciamento\nO licenciamento e a "
    "comunicação prévia seguem o regime jurídico da urbanização e edificação.",
]
