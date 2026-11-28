"""Create files: Word, PDF, Excel and PowerPoint documents, and spoken audio (an article read aloud, a podcast).

Everything is made on this computer - no text is sent anywhere, not even for audio (the local voice is used, never a
cloud voice, so long recordings cost nothing). Files land in ~/Documents/Vaelon (config `output_dir`), an existing
file is never overwritten (a number is added), and every creation can be undone.

Optional extras:  pip install "vaelon[docs]"   (python-docx, fpdf2, openpyxl, python-pptx)
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from ..security import undo
from ..security.policy import Risk, resolve_path
from .registry import tool

OPENABLE = {".docx", ".pdf", ".xlsx", ".pptx", ".wav", ".md", ".txt", ".csv", ".png", ".jpg", ".jpeg"}
MAX_AUDIO_CHARS = 20000  # about 20 minutes of speech


def out_dir(cfg) -> Path:
    """Where Vaelon puts the files it creates. Company mode: each company has its own folder inside it
    ("Companies/<name>") - one company's invoices, exports and attachments are never another's (or the owner's)."""
    raw = getattr(cfg, "output_dir", "") or str(Path.home() / "Documents" / "Vaelon")
    base = Path(raw).expanduser()
    try:
        from .. import company

        if company.enabled() and company.workspace() != company.PERSONAL:
            return base / "Companies" / (_safe_name(company.workspace_name(), "company") + "-" + company.workspace()[:4])
    except Exception:
        pass
    return base


def _safe_name(name: str, fallback: str = "vaelon") -> str:
    name = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", str(name or "").strip())  # the extension is chosen by the tool
    name = re.sub(r"[^\w .()-]+", " ", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" .")[:80]
    return name or fallback


def _save(ctx, name: str, ext: str, write, quiet: bool = False) -> str:
    """Pick a free file name inside the output folder, let `write(path)` produce the file, register undo.
    `quiet` (Vaelon's own background work, e.g. a recurring invoice): no undo entry - the user's next "undo" must
    never delete a file they did not ask for - and no file card."""
    folder = out_dir(ctx.cfg)
    stem = _safe_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    path, n = folder / f"{stem}{ext}", 2
    while True:  # claim the name atomically: two parallel tasks can never pick (and overwrite) the same file
        try:
            resolve_path(str(path), ctx.cfg.allowed_roots).open("x").close()
            break
        except FileExistsError:
            path, n = folder / f"{stem} ({n}){ext}", n + 1
    path = resolve_path(str(path), ctx.cfg.allowed_roots)
    try:
        write(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if quiet:
        return str(path)
    undo.push(f"create {path.name}", lambda: path.unlink(missing_ok=True))
    emit = ctx.extra.get("emit") if hasattr(ctx, "extra") else None
    if emit:
        emit("file", str(path))
    kb = max(1, path.stat().st_size // 1024)
    return f"created {path} ({kb} KB). Tell the user the file name; the app shows a button to open it."


# ------------------------------------------------------------------ a small Markdown reader
def blocks(md: str) -> list[tuple]:
    """Markdown -> [("h", level, text) | ("p", text) | ("ul", items) | ("ol", items) | ("code", text) | ("table", rows)]"""
    out: list[tuple] = []
    para: list[str] = []
    lines = str(md or "").replace("\r\n", "\n").split("\n")

    def flush():
        if para:
            out.append(("p", " ".join(para)))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(("code", "\n".join(code)))
        elif s.startswith("|") and s.count("|") >= 2:
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                out.append(("table", rows))
            continue
        elif re.match(r"#{1,6}\s+", s):
            flush()
            level = len(s) - len(s.lstrip("#"))
            out.append(("h", min(level, 4), s.lstrip("#").strip()))
        elif re.match(r"[-*+]\s+", s) or re.match(r"\d+[.)]\s+", s):
            flush()
            kind = "ul" if re.match(r"[-*+]\s+", s) else "ol"
            rx = r"[-*+]\s+" if kind == "ul" else r"\d+[.)]\s+"
            items = []
            while i < len(lines) and re.match(rx, lines[i].strip()):
                items.append(re.sub("^" + rx, "", lines[i].strip()))
                i += 1
            out.append((kind, items))
            continue
        elif re.fullmatch(r"[-*_]{3,}", s) or not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return out


_INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|`[^`]+`|\*[^*\s][^*]*\*)")


def runs(text: str) -> list[tuple[str, str]]:
    """Inline Markdown -> [(text, style)] with style "" | "b" | "i" | "code". Links become "label (address)"."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", str(text))
    out = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if (part.startswith("**") and part.endswith("**")) or (part.startswith("__") and part.endswith("__")):
            out.append((part[2:-2], "b"))
        elif part.startswith("`") and part.endswith("`"):
            out.append((part[1:-1], "code"))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append((part[1:-1], "i"))
        else:
            out.append((part, ""))
    return out


def plain(text: str) -> str:
    return "".join(t for t, _ in runs(text))


# ------------------------------------------------------------------ documents
def _docx(path: Path, title: str, body: list[tuple]) -> None:
    try:
        import docx
        from docx.shared import Pt
    except ImportError:
        raise RuntimeError('Word files need: pip install "vaelon[docs]"')
    doc = docx.Document()
    doc.core_properties.title = title
    doc.add_heading(title, 0)

    def fill(par, text):
        for t, style in runs(text):
            r = par.add_run(t)
            r.bold = style == "b" or None
            r.italic = style == "i" or None
            if style == "code":
                r.font.name = "Consolas"

    for b in body:
        if b[0] == "h":
            doc.add_heading(plain(b[2]), b[1])
        elif b[0] == "p":
            fill(doc.add_paragraph(), b[1])
        elif b[0] in ("ul", "ol"):
            for item in b[1]:
                fill(doc.add_paragraph(style="List Bullet" if b[0] == "ul" else "List Number"), item)
        elif b[0] == "code":
            r = doc.add_paragraph().add_run(b[1])
            r.font.name, r.font.size = "Consolas", Pt(9.5)
        elif b[0] == "table":
            cols = max(len(r) for r in b[1])
            table = doc.add_table(rows=len(b[1]), cols=cols)
            table.style = "Light Grid Accent 1"
            for ri, row in enumerate(b[1]):
                for ci in range(cols):
                    cell = table.cell(ri, ci)
                    cell.text = ""
                    fill(cell.paragraphs[0], row[ci] if ci < len(row) else "")
                    if ri == 0:
                        for r in cell.paragraphs[0].runs:
                            r.bold = True
            doc.add_paragraph()
    doc.save(str(path))


def _pdf_fonts(pdf) -> tuple[str, str]:
    """Register Unicode fonts (Cyrillic must work). Returns (text family, monospace family)."""
    win = Path(r"C:\Windows\Fonts")
    sets = [
        (win, {"": "arial.ttf", "B": "arialbd.ttf", "I": "ariali.ttf", "BI": "arialbi.ttf"}, "consola.ttf"),
        (win, {"": "segoeui.ttf", "B": "segoeuib.ttf", "I": "segoeuii.ttf", "BI": "segoeuiz.ttf"}, "consola.ttf"),
        (Path("/usr/share/fonts/truetype/dejavu"), {"": "DejaVuSans.ttf", "B": "DejaVuSans-Bold.ttf",
                                                    "I": "DejaVuSans-Oblique.ttf", "BI": "DejaVuSans-BoldOblique.ttf"},
         "DejaVuSansMono.ttf"),
        (Path("/System/Library/Fonts/Supplemental"), {"": "Arial.ttf", "B": "Arial Bold.ttf", "I": "Arial Italic.ttf",
                                                      "BI": "Arial Bold Italic.ttf"}, "Courier New.ttf"),  # macOS
        (Path("/Library/Fonts"), {"": "Arial Unicode.ttf", "B": "Arial Unicode.ttf", "I": "Arial Unicode.ttf",
                                  "BI": "Arial Unicode.ttf"}, "Arial Unicode.ttf"),
    ]
    for folder, faces, mono in sets:
        if all((folder / f).exists() for f in faces.values()):
            for style, f in faces.items():
                pdf.add_font("Body", style, str(folder / f))
            if (folder / mono).exists():
                pdf.add_font("Mono", "", str(folder / mono))
                return "Body", "Mono"
            return "Body", "Body"
    return "Helvetica", "Courier"  # built-in fonts: Latin letters only


def _pdf(path: Path, title: str, body: list[tuple]) -> None:
    try:
        import logging

        logging.getLogger("fontTools").setLevel(logging.ERROR)  # it reports every unused font table
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError('PDF files need: pip install "vaelon[docs]"')
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, 18)
    pdf.set_title(title)
    pdf.set_creator("Vaelon")
    fam, mono = _pdf_fonts(pdf)
    latin = fam == "Helvetica"

    def fix(text: str) -> str:
        text = text.replace("\u2011", "-").replace("\u202f", " ").replace("\u00a0", " ")
        return text.encode("latin-1", "replace").decode("latin-1") if latin else text

    def write(text: str, size: float = 11, indent: float = 0):
        pdf.set_left_margin(20 + indent)
        pdf.set_x(20 + indent)
        for t, style in runs(text):
            if style == "code":
                pdf.set_font(mono, "", size - 1)
            else:
                pdf.set_font(fam, {"b": "B", "i": "I"}.get(style, ""), size)
            pdf.write(size * 0.52, fix(t))
        pdf.ln(size * 0.52 + 2.5)
        pdf.set_left_margin(20)

    pdf.add_page()
    pdf.set_font(fam, "B", 20)
    pdf.multi_cell(0, 9, fix(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(255, 122, 31)
    pdf.set_line_width(0.6)
    pdf.line(20, pdf.get_y() + 1.5, 190, pdf.get_y() + 1.5)
    pdf.ln(6)
    pdf.set_draw_color(170, 170, 170)  # table borders: thin and grey
    pdf.set_line_width(0.2)
    for b in body:
        if b[0] == "h":
            pdf.ln(2)
            pdf.set_font(fam, "B", {1: 16, 2: 14, 3: 12.5}.get(b[1], 11.5))
            pdf.multi_cell(0, 7, fix(plain(b[2])), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif b[0] == "p":
            write(b[1])
        elif b[0] in ("ul", "ol"):
            for n, item in enumerate(b[1], 1):
                write(("- " if b[0] == "ul" else f"{n}. ") + item, indent=5)
        elif b[0] == "code":
            pdf.set_font(mono, "", 9)
            pdf.set_fill_color(244, 244, 244)
            pdf.multi_cell(0, 4.6, fix(b[1]), fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
        elif b[0] == "table":
            cols = max(len(r) for r in b[1])
            pdf.set_font(fam, "", 9.5)
            with pdf.table(line_height=5.2, padding=1.5) as table:
                for row in b[1]:
                    r = table.row()
                    for ci in range(cols):
                        r.cell(fix(plain(row[ci])) if ci < len(row) else "")
            pdf.ln(4)
    pdf.output(str(path))


@tool("create_document",
      "Create a document FILE from Markdown text: a report, letter, CV, notes, plan. format: docx (Word), pdf, md or txt. "
      "Write the full content yourself (headings, lists, tables are supported).",
      {"title": "document title (also the file name)", "content": "the full text in Markdown",
       "?format": "docx | pdf | md | txt (default docx)"},
      risk=Risk.REVERSIBLE, group="create",
      summary=lambda a: f"create document '{a.get('title')}' ({a.get('format') or 'docx'}, {len(str(a.get('content', '')))} chars)")
def create_document(ctx, title, content, format="docx"):
    fmt = str(format or "docx").lower().strip(". ")
    fmt = {"word": "docx", "doc": "docx", "markdown": "md", "text": "txt"}.get(fmt, fmt)
    if fmt not in ("docx", "pdf", "md", "txt"):
        return "ERROR: format must be docx, pdf, md or txt"
    title = str(title or "Document").strip()
    body = blocks(content)
    if body and body[0][0] == "h" and plain(body[0][2]).strip().lower() == title.lower():
        body = body[1:]  # the title is written once
    if fmt == "docx":
        return _save(ctx, title, ".docx", lambda p: _docx(p, title, body))
    if fmt == "pdf":
        return _save(ctx, title, ".pdf", lambda p: _pdf(p, title, body))
    text = str(content) if fmt == "md" else "\n".join(plain(line) for line in str(content).split("\n"))
    return _save(ctx, title, "." + fmt, lambda p: p.write_text(text, "utf-8"))


def _num(s):
    """'1 234,56 €' -> 1234.56, '12%' -> 0.12 (kind 'pct'), '2026-11-20' / '20.11.2026' -> a date. (value, kind)."""
    from datetime import date as _date, datetime as _datetime

    if not isinstance(s, str):
        return s, "num" if isinstance(s, (int, float)) else "text"
    t = s.strip().replace(" ", " ")
    digits = re.sub(r"[\s-]", "", t)
    if re.fullmatch(r"\+?\d+", digits) and (digits.startswith(("0", "+")) and len(digits) > 1 or len(digits) >= 10):
        return s, "text"  # a phone number, an ID, an invoice number: never a sum (a leading 0 is kept)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return _datetime.strptime(t, fmt).date(), "date"
        except ValueError:
            pass
    pct = t.endswith("%")
    money = bool(re.search(r"[€$£]|\b(?:eur|евро|usd|gbp)\b", t, re.I))
    core = re.sub(r"(?i)[€$£%]|\b(?:eur|евро|usd|gbp)\b", "", t).strip().replace(" ", "")
    if not re.fullmatch(r"[-+]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?", core):
        return s, "text"
    if "," in core and "." in core:  # both: the last one is the decimal separator
        core = core.replace(".", "").replace(",", ".") if core.rfind(",") > core.rfind(".") else core.replace(",", "")
    else:  # the same rule as bills.cents: several separators, or 3 digits after one (and not "0,125"), are thousands
        sep = "," if "," in core else "." if "." in core else ""
        if sep:
            whole, _, frac = core.rpartition(sep)
            if core.count(sep) > 1 or (len(frac) == 3 and whole.lstrip("+-") not in ("", "0")):
                core = core.replace(sep, "")
            else:
                core = core.replace(sep, ".")
    v = float(core)
    if pct:
        return v / 100, "pct"
    if v.is_integer() and not money and "." not in core:
        return int(v), "int"
    return v, "money" if money else "num"


def _rows(data: str) -> list[list]:
    """A Markdown table, or lines separated by tabs / semicolons / commas -> rows of text (numbers are read later)."""
    rows: list[list[str]] = []
    for b in blocks(data):
        if b[0] == "table":
            rows += [[plain(c) for c in r] for r in b[1]]
    if not rows:
        import csv
        import io

        lines = [x for x in str(data).splitlines() if x.strip()]
        sample = "\n".join(lines[:5])
        sep = "\t" if "\t" in sample else ";" if sample.count(";") > sample.count(",") else ","
        rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO("\n".join(lines)), delimiter=sep)]
    return rows


MONEY_HEAD = re.compile(r"(?i)price|amount|cost|total|sum|budget|salary|revenue|income|expense|paid|balance|value|fee|"
                        r"цена|сума|стойност|общо|бюджет|заплата|приход|разход|платен|баланс|такса|€|eur|евро")
PCT_HEAD = re.compile(r"(?i)%|percent|share|rate|процент|дял")
TOTAL_ROW = re.compile(r"(?i)^\s*(?:total|grand total|sum|общо|всичко|сума)\b")

# one calm palette for every file Vaelon makes: dark slate + a single warm accent, lots of white
INK, ACCENT, SOFT, LINE, BAND = "1F2A37", "C2571A", "6B7280", "D9DEE5", "F4F6F8"


@tool("create_spreadsheet",
      "Create an Excel FILE (.xlsx) from rows: a Markdown table, or lines with comma/semicolon/tab separated cells. "
      "The first row is the header. It is laid out like a real template: a title, a formatted table with filters, "
      "money / % / dates formatted, a totals row and a chart when they make sense.",
      {"title": "sheet title (also the file name)", "rows": "the table as text",
       "?chart": "auto (default), column, bar, line, pie or none", "?subtitle": "one line under the title"},
      risk=Risk.REVERSIBLE, group="create", summary=lambda a: f"create spreadsheet '{a.get('title')}'")
def create_spreadsheet(ctx, title, rows, chart="auto", subtitle=""):
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise RuntimeError('Excel files need: pip install "vaelon[docs]"')
    data = _rows(rows)
    if len(data) < 1 or not any(data):
        return "ERROR: no rows given"
    title = str(title or "Sheet").strip()
    return _save(ctx, title, ".xlsx", lambda p: write_table_xlsx(p, title, data, str(chart or "auto"), str(subtitle or "")))


def write_table_xlsx(path: Path, title: str, data: list[list], chart: str = "auto", subtitle: str = "") -> None:
    import openpyxl
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    head = [str(h).strip() or f"Column {n + 1}" for n, h in enumerate(data[0])]
    width = len(head)
    body = [list(r) + [""] * (width - len(r)) for r in data[1:]]
    body = [r[:width] for r in body if any(str(c).strip() for c in r)]
    total_given = bool(body) and bool(TOTAL_ROW.match(str(body[-1][0])))
    if total_given:
        body = body[:-1]  # a totals row is written below with real formulas instead
    body = [[re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", c) if isinstance(c, str) else c for c in r] for r in body]
    ident = [bool(re.search(r"(?i)phone|tel|mobile|\bid\b|№|number|\bno\.?$|номер|еик|егн|iban|zip|postal|код|code|year|година",
                            h)) for h in head]
    parsed = [[(c, "text") if ident[ci] else _num(c) for ci, c in enumerate(r)] for r in body]
    kinds = []
    for ci in range(width):
        ks = {k for r in parsed for v, k in [r[ci]] if str(v).strip() not in ("", "-", "—")}
        if ks and ks <= {"int", "num", "money"}:  # a column of numbers: money wins, then decimals, then whole numbers
            kind = "money" if "money" in ks else "num" if "num" in ks else "int"
        else:
            kind = ks.pop() if len(ks) == 1 else "text"
        if kind in ("int", "num") and MONEY_HEAD.search(head[ci]):
            kind = "money"
        if kind == "num" and PCT_HEAD.search(head[ci]) and all(0 <= (r[ci][0] or 0) <= 1 for r in parsed if r[ci][1] != "text"):
            kind = "pct"
        kinds.append(kind)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]:*?/\\]", " ", title)[:31] or "Sheet"
    ws.sheet_view.showGridLines = False
    thin = Side(style="thin", color=LINE)
    ws["A1"] = title
    ws["A1"].font = Font(size=20, bold=True, color=INK)
    ws["A2"] = subtitle or time.strftime("%d.%m.%Y")
    for c in (ws["A1"], ws["A2"]):
        if isinstance(c.value, str) and c.value[:1] in ("=", "+", "-", "@"):
            c.data_type = "s"  # a title that looks like a formula stays text
    ws["A2"].font = Font(size=10, color=SOFT)
    ws.row_dimensions[1].height = 30
    top = 4
    ws.append([])
    for ci, h in enumerate(head, 1):
        c = ws.cell(row=top, column=ci, value=h)
        if h[:1] in ("=", "+", "-", "@"):
            c.data_type = "s"
        c.font = Font(bold=True, color="FFFFFF")
        c.alignment = Alignment(horizontal="right" if kinds[ci - 1] in ("money", "num", "int", "pct") else "left", vertical="center")
    fmt = {"money": '#,##0.00 "€"', "num": "#,##0.00", "int": "#,##0", "pct": "0%", "date": "dd.mm.yyyy"}
    for ri, r in enumerate(parsed, top + 1):
        for ci, (v, k) in enumerate(r, 1):
            c = ws.cell(row=ri, column=ci, value=(None if v == "" else v))
            if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and k == "text":
                c.data_type = "s"  # text that looks like a formula stays text
            if kinds[ci - 1] in fmt and k != "text":
                c.number_format = fmt[kinds[ci - 1]]
            c.alignment = Alignment(vertical="center", wrap_text=k == "text" and len(str(v)) > 40)
    last = top + len(parsed)
    ref = f"A{top}:{get_column_letter(width)}{max(last, top + 1)}"
    if not parsed:
        ws.cell(row=top + 1, column=1, value="")
    table = Table(displayName=re.sub(r"\W", "_", "T_" + ws.title)[:30] or "T_1", ref=ref)
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(table)
    sums = [ci for ci, k in enumerate(kinds, 1) if k in ("money", "num", "int")]
    if sums and len(parsed) >= 2 and kinds[0] == "text":
        tr = last + 1
        lab = ws.cell(row=tr, column=1, value="Общо" if re.search(r"[а-яА-Я]", "".join(head)) else "Total")
        lab.font = Font(bold=True, color=INK)
        for ci in range(1, width + 1):
            ws.cell(row=tr, column=ci).border = Border(top=Side(style="medium", color=INK))
        for ci in sums:
            col = get_column_letter(ci)
            c = ws.cell(row=tr, column=ci, value=f"=SUM({col}{top + 1}:{col}{last})")
            c.font = Font(bold=True, color=INK)
            c.number_format = fmt[kinds[ci - 1]]
    for ci in range(1, width + 1):
        values = [head[ci - 1]] + [r[ci - 1][0] for r in parsed]
        longest = max(len(f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in values)
        ws.column_dimensions[get_column_letter(ci)].width = min(48, max(10, longest + 3))
    ws.freeze_panes = f"A{top + 1}"
    ws.print_title_rows = f"{top}:{top}"
    ws.page_setup.orientation = "landscape" if width > 5 else "portrait"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.oddFooter.center.text = "&P / &N"
    ws.oddFooter.left.text = title
    # a chart, when there is a label column and 1-4 number columns and not too many rows
    want = chart.lower().strip()
    # a difference column ("Разлика", "Variance") goes below zero and says nothing a chart of the others does not
    nums = [ci for ci, k in enumerate(kinds, 1) if k in ("money", "num", "int", "pct")
            and not re.search(r"(?i)разлик|остатък|difference|variance|delta|change|промяна", head[ci - 1])]
    if want != "none" and kinds[0] in ("text", "date") and nums and 2 <= len(parsed) <= 24 and (want != "auto" or len(nums) <= 4):
        if want == "auto":
            long_labels = max(len(str(r[0][0])) for r in parsed) > 10  # long names read better on horizontal bars
            want = "pie" if len(nums) == 1 and len(parsed) <= 6 and PCT_HEAD.search(head[nums[0] - 1]) else \
                "bar" if long_labels and kinds[0] == "text" else \
                "line" if kinds[0] == "date" else "column"
        ch = {"pie": PieChart, "line": LineChart, "bar": BarChart, "column": BarChart}.get(want, BarChart)()
        if want == "bar":
            ch.type = "bar"
        elif want == "column":
            ch.type = "col"
        ch.title = title
        ch.height, ch.width = (max(7.5, 1.0 * len(parsed) + 2.5), 16) if want == "bar" else (7.5, 15)
        if want == "bar":
            ch.x_axis.scaling.orientation = "maxMin"  # the first row on top, as in the table
        cats = Reference(ws, min_col=1, min_row=top + 1, max_row=last)
        for ci in (nums[:1] if want == "pie" else nums[:4]):
            ch.add_data(Reference(ws, min_col=ci, min_row=top, max_row=last), titles_from_data=True)
        ch.set_categories(cats)
        if want != "pie":
            # openpyxl 3.1 marks both axes as deleted: Excel then shows no labels and no values at all
            ch.x_axis.delete = False
            ch.y_axis.delete = False
            ch.y_axis.majorGridlines = None if want == "bar" else ch.y_axis.majorGridlines
            ch.y_axis.numFmt = fmt.get(kinds[nums[0] - 1], "General")
            ch.gapWidth = 60
            if len(nums) > 1:
                ch.legend.position = "b"
            else:
                ch.legend = None
        ws.add_chart(ch, f"{get_column_letter(width + 2)}{top}")
    wb.properties.creator = "Vaelon"
    wb.save(str(path))


def _slides(text: str) -> list[dict]:
    """'# Title' starts a slide; '- point' lines are its bullets; 'Notes: ...' goes to the speaker notes."""
    slides: list[dict] = []
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if not s or re.fullmatch(r"[-*_]{3,}", s):
            continue
        if s.startswith("#"):
            slides.append({"title": plain(s.lstrip("#").strip()), "points": [], "notes": ""})
            continue
        if not slides:
            slides.append({"title": plain(s), "points": [], "notes": ""})
            continue
        m = re.match(r"(?i)(notes?|бележк[аи])\s*:\s*(.*)", s)
        if m:
            slides[-1]["notes"] += m.group(2) + " "
        else:
            slides[-1]["points"].append(plain(re.sub(r"^([-*+]|\d+[.)])\s+", "", s)))
    return slides


# "90% - cheaper panels", "6-8 г. - payback", "25 years: warranty" -> a big number and its line (a dash or colon must
# follow the number, so an ordinary sentence that starts with a number stays a bullet)
STAT_RX = re.compile(r"^\s*([+-]?\d[\d.,]*(?:\s*[-–]\s*\d[\d.,]*)?\s*(?:%|€|\$|x|×|k|m|bn|млн\.?|млрд\.?|хил\.?|г\.|години|"
                     r"месеца|дни|years?|months?|days?|hours?|часа)?)\s*[-–:—]\s+(.{3,})$", re.I)


@tool("create_presentation",
      "Create a PowerPoint FILE (.pptx). Give the slides as text: a line starting with '# ' is a slide title, lines "
      "starting with '- ' are its points (3-6 short ones), 'Notes: ...' adds speaker notes. A slide whose points start "
      "with a number ('42% - of users ...') becomes a big-number slide. Write like a person: short points, no filler.",
      {"title": "presentation title (also the file name)", "slides": "the slides as text", "?subtitle": "under the title"},
      risk=Risk.REVERSIBLE, group="create", summary=lambda a: f"create presentation '{a.get('title')}'")
def create_presentation(ctx, title, slides, subtitle=""):
    try:
        import pptx  # noqa: F401
    except ImportError:
        raise RuntimeError('PowerPoint files need: pip install "vaelon[docs]"')
    deck = _slides(slides)
    if not deck:
        return "ERROR: no slides given"
    title = str(title or "Presentation").strip()
    return _save(ctx, title, ".pptx", lambda p: write_deck(p, title, deck, str(subtitle or "")))


def write_deck(path: Path, title: str, deck: list[dict], subtitle: str = "") -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    rgb = lambda h: RGBColor.from_string(h)  # noqa: E731
    FONT = "Segoe UI"
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    W = 13.333

    def box(slide, x, y, w, h, fill=None):
        shape = slide.shapes.add_shape(1, Inches(x), Inches(y), Inches(w), Inches(h))
        shape.line.fill.background()
        if fill:
            shape.fill.solid()
            shape.fill.fore_color.rgb = rgb(fill)
        else:
            shape.fill.background()
        shape.shadow.inherit = False
        return shape

    def text(slide, x, y, w, h, value, size, bold=False, color=INK, align=None, anchor=None, spacing=None):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Emu(0)
        if anchor:
            tf.vertical_anchor = anchor
        p = tf.paragraphs[0]
        if align:
            p.alignment = align
        if spacing:
            p.line_spacing = spacing
        r = p.add_run()
        r.text = value
        f = r.font
        f.size, f.bold, f.name, f.color.rgb = Pt(size), bold, FONT, rgb(color)
        return tf

    def bullets(slide, x, y, w, h, points, size):
        tf = text(slide, x, y, w, h, "", size)
        tf.paragraphs[0].runs[0].text = ""
        for n, pt in enumerate(points):
            p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
            p.line_spacing = 1.12
            p.space_after = Pt(size * 0.55)
            dot = p.add_run() if n else p.runs[0]
            dot.text = "▪  "  # a small square: quieter than a round bullet
            dot.font.size, dot.font.name, dot.font.color.rgb = Pt(size * 0.8), FONT, rgb(ACCENT)
            r = p.add_run()
            head, sep, rest = pt.partition(": ")
            if sep and len(head) <= 32:  # "Speed: 3x faster" -> the label in bold
                r.text = head + ": "
                r.font.bold = True
                r.font.size, r.font.name, r.font.color.rgb = Pt(size), FONT, rgb(INK)
                r = p.add_run()
                pt = rest
            r.text = pt
            r.font.size, r.font.name, r.font.color.rgb = Pt(size), FONT, rgb(INK)

    def frame(slide, n, heading):
        box(slide, 0, 0, 0.16, 7.5, ACCENT)
        text(slide, 0.85, 0.55, 11.6, 1.0, heading, 30, True, INK, anchor=MSO_ANCHOR.BOTTOM)
        box(slide, 0.85, 1.62, 11.6, 0.02, LINE)
        text(slide, 0.85, 6.95, 9.5, 0.35, title, 10, False, SOFT)
        text(slide, 11.45, 6.95, 1.0, 0.35, str(n), 10, False, SOFT, align=PP_ALIGN.RIGHT)

    # the cover: dark, one accent line, the title large
    cover = prs.slides.add_slide(blank)
    box(cover, 0, 0, W, 7.5, INK)
    box(cover, 0.9, 3.15, 1.1, 0.07, ACCENT)
    text(cover, 0.9, 1.4, 11.2, 1.7, title, 46, True, "FFFFFF", anchor=MSO_ANCHOR.BOTTOM)
    text(cover, 0.9, 3.45, 11.2, 0.6, subtitle or time.strftime("%d.%m.%Y"), 18, False, "C9D1DB")
    n = 1
    content = [s for s in deck if s["points"] or s["title"]]
    if len(content) >= 5:  # an agenda slide for longer decks
        n += 1
        ag = prs.slides.add_slide(blank)
        frame(ag, n, "Съдържание" if re.search(r"[а-яА-Я]", title) else "Agenda")
        for k, s in enumerate(content[:8]):
            y = 2.0 + k * 0.6
            text(ag, 0.85, y, 0.7, 0.5, f"{k + 1:02d}", 18, True, ACCENT)
            text(ag, 1.6, y, 10.5, 0.5, s["title"], 20, False, INK)
    for sl in deck:
        pts = sl["points"]
        stats = [STAT_RX.match(p) for p in pts]
        if pts and len(pts) <= 3 and all(stats):  # big numbers
            n += 1
            s = prs.slides.add_slide(blank)
            frame(s, n, sl["title"])
            colw = 11.6 / len(pts)
            for k, m in enumerate(stats):
                x = 0.85 + k * colw
                text(s, x, 2.3, colw - 0.4, 1.5, m.group(1).strip(), 60, True, ACCENT)
                text(s, x, 3.65, colw - 0.4, 1.8, m.group(2).strip(), 18, False, INK, spacing=1.1)
        else:
            short = pts and len(pts) >= 6 and max(len(p) for p in pts) <= 48
            chunks = [pts] if short and len(pts) <= 12 else ([pts[i:i + 6] for i in range(0, len(pts), 6)] or [[]])
            for part, chunk in enumerate(chunks):
                n += 1
                s = prs.slides.add_slide(blank)
                frame(s, n, sl["title"] + (" (2)" if part == 1 else f" ({part + 1})" if part else ""))
                chars = sum(len(p) for p in chunk)
                size = 26 if chars < 170 else 22 if chars < 260 else 19 if chars < 420 else 16  # few words: larger
                if short and len(chunk) >= 6:
                    half = (len(chunk) + 1) // 2
                    bullets(s, 0.85, 2.0, 5.6, 4.7, chunk[:half], 20)
                    bullets(s, 6.85, 2.0, 5.6, 4.7, chunk[half:], 20)
                elif chunk:
                    bullets(s, 0.85, 2.0, 11.6, 4.7, chunk, size)
                if sl["notes"].strip() and not part:
                    s.notes_slide.notes_text_frame.text = sl["notes"].strip()
    prs.core_properties.author = "Vaelon"
    prs.core_properties.title = title
    prs.save(str(path))


# ------------------------------------------------------------------ audio
def _speech_parts(text: str) -> list[tuple[int, str]]:
    """[(speaker 0/1, text)]. Lines starting with 'A:', 'B:', 'Host:', 'Guest:' (any two names) switch the voice."""
    parts: list[tuple[int, str]] = []
    names: list[str] = []
    raw: list[str] = []
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        s = plain(line.strip().lstrip("#>-* ").strip())
        if not s:
            continue
        raw.append(s)
        m = re.match(r"([A-Za-zА-Яа-я][\w ]{0,18}?)\s*:\s+(.+)", s)
        who = parts[-1][0] if parts else 0
        if m and (m.group(1).lower() in names or len(names) < 2) and len(m.group(1).split()) <= 2:
            key = m.group(1).lower()
            if key not in names:
                names.append(key)
            who, s = names.index(key), m.group(2)
        if parts and parts[-1][0] == who:
            parts[-1] = (who, parts[-1][1] + " " + s)
        else:
            parts.append((who, s))
    if len(names) == 2:
        return parts
    return [(0, " ".join(raw))] if raw else []  # one voice: every line is read exactly as written


def _chunks(text: str, limit: int = 280) -> list[str]:
    out, cur = [], ""
    for sentence in re.findall(r"[^.!?…]+[.!?…]*\s*", text) or [text]:
        if cur and len(cur) + len(sentence) > limit:
            out.append(cur.strip())
            cur = ""
        cur += sentence
    if cur.strip():
        out.append(cur.strip())
    return out


VOICES = ({"pitch": 1.0, "speed": 1.0}, {"pitch": 0.86, "speed": 1.04})  # speaker B: the same voice, lower


def synth_audio(text: str, on_progress=None):
    """(samples, rate) of `text` spoken with the local voice. Two speakers if the text is a dialogue."""
    import numpy as np

    from .. import tts

    parts = _speech_parts(text)
    if not parts:
        raise ValueError("no text to speak")
    jobs = [(who, c) for who, body in parts for c in _chunks(body)]
    audio, rate = [], 22050
    last_who = None
    import tempfile

    for n, (who, chunk) in enumerate(jobs, 1):
        lang = tts.detect_lang(chunk)
        v = tts.normalize({"preset": "clean", **VOICES[who]})
        if tts._piper_ready(lang):
            wav = tts._piper(chunk, lang, length_scale=v["pitch"] / max(v["speed"], 0.1))
        elif sys.platform == "win32":
            with tempfile.TemporaryDirectory() as td:
                wav = tts._sapi(chunk, lang, Path(td))
        else:
            raise RuntimeError("no local voice installed: run  vaelon voice-setup")
        x, r = tts._read_wav(wav)
        if x is None:
            continue
        if abs(v["pitch"] - 1.0) > 0.01:
            x = tts.design(x, r, v)
        if not audio:
            rate = r
        elif r != rate:
            x = np.interp(np.arange(0, len(x), r / rate), np.arange(len(x)), x).astype(np.float32)
        if last_who is not None:
            audio.append(np.zeros(int(rate * (0.45 if who != last_who else 0.18)), np.float32))
        audio.append(x.astype(np.float32))
        last_who = who
        if on_progress:
            on_progress(n, len(jobs))
    if not audio:
        raise RuntimeError("the voice produced no sound")
    return np.concatenate(audio), rate


@tool("create_audio",
      "Create a spoken AUDIO FILE (.wav) with the local voice: an article or story read aloud, or a podcast - for a "
      "two-voice podcast start every line with the speaker's name, e.g. 'Anna: ...' and 'Ben: ...'. Write the full text.",
      {"title": "title (also the file name)", "text": "everything that should be said"},
      risk=Risk.REVERSIBLE, group="create",
      summary=lambda a: f"create audio '{a.get('title')}' ({len(str(a.get('text', '')))} chars, local voice)")
def create_audio(ctx, title, text):
    text = str(text or "")
    if len(text) > MAX_AUDIO_CHARS:
        return f"ERROR: text too long ({len(text)} chars; the limit is {MAX_AUDIO_CHARS}, about 20 minutes)"
    from .. import tts

    emit = ctx.extra.get("emit") if hasattr(ctx, "extra") else None
    samples, rate = synth_audio(text, (lambda n, total: emit("detail", f"speaking part {n} of {total}")) if emit else None)
    seconds = len(samples) / rate
    out = _save(ctx, str(title or "Audio"), ".wav", lambda p: p.write_bytes(tts._write_wav(samples, rate)))
    return out + f" Length: {int(seconds // 60)} min {int(seconds % 60)} s."
