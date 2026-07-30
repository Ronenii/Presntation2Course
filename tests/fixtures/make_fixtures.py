"""Deterministic deck fixtures. Run as a script to (re)write terse.pdf/terse.pptx."""

import io
import zipfile
from pathlib import Path

HERE = Path(__file__).parent


def make_pdf(pages: list[list[str]]) -> bytes:
    """A minimal uncompressed PDF, one text object per page. Stdlib only."""
    objs: list[str] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append("<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        contents = 5 + 2 * i
        objs.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 720 540] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {contents} 0 R >>"
        )
        body = "BT /F1 24 Tf 40 480 Td 30 TL\n"
        for line in lines:
            esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            body += f"({esc}) Tj T*\n"
        body += "ET"
        objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for n, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""

_PRESENTATION = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst>
<p:sldSz cx="9144000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""

_PRESENTATION_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>"""

_SLIDE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""

_SLIDE_HEAD = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld><p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr/>
<p:sp><p:nvSpPr><p:cNvPr id="2" name="Body"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm><a:off x="457200" y="457200"/><a:ext cx="8229600" cy="4114800"/></a:xfrm>
<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>
<p:txBody><a:bodyPr/><a:lstStyle/>"""

_SLIDE_TAIL = """</p:txBody></p:sp>
</p:spTree></p:cSld>
</p:sld>"""


def make_pptx(lines: list[str]) -> bytes:
    """A one-slide PPTX. Deterministic: fixed zip timestamps."""
    paras = "".join(
        '<a:p><a:r><a:rPr lang="en-US"/><a:t>'
        + line.replace("&", "&amp;").replace("<", "&lt;")
        + "</a:t></a:r></a:p>"
        for line in lines
    )
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "ppt/presentation.xml": _PRESENTATION,
        "ppt/_rels/presentation.xml.rels": _PRESENTATION_RELS,
        "ppt/slides/slide1.xml": _SLIDE_HEAD + paras + _SLIDE_TAIL,
        "ppt/slides/_rels/slide1.xml.rels": _SLIDE_RELS,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text)
    return buf.getvalue()


PDF_PAGES = [
    ["Virtual memory", "TLB", "Page fault"],
    ["Page table walk", "Multi-level tables"],
    ["Thrashing", "Working set"],
]
PPTX_LINES = ["Cache coherence", "MESI", "False sharing"]

if __name__ == "__main__":
    (HERE / "terse.pdf").write_bytes(make_pdf(PDF_PAGES))
    (HERE / "terse.pptx").write_bytes(make_pptx(PPTX_LINES))
    print("wrote terse.pdf and terse.pptx")
