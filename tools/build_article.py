"""Build the illustrated README PDF and validate its release input fingerprints."""

import argparse
import hashlib
import json
import re
import sys
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF = "docs/DALE-guide.pdf"
MANIFEST = "docs/article-build.json"


def digest(path):
    data = path.read_bytes()
    if path.suffix in (".py", ".md", ".txt"):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def version(root):
    text = (root / "src/dale/__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([\d.]+)"', text)[1]


def inputs(root):
    text = (root / "README.md").read_text(encoding="utf-8")
    names = {"README.md", "tools/build_article.py", "tools/article-requirements.txt"}
    names.update(re.findall(r'src="(docs/images/readme/[^"<>]+\.png)"', text))
    return {name: digest(root / name) for name in sorted(names)}


def interface_inputs(root):
    return {
        p.relative_to(root).as_posix(): digest(p)
        for p in sorted((root / "src/dale").rglob("*"))
        if p.is_file() and p.suffix in (".py", ".png", ".ico") and p.name != "__init__.py"
    }


def check(root=ROOT):
    record = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if record.get("format") != "dale-article-v1" or record.get("version") != version(root):
        raise ValueError("Article version is stale. Rebuild and review the release PDF.")
    if record.get("inputs") != inputs(root):
        raise ValueError("README, screenshots or renderer changed. Rebuild and review the PDF.")
    if record.get("reviewed_interface") != interface_inputs(root):
        raise ValueError("Application changed. Review/update screenshots and rebuild the PDF.")
    pdf = root / PDF
    if not pdf.read_bytes().startswith(b"%PDF-") or record.get("pdf_sha256") != digest(pdf):
        raise ValueError("Release PDF is missing, modified or invalid.")
    return record


class Node:
    def __init__(self, tag="root", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in ("img", "br", "hr", "meta", "input"):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def inline(node):
    if isinstance(node, str):
        return escape(node)
    body = "".join(inline(child) for child in node.children)
    if node.tag in ("strong", "b", "em", "i"):
        tag = "b" if node.tag in ("strong", "b") else "i"
        return f"<{tag}>{body}</{tag}>"
    if node.tag == "br":
        return "<br/>"
    if node.tag == "a" and body:
        href = node.attrs.get("href", "")
        if not href.startswith(("#", "https://", "http://")):
            href = "https://github.com/Shin0by/DALE/blob/release/" + href
        return f'<a href="{escape(href, quote=True)}" color="#176b86">{body}</a>'
    return body


def build(root, deps=None, reviewed=False):
    if deps:
        sys.path.insert(0, str(Path(deps).resolve()))
    from markdown_it import MarkdownIt
    from pypdf import PdfReader
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus.tableofcontents import TableOfContents

    old = root / MANIFEST
    if not reviewed and (
        not old.exists()
        or json.loads(old.read_text(encoding="utf-8")).get("reviewed_interface")
        != interface_inputs(root)
    ):
        raise ValueError("Review current screenshots first; then pass --screenshots-reviewed.")
    fonts = Path("C:/Windows/Fonts")
    if fonts.exists():
        names = ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")
    else:
        fonts = Path("/usr/share/fonts/truetype/dejavu")
        names = (
            "DejaVuSans.ttf",
            "DejaVuSans-Bold.ttf",
            "DejaVuSans-Oblique.ttf",
            "DejaVuSans-BoldOblique.ttf",
        )
    for label, name in zip(("Body", "Bold", "Italic", "BoldItalic"), names, strict=True):
        pdfmetrics.registerFont(TTFont(label, str(fonts / name)))
    pdfmetrics.registerFontFamily(
        "Body", normal="Body", bold="Bold", italic="Italic", boldItalic="BoldItalic"
    )
    styles = {
        "body": ParagraphStyle(
            "body",
            fontName="Body",
            fontSize=10,
            leading=14,
            spaceAfter=9,
            textColor=colors.HexColor("#243342"),
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName="Bold",
            fontSize=15,
            leading=19,
            spaceBefore=17,
            spaceAfter=10,
            keepWithNext=True,
            textColor=colors.HexColor("#176b86"),
        ),
        "sub": ParagraphStyle(
            "sub",
            fontName="Bold",
            fontSize=11,
            leading=15,
            spaceBefore=8,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "caption": ParagraphStyle(
            "caption", fontName="Body", fontSize=9, leading=12, spaceAfter=8, alignment=TA_LEFT
        ),
    }
    parser = ArticleParser()
    parser.feed(
        MarkdownIt("commonmark", {"html": True}).render(
            (root / "README.md").read_text(encoding="utf-8")
        )
    )
    width = A4[0] - 88
    headings = {}
    language = "english"
    chapter = 0
    for node in parser.root.children:
        if not isinstance(node, Node):
            continue
        if node.tag == "h2":
            language = "russian" if "Русский" in inline(node) else "english"
            chapter = 0
            headings[id(node)] = (0, language)
        elif node.tag == "details":
            summary = next(c for c in node.children if isinstance(c, Node) and c.tag == "summary")
            chapter += 1
            headings[id(summary)] = (1, f"{language}-{chapter}")

    class ArticleTemplate(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            heading = getattr(flowable, "article_heading", None)
            if heading:
                level, key = heading
                title = unescape(re.sub(r"<[^>]+>", "", flowable.text))
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(title, key, level, closed=False)
                self.notify("TOCEntry", (level, escape(title), self.page, key))

    def convert(node, available=width, depth=0):
        if isinstance(node, str):
            return [] if not node.strip() else [Paragraph(escape(node), styles["body"])]
        tag = node.tag
        if tag == "img":
            image = Image(str(root / node.attrs["src"]))
            limit = 440 if int(node.attrs.get("width", "720")) == 416 else 320
            factor = min(available / image.imageWidth, limit / image.imageHeight, 1)
            image.drawWidth, image.drawHeight = (
                image.imageWidth * factor,
                image.imageHeight * factor,
            )
            image.hAlign = "LEFT"
            return [image, Spacer(1, 8)]
        if tag == "table":
            rows = []
            pending = list(node.children)
            while pending:
                child = pending.pop(0)
                if isinstance(child, str):
                    continue
                if child.tag == "tr":
                    cells = [c for c in child.children if isinstance(c, Node) and c.tag == "td"]
                    rows.append([convert(c, available / len(cells) - 16, depth + 1) for c in cells])
                else:
                    pending[0:0] = child.children
            if not rows:
                return []
            table = Table(rows, colWidths=[available / len(rows[0])] * len(rows[0]))
            table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d7e0e5")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            return [table, Spacer(1, 10)]
        if tag in ("h1", "h2", "summary", "p", "li", "em"):
            if tag == "p" and any(isinstance(c, Node) and c.tag == "img" for c in node.children):
                return [f for c in node.children for f in convert(c, available, depth)]
            text = inline(node).strip()
            if not text:
                return []
            kind = (
                "heading"
                if tag in ("h1", "h2") or (tag == "summary" and depth <= 1)
                else ("sub" if tag == "summary" else "caption" if tag == "em" else "body")
            )
            output = [PageBreak()] if tag == "h2" and "Русский" in text else []
            paragraph = Paragraph(text, styles[kind], bulletText="-" if tag == "li" else None)
            if id(node) in headings:
                paragraph.article_heading = headings[id(node)]
            output.append(paragraph)
            return output
        if tag in ("a", "br"):
            return []
        children = [
            f
            for c in node.children
            for f in convert(c, available, depth + (1 if tag == "details" else 0))
        ]
        if tag == "details":
            return [KeepTogether(children)]
        return children

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("toc-language", fontName="Bold", fontSize=11, leading=15, spaceBefore=10),
        ParagraphStyle("toc-chapter", fontName="Body", fontSize=9, leading=13, leftIndent=12),
    ]
    story = [
        Paragraph('<a name="contents"/>Contents / Оглавление', styles["heading"]),
        Paragraph(
            '<a href="#english">English</a> / <a href="#russian">Русский</a>', styles["body"]
        ),
        toc,
        PageBreak(),
        *convert(parser.root),
    ]
    destination = root / PDF
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.pdf")
    current = version(root)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Body", 8)
        canvas.setFillColor(colors.HexColor("#536978"))
        x = 44
        for label, target in (
            (f"DALE {current} | ", None),
            ("Contents / Оглавление", "contents"),
            (" | English", "english"),
            (" / Русский", "russian"),
        ):
            canvas.drawString(x, 24, label)
            size = pdfmetrics.stringWidth(label, "Body", 8)
            if target:
                canvas.linkRect("", target, (x, 22, x + size, 33), relative=0, thickness=0)
            x += size
        canvas.drawRightString(A4[0] - 44, 24, str(doc.page))
        canvas.restoreState()

    doc = ArticleTemplate(
        str(temporary),
        pagesize=A4,
        leftMargin=44,
        rightMargin=44,
        topMargin=35,
        bottomMargin=42,
        title=f"DALE {current} - Illustrated guide",
        author="DALE",
        invariant=True,
    )
    doc.multiBuild(story, onFirstPage=footer, onLaterPages=footer)
    reader = PdfReader(temporary)
    text = "\n".join(p.extract_text() for p in reader.pages)
    for phrase in ("DA contours", "Object slices", "Thinning", "Нарезка объектов", "Прореживание"):
        if phrase not in text:
            raise ValueError(f"PDF text is missing: {phrase}")
    temporary.replace(destination)
    record = {
        "format": "dale-article-v1",
        "version": current,
        "inputs": inputs(root),
        "reviewed_interface": interface_inputs(root),
        "pdf_sha256": digest(destination),
        "pages": len(reader.pages),
    }
    old.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--deps", type=Path, help="Optional isolated documentation dependencies")
    parser.add_argument("--screenshots-reviewed", action="store_true")
    args = parser.parse_args()
    try:
        record = (
            check() if args.check else build(ROOT, args.deps, reviewed=args.screenshots_reviewed)
        )
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"Release article: {exc}") from exc
    print(f"Article {record['version']}: {record['pages']} pages, SHA256 {record['pdf_sha256']}")


if __name__ == "__main__":
    main()
