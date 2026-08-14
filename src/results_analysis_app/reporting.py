from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import time
from typing import Any

from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from results_analysis_app import resonance_checks, sustained_sdpf
from results_analysis_app.envelope_rows import nearest_rows, row_value
from results_analysis_app.excel import EXCEL_AUTOMATION_ERRORS, excel_app
from results_analysis_app.models import ScopeEntry
from results_analysis_app.project_config import DEFAULT_EVENT_TIMES
from pscad_plotter_app_v3.services.project_conventions import KNOWN_FAULT_LABELS


IMAGE_WIDTH_CM = 15.92
REPORT_HEADING_GREEN = RGBColor(112, 155, 50)
BUS_VOLTAGE_SLICER_SOURCE_TEXT = "Bus voltage [kV]"
BUS_VOLTAGE_SLICER_VALUE_OVERRIDES = {"22": "23"}
DASHBOARD_FILTER_SETTLE_S = 0.8
DASHBOARD_REPORT_TITLE_ORDER = {
    "initial voltages": 0,
    "initial reactive power": 1,
    "initial active power": 2,
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"
WORD_2012_NAMESPACE = "http://schemas.microsoft.com/office/word/2012/wordml"
WORD_2016_CID_NAMESPACE = "http://schemas.microsoft.com/office/word/2016/wordml/cid"

LogFn = Callable[[str], None]
CancelFn = Callable[[], None]


def _cancel(check_cancel: CancelFn | None) -> None:
    if check_cancel is not None:
        check_cancel()


@dataclass(frozen=True)
class EnvelopeSummaryRow:
    event: str
    measurement: str
    time_s: float
    peak_kv: float
    rms_kv: float


@dataclass(frozen=True)
class FigureReference:
    bookmark: str
    fallback_label: str


def _configure_report_styles(doc) -> None:
    """Apply the report typography without depending on a Word template."""
    styles = doc.styles

    normal = styles["Normal"]
    normal.font.name = "Calibri Light"
    normal.font.size = Pt(12)

    body = styles["Body Text"]
    body.font.name = "Calibri Light"
    body.font.size = Pt(12)
    body.paragraph_format.space_before = Pt(12)
    body.paragraph_format.space_after = Pt(6)
    body.paragraph_format.line_spacing = 1.2
    body.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    body.next_paragraph_style = body

    heading_1 = styles["Heading 1"]
    heading_1.font.name = "Calibri"
    heading_1.font.size = Pt(20)
    heading_1.font.bold = None
    heading_1.font.color.rgb = REPORT_HEADING_GREEN
    heading_1.paragraph_format.space_before = Pt(8)
    heading_1.paragraph_format.space_after = Pt(12)
    heading_1.paragraph_format.keep_with_next = True
    heading_1.paragraph_format.keep_together = True
    heading_1.next_paragraph_style = body

    heading_2 = styles["Heading 2"]
    heading_2.font.name = "Calibri Light"
    heading_2.font.size = Pt(16)
    heading_2.font.bold = None
    heading_2.font.color.rgb = REPORT_HEADING_GREEN
    heading_2.paragraph_format.space_before = Pt(18)
    heading_2.paragraph_format.space_after = Pt(6)
    heading_2.paragraph_format.keep_with_next = True
    heading_2.paragraph_format.keep_together = True
    heading_2.next_paragraph_style = body

    heading_3 = styles["Heading 3"]
    heading_3.font.name = "Calibri Light"
    heading_3.font.size = Pt(14)
    heading_3.font.bold = None
    heading_3.font.color.rgb = REPORT_HEADING_GREEN
    heading_3.paragraph_format.space_before = Pt(14)
    heading_3.paragraph_format.space_after = Pt(6)
    heading_3.paragraph_format.keep_with_next = True
    heading_3.paragraph_format.keep_together = True
    heading_3.next_paragraph_style = body

    caption = styles["Caption"]
    caption.font.name = "Calibri Light"
    caption.font.size = Pt(12)
    caption.font.bold = None
    caption.font.italic = True
    caption.font.color.rgb = REPORT_HEADING_GREEN
    caption.paragraph_format.space_before = Pt(12)
    caption.paragraph_format.space_after = Pt(14)
    caption.paragraph_format.line_spacing = 1.2
    caption.next_paragraph_style = styles["Normal"]

    bullet_style = styles["List Bullet"]
    bullet_style.base_style = normal
    bullet_style.next_paragraph_style = body
    bullet_style.font.name = "Calibri Light"
    bullet_style.font.size = Pt(12)
    bullet_style.paragraph_format.space_before = Pt(0)
    bullet_style.paragraph_format.space_after = Pt(0)
    bullet_style.paragraph_format.line_spacing = Pt(20)
    bullet_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    header = styles["Header"]
    header.font.name = "Calibri"
    header.font.size = Pt(10)
    header.font.bold = True
    header.font.color.rgb = REPORT_HEADING_GREEN

    footer = styles["Footer"]
    footer.font.name = "Arial"
    footer.font.size = Pt(10)

    try:
        plot_heading = styles["Plot Heading"]
    except KeyError:
        plot_heading = styles.add_style("Plot Heading", WD_STYLE_TYPE.PARAGRAPH)
    plot_heading.base_style = body
    plot_heading.next_paragraph_style = body
    plot_heading.font.name = "Calibri Light"
    plot_heading.font.size = Pt(14)
    plot_heading.font.color.rgb = REPORT_HEADING_GREEN
    plot_heading.paragraph_format.space_before = Pt(14)
    plot_heading.paragraph_format.space_after = Pt(6)
    plot_heading.paragraph_format.keep_with_next = True
    plot_heading.paragraph_format.keep_together = True
    outline_level = plot_heading._element.get_or_add_pPr().find(qn("w:outlineLvl"))
    if outline_level is None:
        outline_level = OxmlElement("w:outlineLvl")
        plot_heading._element.get_or_add_pPr().append(outline_level)
    outline_level.set(qn("w:val"), "2")


def _configure_report_header_footer(doc, header_text: str) -> None:
    """Add generic report header/footer content generated entirely in code."""
    section = doc.sections[0]
    section.header_distance = Inches(0.5)
    section.footer_distance = Inches(0.25)

    header_paragraph = section.header.paragraphs[0]
    header_paragraph.clear()
    header_paragraph.style = "Header"
    header_paragraph.add_run(header_text)

    footer_paragraph = section.footer.paragraphs[0]
    footer_paragraph.clear()
    footer_paragraph.style = "Footer"
    footer_paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer_paragraph.add_run("Page ")
    _append_field(footer_paragraph, r"PAGE \* MERGEFORMAT", "1")

    paragraph_properties = footer_paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    top_border = OxmlElement("w:top")
    top_border.set(qn("w:val"), "single")
    top_border.set(qn("w:sz"), "4")
    top_border.set(qn("w:space"), "1")
    top_border.set(qn("w:color"), "000000")
    borders.append(top_border)
    paragraph_properties.append(borders)


@dataclass
class _FigureRegistry:
    count: int = 0

    def allocate(self) -> FigureReference:
        self.count += 1
        return FigureReference(
            bookmark=f"ReportFigure{self.count}",
            fallback_label=f"Figure 1-{self.count}",
        )

    def add_caption(self, doc, reference: FigureReference, text: str) -> None:
        paragraph = doc.add_paragraph(style="Caption")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        bookmark_start = OxmlElement("w:bookmarkStart")
        bookmark_start.set(qn("w:id"), str(self.count + 1000))
        bookmark_start.set(qn("w:name"), reference.bookmark)
        paragraph._p.append(bookmark_start)
        paragraph.add_run("Figure ").bold = True
        _append_field(paragraph, r"STYLEREF 1 \s", "1", bold=True)
        paragraph.add_run("-").bold = True
        _append_field(paragraph, r"SEQ Figure \* ARABIC \s 1", str(self.count), bold=True)
        bookmark_end = OxmlElement("w:bookmarkEnd")
        bookmark_end.set(qn("w:id"), str(self.count + 1000))
        paragraph._p.append(bookmark_end)
        paragraph.add_run(f" – {text}")


def _append_field(paragraph, instruction: str, fallback_text: str, bold: bool = False) -> None:
    begin_run = paragraph.add_run()
    begin_run.bold = bold
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin_run._r.append(begin)

    instruction_run = paragraph.add_run()
    instruction_run.bold = bold
    instruction_element = OxmlElement("w:instrText")
    instruction_element.set(qn("xml:space"), "preserve")
    instruction_element.text = f" {instruction} "
    instruction_run._r.append(instruction_element)

    separator_run = paragraph.add_run()
    separator_run.bold = bold
    separator = OxmlElement("w:fldChar")
    separator.set(qn("w:fldCharType"), "separate")
    separator_run._r.append(separator)

    result_run = paragraph.add_run()
    result_run.bold = bold
    result = OxmlElement("w:t")
    result.text = fallback_text
    result_run._r.append(result)

    end_run = paragraph.add_run()
    end_run.bold = bold
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    end_run._r.append(end)


def _create_heading_numbering(doc) -> int:
    numbering = doc.part.numbering_part.element
    for number in list(numbering.findall(qn("w:num"))):
        numbering.remove(number)
    abstract_ids = [
        int(element.get(qn("w:abstractNumId")))
        for element in numbering.findall(qn("w:abstractNum"))
        if element.get(qn("w:abstractNumId")) is not None
    ]
    abstract_id = max(abstract_ids, default=-1) + 1
    num_id = 1

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    abstract.set(f"{{{WORD_2012_NAMESPACE}}}restartNumberingAfterBreak", "0")
    nsid = OxmlElement("w:nsid")
    nsid.set(qn("w:val"), f"{abstract_id:08X}")
    abstract.append(nsid)
    multi_level = OxmlElement("w:multiLevelType")
    multi_level.set(qn("w:val"), "multilevel")
    abstract.append(multi_level)
    template = OxmlElement("w:tmpl")
    template.set(qn("w:val"), "5902F2C2")
    abstract.append(template)
    for level in range(3):
        item = OxmlElement("w:lvl")
        item.set(qn("w:ilvl"), str(level))
        start = OxmlElement("w:start")
        start.set(qn("w:val"), "1")
        item.append(start)
        number_format = OxmlElement("w:numFmt")
        number_format.set(qn("w:val"), "decimal")
        item.append(number_format)
        style_reference = OxmlElement("w:pStyle")
        style_reference.set(qn("w:val"), f"Heading{level + 1}")
        item.append(style_reference)
        level_text = OxmlElement("w:lvlText")
        level_text.set(qn("w:val"), ".".join(f"%{index}" for index in range(1, level + 2)))
        item.append(level_text)
        alignment = OxmlElement("w:lvlJc")
        alignment.set(qn("w:val"), "left")
        item.append(alignment)
        paragraph_properties = OxmlElement("w:pPr")
        indentation = OxmlElement("w:ind")
        if level == 0:
            indentation.set(qn("w:left"), "360")
            indentation.set(qn("w:hanging"), "360")
        elif level == 1:
            indentation.set(qn("w:left"), "0")
            indentation.set(qn("w:firstLine"), "0")
        else:
            indentation.set(qn("w:left"), "357")
            indentation.set(qn("w:hanging"), "357")
        paragraph_properties.append(indentation)
        item.append(paragraph_properties)
        abstract.append(item)
    for level in range(3, 9):
        item = OxmlElement("w:lvl")
        item.set(qn("w:ilvl"), str(level))
        number_format = OxmlElement("w:numFmt")
        number_format.set(qn("w:val"), "decimal")
        item.append(number_format)
        level_text = OxmlElement("w:lvlText")
        level_text.set(qn("w:val"), "")
        item.append(level_text)
        alignment = OxmlElement("w:lvlJc")
        alignment.set(qn("w:val"), "left")
        item.append(alignment)
        abstract.append(item)
    numbering.insert(len(numbering.findall(qn("w:abstractNum"))), abstract)

    number = OxmlElement("w:num")
    number.set(qn("w:numId"), str(num_id))
    number.set(f"{{{WORD_2016_CID_NAMESPACE}}}durableId", "1701663979")
    abstract_reference = OxmlElement("w:abstractNumId")
    abstract_reference.set(qn("w:val"), str(abstract_id))
    number.append(abstract_reference)
    numbering.append(number)
    for level in range(3):
        _set_numbering_properties(
            doc.styles[f"Heading {level + 1}"],
            None if level == 0 else level,
            num_id,
        )
    return num_id


def _create_bullet_numbering(doc) -> int:
    numbering = doc.part.numbering_part.element
    existing = next(
        (
            number
            for number in numbering.findall(qn("w:num"))
            if number.get(qn("w:numId")) == "2"
        ),
        None,
    )
    if existing is not None:
        _set_numbering_properties(doc.styles["List Bullet"], None, 2)
        return 2

    abstract_ids = [
        int(element.get(qn("w:abstractNumId")))
        for element in numbering.findall(qn("w:abstractNum"))
        if element.get(qn("w:abstractNumId")) is not None
    ]
    abstract_id = max(abstract_ids, default=-1) + 1

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    abstract.set(f"{{{WORD_2012_NAMESPACE}}}restartNumberingAfterBreak", "0")
    nsid = OxmlElement("w:nsid")
    nsid.set(qn("w:val"), "547D0181")
    abstract.append(nsid)
    multi_level = OxmlElement("w:multiLevelType")
    multi_level.set(qn("w:val"), "multilevel")
    abstract.append(multi_level)
    template = OxmlElement("w:tmpl")
    template.set(qn("w:val"), "1A2A351A")
    abstract.append(template)

    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    level.append(start)
    number_format = OxmlElement("w:numFmt")
    number_format.set(qn("w:val"), "bullet")
    level.append(number_format)
    style_reference = OxmlElement("w:pStyle")
    style_reference.set(qn("w:val"), "ListBullet")
    level.append(style_reference)
    level_text = OxmlElement("w:lvlText")
    level_text.set(qn("w:val"), "\u25e6")
    level.append(level_text)
    alignment = OxmlElement("w:lvlJc")
    alignment.set(qn("w:val"), "left")
    level.append(alignment)
    paragraph_properties = OxmlElement("w:pPr")
    indentation = OxmlElement("w:ind")
    indentation.set(qn("w:left"), "720")
    indentation.set(qn("w:hanging"), "360")
    paragraph_properties.append(indentation)
    level.append(paragraph_properties)
    run_properties = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), "Calibri")
    fonts.set(qn("w:hAnsi"), "Calibri")
    fonts.set(qn("w:hint"), "default")
    run_properties.append(fonts)
    color = OxmlElement("w:color")
    color.set(qn("w:val"), str(REPORT_HEADING_GREEN))
    run_properties.append(color)
    position = OxmlElement("w:position")
    position.set(qn("w:val"), "-4")
    run_properties.append(position)
    size = OxmlElement("w:sz")
    size.set(qn("w:val"), "36")
    run_properties.append(size)
    level.append(run_properties)
    abstract.append(level)
    # Word repairs out-of-order numbering XML and can relink heading styles to this bullet list.
    numbering.insert(len(numbering.findall(qn("w:abstractNum"))), abstract)

    number = OxmlElement("w:num")
    number.set(qn("w:numId"), "2")
    number.set(f"{{{WORD_2016_CID_NAMESPACE}}}durableId", "1656910545")
    abstract_reference = OxmlElement("w:abstractNumId")
    abstract_reference.set(qn("w:val"), str(abstract_id))
    number.append(abstract_reference)
    numbering.append(number)
    _set_numbering_properties(doc.styles["List Bullet"], None, 2)
    return 2


def _set_numbering_properties(target, level: int | None, num_id: int) -> None:
    element = target._element if hasattr(target, "_element") else target
    paragraph_properties = element.get_or_add_pPr()
    number_properties = paragraph_properties.find(qn("w:numPr"))
    if number_properties is None:
        number_properties = OxmlElement("w:numPr")
        insert_before = {
            qn("w:suppressLineNumbers"),
            qn("w:pBdr"),
            qn("w:shd"),
            qn("w:tabs"),
            qn("w:spacing"),
            qn("w:ind"),
            qn("w:contextualSpacing"),
            qn("w:jc"),
            qn("w:outlineLvl"),
            qn("w:rPr"),
        }
        insertion_index = next(
            (
                index
                for index, child in enumerate(paragraph_properties)
                if child.tag in insert_before
            ),
            len(paragraph_properties),
        )
        paragraph_properties.insert(insertion_index, number_properties)
    else:
        for child in list(number_properties):
            number_properties.remove(child)
    if level is not None:
        level_element = OxmlElement("w:ilvl")
        level_element.set(qn("w:val"), str(level))
        number_properties.append(level_element)
    number_element = OxmlElement("w:numId")
    number_element.set(qn("w:val"), str(num_id))
    number_properties.append(number_element)


def _apply_paragraph_numbering(paragraph, level: int, num_id: int) -> None:
    _set_numbering_properties(paragraph._p, level, num_id)


def _add_report_heading(doc, text: str, level: int):
    return doc.add_heading(text, level=level)


def _add_unumbered_plot_heading(doc, text: str) -> None:
    doc.add_paragraph(text, style="Plot Heading")


def _add_figure_reference_sentence(doc, before: str, reference: FigureReference, after: str) -> None:
    paragraph = doc.add_paragraph(style="Body Text")
    paragraph.add_run(before)
    _append_field(paragraph, rf"REF {reference.bookmark} \h", reference.fallback_label, bold=True)
    paragraph.add_run(after)


def _add_centered_report_image(doc, image_path: Path) -> None:
    paragraph = doc.add_paragraph(style="Body Text")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run().add_picture(str(image_path), width=Cm(IMAGE_WIDTH_CM))


ENVELOPE_SUMMARY_SHEETS = {"SFO": "LLp", "TOV": "LLp", "SA": "LGp"}
ENVELOPE_SUMMARY_RMS_EVENTS = {"TOV", "SA"}
SA_TOV_DURATION_MS = 300
PLOT_FAULT_LABEL_PATTERN = "|".join(
    re.escape(label)
    for label in sorted(
        (label for label in KNOWN_FAULT_LABELS if label.casefold() != "no fault"),
        key=len,
        reverse=True,
    )
)


def _log(log: LogFn | None, message: str) -> None:
    if log is not None:
        log(message)


def _safe_stem(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    value = re.sub(r"_+", "_", value)
    return value.strip("_.") or "figure"


def _is_report_image(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError:
        return False
    suffix = path.suffix.casefold()
    if suffix == ".png":
        return header.startswith(PNG_SIGNATURE)
    if suffix in {".jpg", ".jpeg"}:
        return header.startswith(JPEG_SIGNATURE)
    return False


def _dashboard_slicer_value(voltage: str) -> str:
    value = str(voltage).strip()
    return BUS_VOLTAGE_SLICER_VALUE_OVERRIDES.get(value, value)


def _dashboard_figure_uses_saved_voltage_filter(title: str) -> bool:
    return " ".join(str(title).split()).casefold() in {
        "initial voltages",
        "initial active power",
        "initial reactive power",
    }


def _slicer_cache_touches_sheet(slicer_cache, sheet_name: str) -> bool:
    wanted = sheet_name.strip().casefold()
    try:
        count = slicer_cache.Slicers.Count
    except EXCEL_AUTOMATION_ERRORS:
        return False

    for index in range(1, count + 1):
        try:
            slicer = slicer_cache.Slicers(index)
            if slicer.Shape.TopLeftCell.Worksheet.Name.strip().casefold() == wanted:
                return True
        except EXCEL_AUTOMATION_ERRORS:
            continue
    return False


def _find_bus_voltage_slicer_cache(workbook, sheet_name: str):
    fallback = None
    try:
        count = workbook.SlicerCaches.Count
    except EXCEL_AUTOMATION_ERRORS:
        return None

    for index in range(1, count + 1):
        slicer_cache = workbook.SlicerCaches(index)
        try:
            source_name = str(slicer_cache.SourceName)
        except EXCEL_AUTOMATION_ERRORS:
            source_name = ""
        try:
            cache_name = str(slicer_cache.Name)
        except EXCEL_AUTOMATION_ERRORS:
            cache_name = ""

        combined = f"{source_name} {cache_name}".casefold()
        if (
            BUS_VOLTAGE_SLICER_SOURCE_TEXT.casefold() not in combined
            and "bus_voltage" not in combined
        ):
            continue

        if _slicer_cache_touches_sheet(slicer_cache, sheet_name):
            return slicer_cache
        if fallback is None:
            fallback = slicer_cache
    return fallback


def _set_dashboard_voltage_filter(
    excel,
    workbook,
    sheet_name: str,
    voltage: str,
    log: LogFn | None,
) -> bool:
    slicer_cache = _find_bus_voltage_slicer_cache(workbook, sheet_name)
    if slicer_cache is None:
        _log(log, f"Dashboard voltage slicer not found: {sheet_name}; exporting current view.")
        return False

    slicer_value = _dashboard_slicer_value(voltage)
    try:
        source_name = str(slicer_cache.SourceName)
        slicer_cache.VisibleSlicerItemsList = (f"{source_name}.&[{slicer_value}]",)
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Dashboard voltage slicer update failed: {sheet_name} | {voltage} kV | {exc}")
        return False

    try:
        excel.CalculateUntilAsyncQueriesDone()
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Dashboard query wait skipped: {sheet_name} | {voltage} kV | {exc}")
    time.sleep(DASHBOARD_FILTER_SETTLE_S)
    _log(log, f"Dashboard voltage slicer set: {sheet_name} | {voltage} kV")
    return True


def _excel_context(get_excel: Callable[[], object] | None):
    return nullcontext(get_excel()) if get_excel is not None else excel_app()


def _find_event_images(
    project_root: Path,
    scope: ScopeEntry,
    event: str,
    voltage: str,
    image_cache: dict[Path, list[Path]] | None = None,
) -> list[Path]:
    event_dir = project_root / "Plots" / "Generated" / scope.folder / event
    return _find_voltage_images(event_dir, voltage, image_cache)


def _find_resonance_images(
    project_root: Path,
    scope: ScopeEntry,
    check: str,
    voltage_type: str,
    voltage: str,
    image_cache: dict[Path, list[Path]] | None = None,
) -> list[Path]:
    folder, type_folder = resonance_checks.report_folder(check, voltage_type)
    event_dir = project_root / "Plots" / "Generated" / scope.folder / folder / type_folder
    return _find_voltage_images(event_dir, voltage, image_cache)


def _find_voltage_images(
    event_dir: Path,
    voltage: str,
    image_cache: dict[Path, list[Path]] | None = None,
) -> list[Path]:
    if not event_dir.is_dir():
        return []
    voltage_patterns = (
        re.compile(rf"MM_{re.escape(voltage)}(?:_|\.|\b)", re.IGNORECASE),
        re.compile(rf"(?:^|[_ -]){re.escape(voltage)}(?:[_ -]?kV|[_ .-])", re.IGNORECASE),
    )
    if image_cache is None:
        image_paths = [
            path
            for pattern in ("*.png", "*.jpg", "*.jpeg")
            for path in sorted(event_dir.rglob(pattern))
        ]
    else:
        image_paths = image_cache.get(event_dir)
        if image_paths is None:
            image_paths = [
                path
                for pattern in ("*.png", "*.jpg", "*.jpeg")
                for path in sorted(event_dir.rglob(pattern))
            ]
            image_cache[event_dir] = image_paths
    return [
        path
        for path in image_paths
        if any(regex.search(path.name) for regex in voltage_patterns)
    ]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _envelope_summary_rows(
    workbook_path: Path,
    event_times: dict[str, float] | None = None,
    events: Iterable[str] | None = None,
    measurement_overrides: dict[str, str] | None = None,
) -> list[EnvelopeSummaryRow]:
    if not workbook_path.is_file():
        return []

    import openpyxl

    if events is None:
        selected_events = ["SFO", "TOV"]
    else:
        selected_events = []
        for event in events:
            event_name = str(event).strip().upper()
            if event_name in ENVELOPE_SUMMARY_SHEETS and event_name not in selected_events:
                selected_events.append(event_name)
    selected_times = [
        (event, float((event_times or {}).get(event, DEFAULT_EVENT_TIMES[event])))
        for event in selected_events
        if event in DEFAULT_EVENT_TIMES
    ]
    workbook = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True)
    try:
        selected_by_sheet: dict[str, dict[str, float]] = {}
        for event_name, event_time in selected_times:
            sheet_name = (measurement_overrides or {}).get(
                event_name,
                ENVELOPE_SUMMARY_SHEETS[event_name],
            )
            if sheet_name not in workbook.sheetnames:
                continue
            selected_by_sheet.setdefault(sheet_name, {})[event_name] = event_time

        matched: dict[str, tuple[str, dict[str, int], tuple[Any, ...]]] = {}
        for sheet_name, targets in selected_by_sheet.items():
            headers, rows = nearest_rows(workbook[sheet_name], targets)
            for event_name, row in rows.items():
                if row is not None:
                    matched[event_name] = (sheet_name, headers, row)

        output: list[EnvelopeSummaryRow] = []
        for event_name, _event_time in selected_times:
            match = matched.get(event_name)
            if match is None:
                continue
            sheet_name, headers, best_row = match

            peak = _as_float(row_value(best_row, headers, "Max_all", "Max"))
            time_s = _as_float(row_value(best_row, headers, "Time (s)"))
            if peak is None or time_s is None:
                continue
            output.append(
                EnvelopeSummaryRow(
                    event=event_name,
                    measurement=sheet_name,
                    time_s=time_s,
                    peak_kv=peak,
                    rms_kv=abs(peak) / math.sqrt(2.0),
                )
            )
        return output
    finally:
        workbook.close()


def _format_float(value: float, decimals: int = 3) -> str:
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _add_subscripted_kv_unit(paragraph, subscript: str) -> None:
    paragraph.add_run(" kV")
    run = paragraph.add_run(subscript)
    run.font.subscript = True


def _add_envelope_summary_list(doc, rows: list[EnvelopeSummaryRow]) -> None:
    if not rows:
        return
    bullet_num_id = _create_bullet_numbering(doc)
    for row in rows:
        paragraph = doc.add_paragraph(style="List Bullet")
        _apply_paragraph_numbering(paragraph, level=0, num_id=bullet_num_id)
        paragraph.add_run(f"{row.event}: {_format_float(row.peak_kv, 1)}")
        _add_subscripted_kv_unit(paragraph, "peak")
        if row.event in ENVELOPE_SUMMARY_RMS_EVENTS:
            paragraph.add_run(f" ({_format_float(row.rms_kv, 1)}")
            _add_subscripted_kv_unit(paragraph, "RMS")
            paragraph.add_run(")")
    doc.add_paragraph(style="Body Text")


def _report_dashboard_title(title: str) -> str:
    text = " ".join(str(title).split())
    return re.sub(r"\bRMS overvoltages\b", "RMS voltage rise", text, flags=re.IGNORECASE)


def _dashboard_figure_caption(title: str, voltage: str) -> str:
    normalized = " ".join(str(title).split())
    key = normalized.casefold()
    fixed_captions = {
        "initial voltages": "Initial voltage across voltage levels in the OWF",
        "initial reactive power": "Initial reactive power at the POC",
        "initial active power": "Initial active power at the PoC",
    }
    if key in fixed_captions:
        return fixed_captions[key]
    if "instantaneous overvoltages" in key:
        return f"Overvoltage results at the {voltage} kV side"
    return f"{_report_dashboard_title(normalized)} at {voltage} kV"


def _add_dashboard_figure_sentence(doc, title: str, voltage: str, reference: FigureReference) -> None:
    normalized = " ".join(str(title).split())
    key = normalized.casefold()
    if key == "initial voltages":
        before = "The initial voltage conditions of all the cases are shown in the "
    elif key == "initial reactive power":
        before = "The initial reactive power conditions of all the cases are shown in the "
    elif key == "initial active power":
        before = "The initial active power conditions of all the cases are shown in the "
    elif "instantaneous overvoltages" in key:
        before = f"The {voltage} kV side overvoltage peaks obtained for the assessed switching instants are shown in the "
    elif "RMS voltage" in key:
        before = f"The {_report_dashboard_title(normalized)} results at the PoC are shown in the "
    else:
        before = f"The {_report_dashboard_title(normalized)} results at {voltage} kV are shown in the "
    _add_figure_reference_sentence(doc, before, reference, ".")


def _add_time_domain_figure_sentence(doc, event: str, voltage: str, reference: FigureReference) -> None:
    _add_figure_reference_sentence(
        doc,
        "",
        reference,
        f" shows the time-domain plot for the highest {_report_event_name(event)} candidate recorded at the {voltage} kV level.",
    )


def _report_event_name(event: str) -> str:
    return str(event).strip().upper()


def _time_domain_figure_caption(event: str, voltage: str) -> str:
    if _report_event_name(event) == "SA":
        return f"Time-domain plot of the highest TOV at {voltage} kV for surge arrester selection"
    return f"Time-domain plots of the highest {_report_event_name(event)} at {voltage} kV"


def _add_sa_figure_sentence(
    doc,
    voltage: str,
    reference: FigureReference,
    tov_row: EnvelopeSummaryRow | None,
) -> None:
    _add_figure_reference_sentence(
        doc,
        "",
        reference,
        f" shows the highest TOV line-ground value found at {voltage} kV, which will be used for surge arrester selection.",
    )
    if tov_row is None:
        return
    paragraph = doc.add_paragraph(style="Body Text")
    paragraph.add_run("This TOV value is ")
    paragraph.add_run(_format_float(tov_row.rms_kv, 1))
    _add_subscripted_kv_unit(paragraph, "RMS")
    paragraph.add_run(f" and was assumed to last for {SA_TOV_DURATION_MS} ms.")


def _add_analysis_figure_sentence(
    doc,
    label: str,
    voltage_type: str,
    voltage: str,
    reference: FigureReference,
) -> None:
    _add_figure_reference_sentence(
        doc,
        f"The {label} {voltage_type} results recorded at {voltage} kV are shown in the ",
        reference,
        ".",
    )


def _load_sustained_sdpf_report_result(
    project_root: Path,
    scope: ScopeEntry,
    voltage: str,
    settings: sustained_sdpf.SustainedSDPFSettings,
    event_times: dict[str, float] | None,
) -> sustained_sdpf.SustainedSDPFResult | None:
    payload = sustained_sdpf.load_results(project_root, scope.folder)
    if payload.get("settings") != settings.to_mapping() or not sustained_sdpf.result_inputs_current(
        payload,
        str(voltage),
    ):
        return None
    raw = payload.get("results", {}).get(str(voltage))
    if not isinstance(raw, dict):
        return None
    try:
        result = sustained_sdpf.SustainedSDPFResult.from_dict(raw)
    except (TypeError, ValueError, KeyError):
        return None
    if abs(result.duration_s - settings.effective_duration(event_times)) > 1e-9:
        return None
    return result


def _add_sustained_sdpf_section(
    doc,
    result: sustained_sdpf.SustainedSDPFResult,
    voltage: str,
    image_path: Path | None,
    figure_registry: _FigureRegistry,
    check_cancel: CancelFn | None = None,
) -> None:
    _add_report_heading(doc, "Sustained SDPF stress", level=2)
    duration_ms = result.duration_s * 1000.0
    doc.add_paragraph(f"Duration criterion: {_format_float(duration_ms, 2)} ms", style="Body Text")
    relevant = [phase for phase in result.phases if phase.longest_margin_s > 0]
    if relevant:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        for cell, text in zip(table.rows[0].cells, ("Phase", "> 15% margin", "> SDPF")):
            cell.text = text
        for phase in relevant:
            cells = table.add_row().cells
            cells[0].text = phase.phase
            cells[1].text = f"{phase.longest_margin_s * 1000.0:.2f} ms"
            cells[2].text = (
                f"{phase.longest_sdpf_s * 1000.0:.2f} ms"
                if phase.longest_sdpf_s > 0
                else "-"
            )
    governing = result.governing
    doc.add_paragraph(
        f"Highest {_format_float(duration_ms, 2)} ms sustained stress: "
        f"{_format_float(governing.sustained_peak_kv, 2)} kVpeak / "
        f"{_format_float(governing.sustained_rms_kv, 2)} kVRMS - "
        f"{_format_float(governing.sustained_ratio * 100.0, 2)}% SDPF",
        style="Body Text",
    )
    if governing.longest_sdpf_s + 1e-12 >= result.duration_s:
        classification = f"SDPF exceeded for >= {_format_float(duration_ms, 2)} ms"
    elif governing.longest_margin_s + 1e-12 >= result.duration_s:
        classification = (
            f"SDPF safety margin exceeded; SDPF not exceeded for >= {_format_float(duration_ms, 2)} ms"
        )
    else:
        classification = f"No SDPF safety-margin exceedance sustained for >= {_format_float(duration_ms, 2)} ms"
    doc.add_paragraph(classification, style="Body Text")
    if image_path is None:
        return
    _cancel(check_cancel)
    reference = figure_registry.allocate()
    _add_unumbered_plot_heading(doc, _plot_heading_from_image_path(image_path))
    _add_figure_reference_sentence(doc, "", reference, " shows the governing Sustained SDPF MM time-domain plot.")
    _add_centered_report_image(doc, image_path)
    figure_registry.add_caption(doc, reference, f"Sustained SDPF stress at {voltage} kV")


def _analysis_figure_caption(label: str, voltage_type: str, voltage: str) -> str:
    return f"{label} {voltage_type} results at {voltage} kV"


def _plot_heading_from_image_path(path: Path) -> str:
    stem = path.stem
    if stem.endswith("_3Ph") or stem.endswith("_1Ch"):
        stem = stem.rsplit("_", 1)[0]
    # Group labels can contain underscores that must remain part of Element.
    match = re.match(
        rf"(?P<case>.+?)_(?P<element>MM_\d+(?:\.\d+)?(?:_[^_]+)*?)(?:_(?P<fault>{PLOT_FAULT_LABEL_PATTERN}))?_(?P<run>\d{{3,}})_(?P<trace>LGp_LLp|LGp|LLp|[^_]+)(?:_|$)",
        stem,
        flags=re.IGNORECASE,
    )
    if match:
        parts = [
            f"Case: {match.group('case')}",
            f"Run: {int(match.group('run'))}",
            f"Element: {match.group('element')}",
        ]
        fault = match.group("fault")
        if fault:
            parts.append(f"Fault: {fault}")
        trace = match.group("trace")
        if trace:
            parts.append(f"Trace: {trace.replace('_', ' & ') if trace == 'LGp_LLp' else trace}")
        return " | ".join(parts)
    return path.stem


def _export_envelope_chart(
    project_root: Path,
    scope: ScopeEntry,
    voltage: str,
    export_dir: Path,
    log: LogFn | None = None,
    get_excel: Callable[[], object] | None = None,
    check_cancel: CancelFn | None = None,
) -> Path | None:
    base_workbook_path = (
        project_root
        / "Voltage_envelope"
        / scope.folder
        / f"MM_{voltage}.xlsx"
    )
    workbook_path = (
        project_root
        / "Voltage_envelope"
        / scope.folder
        / f"MM_{voltage}_with_combined_plot.xlsx"
    )
    if not workbook_path.is_file():
        return None
    if (
        base_workbook_path.is_file()
        and workbook_path.stat().st_mtime_ns < base_workbook_path.stat().st_mtime_ns
    ):
        _log(
            log,
            f"Envelope chart is older than its data and was skipped: "
            f"{scope.folder} / {workbook_path.name}. Rebuild envelope charts.",
        )
        return None
    _cancel(check_cancel)
    export_dir.mkdir(parents=True, exist_ok=True)
    output_path = export_dir / f"Envelope_{scope.folder}_{voltage}_kV.png"
    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        with _excel_context(get_excel) as excel:
            workbook = excel.Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
            try:
                worksheet = workbook.Worksheets("LLp")
                if worksheet.ChartObjects().Count < 1:
                    return None
                chart_object = worksheet.ChartObjects(1)
                _log(log, f"Exporting envelope chart: {scope.folder} | {voltage} kV")
                for _attempt in range(2):
                    _cancel(check_cancel)
                    try:
                        chart_object.Activate()
                    except EXCEL_AUTOMATION_ERRORS:
                        pass
                    time.sleep(0.5)
                    ok = chart_object.Chart.Export(str(output_path), "PNG")
                    if ok and _is_report_image(output_path):
                        return output_path
                    try:
                        output_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                _log(log, f"Excel did not export a valid envelope chart: {output_path.name}")
                return None
            finally:
                workbook.Close(SaveChanges=False)
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Envelope chart export skipped: {exc}")
        return None


def _parse_dashboard_figure_id(figure_id: str) -> tuple[str, str, int, str]:
    parts = figure_id.split("|", 3)
    if len(parts) != 4:
        raise ValueError(f"Unsupported dashboard figure id: {figure_id}")
    workbook, sheet, chart_index, title = [part.strip() for part in parts]
    return workbook, sheet, int(chart_index), title


def _export_dashboard_figures(
    project_root: Path,
    figure_ids: Iterable[str],
    voltage: str,
    export_dir: Path,
    log: LogFn | None = None,
    get_excel: Callable[[], object] | None = None,
    get_dashboard_workbook: Callable[[Path, str], object] | None = None,
    check_cancel: CancelFn | None = None,
) -> list[tuple[str, Path]]:
    selected_ids = [figure_id for figure_id in figure_ids if figure_id]
    if not selected_ids:
        return []
    export_dir.mkdir(parents=True, exist_ok=True)
    exported: list[tuple[str, Path]] = []
    try:
        with _excel_context(get_excel) as excel:
            grouped: dict[str, list[tuple[str, int, str, str]]] = {}
            for figure_id in selected_ids:
                _cancel(check_cancel)
                try:
                    workbook_name, sheet_name, chart_index, title = _parse_dashboard_figure_id(figure_id)
                except ValueError as exc:
                    _log(log, str(exc))
                    continue
                grouped.setdefault(workbook_name, []).append((sheet_name, chart_index, title, figure_id))

            for workbook_name, figures in grouped.items():
                _cancel(check_cancel)
                workbook_path = project_root / "Dashboards" / workbook_name
                if not workbook_path.is_file():
                    _log(log, f"Dashboard workbook not found, skipping: {workbook_name}")
                    continue
                use_cached_workbook = get_dashboard_workbook is not None and not any(
                    _dashboard_figure_uses_saved_voltage_filter(figure[2])
                    for figure in figures
                )

                saved_filter_figures = [
                    figure
                    for figure in figures
                    if _dashboard_figure_uses_saved_voltage_filter(figure[2])
                ]
                voltage_filter_figures = [
                    figure
                    for figure in figures
                    if not _dashboard_figure_uses_saved_voltage_filter(figure[2])
                ]
                for figures_to_export, apply_voltage_filter in (
                    (saved_filter_figures, False),
                    (voltage_filter_figures, True),
                ):
                    if not figures_to_export:
                        continue
                    if apply_voltage_filter and use_cached_workbook:
                        _log(log, f"Opening dashboard for report figures: {workbook_name}")
                        workbook = get_dashboard_workbook(project_root, workbook_name)
                        close_workbook = False
                    else:
                        _log(log, f"Opening dashboard for saved figure state: {workbook_name}")
                        workbook = excel.Workbooks.Open(
                            str(workbook_path),
                            UpdateLinks=0,
                            ReadOnly=True,
                        )
                        close_workbook = True
                    try:
                        filtered_sheets: set[str] = set()
                        for sheet_name, chart_index, title, figure_id in figures_to_export:
                            _cancel(check_cancel)
                            try:
                                sheet_key = sheet_name.strip().casefold()
                                if apply_voltage_filter and sheet_key not in filtered_sheets:
                                    _set_dashboard_voltage_filter(excel, workbook, sheet_name, str(voltage), log)
                                    filtered_sheets.add(sheet_key)
                                worksheet = workbook.Worksheets(sheet_name)
                                chart_object = worksheet.ChartObjects(chart_index)
                                figure_title = title or f"Chart {chart_index}"
                                file_name = _safe_stem(
                                    f"{voltage}_kV_{workbook_name}_{sheet_name}_{chart_index}_{figure_title}.png"
                                )
                                output_path = export_dir / file_name
                                try:
                                    output_path.unlink(missing_ok=True)
                                except OSError:
                                    pass
                                _log(log, f"Exporting dashboard figure: {voltage} kV | {figure_title}")
                                ok = chart_object.Chart.Export(str(output_path), "PNG")
                                if not ok or not _is_report_image(output_path):
                                    _log(log, f"Excel did not export dashboard figure: {figure_id}")
                                    try:
                                        output_path.unlink(missing_ok=True)
                                    except OSError:
                                        pass
                                    continue
                                exported.append((figure_title, output_path))
                            except EXCEL_AUTOMATION_ERRORS as exc:
                                _log(log, f"Dashboard figure skipped: {figure_id} | {exc}")
                    finally:
                        if close_workbook:
                            workbook.Close(SaveChanges=False)
    except EXCEL_AUTOMATION_ERRORS as exc:
        _log(log, f"Dashboard figure export skipped: {exc}")

    return exported


def build_reports_from_existing_plots(
    project_roots: Iterable[str | Path],
    scopes: Iterable[ScopeEntry],
    voltages: Iterable[str],
    events: Iterable[str],
    dashboard_figure_ids: Iterable[str] = (),
    resonance_settings: dict[str, object] | None = None,
    event_times: dict[str, float] | None = None,
    log: LogFn | None = None,
    check_cancel: CancelFn | None = None,
    sustained_sdpf_settings: dict[str, object] | None = None,
) -> list[Path]:
    """Build draft Word reports from already generated plot image files."""
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is required to build Word reports.") from exc

    written: list[Path] = []
    selected_scopes = list(scopes)
    selected_events = list(events)
    selected_voltages = list(voltages)
    parsed_resonance = resonance_checks.ResonanceSettings.from_mapping(resonance_settings)
    parsed_sustained = sustained_sdpf.SustainedSDPFSettings.from_mapping(sustained_sdpf_settings)
    _cancel(check_cancel)

    with ExitStack() as stack:
        excel = None
        dashboard_workbooks: dict[tuple[Path, str], object] = {}

        def get_excel():
            nonlocal excel
            _cancel(check_cancel)
            if excel is None:
                excel = stack.enter_context(excel_app())
            return excel

        def get_dashboard_workbook(project_root: Path, workbook_name: str):
            _cancel(check_cancel)
            key = (project_root, workbook_name)
            workbook = dashboard_workbooks.get(key)
            if workbook is None:
                workbook_path = project_root / "Dashboards" / workbook_name
                workbook = get_excel().Workbooks.Open(str(workbook_path), UpdateLinks=0, ReadOnly=True)
                dashboard_workbooks[key] = workbook
                stack.callback(lambda wb=workbook: wb.Close(SaveChanges=False))
            return workbook

        for project_root in project_roots:
            _cancel(check_cancel)
            root = Path(project_root).resolve()
            for scope in selected_scopes:
                _cancel(check_cancel)
                report_dir = root / "Reports" / scope.folder
                report_dir.mkdir(parents=True, exist_ok=True)
                for temporary_dir in (
                    report_dir / "_envelope_exports",
                    report_dir / "_dashboard_exports",
                ):
                    stack.callback(shutil.rmtree, temporary_dir, ignore_errors=True)
                image_cache: dict[Path, list[Path]] = {}
                for voltage in selected_voltages:
                    _cancel(check_cancel)
                    _log(log, f"Building report: {root.name} | {scope.folder} | {voltage} kV")
                    doc = Document()
                    section = doc.sections[0]
                    section.page_width = Cm(21.0)
                    section.page_height = Cm(29.7)
                    section.left_margin = Cm(2.54)
                    section.right_margin = Cm(2.54)
                    section.top_margin = Cm(2.54)
                    section.bottom_margin = Cm(2.54)

                    _configure_report_styles(doc)
                    _configure_report_header_footer(
                        doc,
                        f"PSCAD Results Analysis - {root.name} - {scope.name}",
                    )

                    _create_heading_numbering(doc)
                    figure_registry = _FigureRegistry()
                    _add_report_heading(doc, f"Voltage {voltage} kV - {scope.name}", level=1)
                    envelope_workbook = root / "Voltage_envelope" / scope.folder / f"MM_{voltage}.xlsx"
                    sa_tov_rows = []
                    if any(_report_event_name(event) == "SA" for event in selected_events):
                        sa_tov_rows = _envelope_summary_rows(
                            envelope_workbook,
                            event_times,
                            events=["TOV"],
                            measurement_overrides={"TOV": "LGp"},
                        )
                    sa_tov_row = sa_tov_rows[0] if sa_tov_rows else None

                    dashboard_figures = _export_dashboard_figures(
                        root,
                        dashboard_figure_ids,
                        str(voltage),
                        report_dir / "_dashboard_exports" / f"Voltage_{voltage}_kV",
                        log,
                        get_excel,
                        get_dashboard_workbook,
                        check_cancel,
                    )
                    _cancel(check_cancel)
                    dashboard_figures.sort(
                        key=lambda figure: DASHBOARD_REPORT_TITLE_ORDER.get(
                            figure[0].strip().casefold(),
                            len(DASHBOARD_REPORT_TITLE_ORDER),
                        )
                    )

                    envelope_chart = _export_envelope_chart(
                        root,
                        scope,
                        str(voltage),
                        report_dir / "_envelope_exports",
                        log,
                        get_excel,
                        check_cancel,
                    )
                    _cancel(check_cancel)
                    if envelope_chart is not None:
                        _add_report_heading(
                            doc,
                            f"{voltage} kV - Envelope - {scope.name}",
                            level=2,
                        )
                        reference = figure_registry.allocate()
                        _add_figure_reference_sentence(
                            doc,
                            "",
                            reference,
                            " shows that the highest overvoltages are:",
                        )
                        _add_envelope_summary_list(
                            doc,
                            _envelope_summary_rows(envelope_workbook, event_times, selected_events),
                        )
                        _add_centered_report_image(doc, envelope_chart)
                        figure_registry.add_caption(
                            doc,
                            reference,
                            f"Representative overvoltages envelope at {voltage} kV",
                        )

                    if dashboard_figures:
                        _add_report_heading(
                            doc,
                            f"{voltage} kV - Dashboard Figures - {scope.name}",
                            level=2,
                        )
                        for figure_title, image_path in dashboard_figures:
                            _cancel(check_cancel)
                            reference = figure_registry.allocate()
                            _add_unumbered_plot_heading(doc, _report_dashboard_title(figure_title))
                            _add_dashboard_figure_sentence(doc, figure_title, str(voltage), reference)
                            _add_centered_report_image(doc, image_path)
                            figure_registry.add_caption(
                                doc,
                                reference,
                                _dashboard_figure_caption(figure_title, str(voltage)),
                            )
                    elif dashboard_figure_ids:
                        doc.add_paragraph(
                            "Selected dashboard figures could not be exported.",
                            style="Body Text",
                        )

                    plot_count = 0

                    for event in selected_events:
                        _cancel(check_cancel)
                        images = _find_event_images(root, scope, event, voltage, image_cache)
                        if not images:
                            continue
                        _add_report_heading(
                            doc,
                            f"{voltage} kV - {event} - {scope.name}",
                            level=2,
                        )
                        for image_path in images:
                            _cancel(check_cancel)
                            if not _is_report_image(image_path):
                                _log(log, f"Skipping invalid plot image: {image_path}")
                                continue
                            reference = figure_registry.allocate()
                            _add_unumbered_plot_heading(doc, _plot_heading_from_image_path(image_path))
                            if _report_event_name(event) == "SA":
                                _add_sa_figure_sentence(doc, str(voltage), reference, sa_tov_row)
                            else:
                                _add_time_domain_figure_sentence(doc, event, str(voltage), reference)
                            _add_centered_report_image(doc, image_path)
                            figure_registry.add_caption(
                                doc,
                                reference,
                                _time_domain_figure_caption(event, str(voltage)),
                            )
                            plot_count += 1

                    if parsed_sustained.enabled:
                        _cancel(check_cancel)
                        sustained_result = _load_sustained_sdpf_report_result(
                            root,
                            scope,
                            str(voltage),
                            parsed_sustained,
                            event_times,
                        )
                        if sustained_result is not None:
                            sustained_image = _find_event_images(
                                root,
                                scope,
                                sustained_sdpf.SUSTAINED_SDPF,
                                str(voltage),
                                image_cache,
                            )
                            _add_sustained_sdpf_section(
                                doc,
                                sustained_result,
                                str(voltage),
                                sustained_image[0] if sustained_image else None,
                                figure_registry,
                                check_cancel,
                            )
                            if sustained_image:
                                plot_count += 1

                    for check in parsed_resonance.effective_enabled_checks:
                        _cancel(check_cancel)
                        for voltage_type in resonance_checks.VOLTAGE_TYPES:
                            _cancel(check_cancel)
                            images = _find_resonance_images(root, scope, check, voltage_type, voltage, image_cache)
                            if not images:
                                continue
                            label = resonance_checks.CHECK_DEFINITIONS[check]["label"]
                            _add_report_heading(
                                doc,
                                f"{voltage} kV - {label} - {voltage_type} - {scope.name}",
                                level=2,
                            )
                            for image_path in images:
                                _cancel(check_cancel)
                                if not _is_report_image(image_path):
                                    _log(log, f"Skipping invalid plot image: {image_path}")
                                    continue
                                reference = figure_registry.allocate()
                                _add_unumbered_plot_heading(doc, _plot_heading_from_image_path(image_path))
                                _add_analysis_figure_sentence(
                                    doc,
                                    label,
                                    voltage_type,
                                    str(voltage),
                                    reference,
                                )
                                _add_centered_report_image(doc, image_path)
                                figure_registry.add_caption(
                                    doc,
                                    reference,
                                    _analysis_figure_caption(label, voltage_type, str(voltage)),
                                )
                                plot_count += 1

                    if plot_count == 0:
                        doc.add_paragraph(
                            "No generated plot images were found for this report.",
                            style="Body Text",
                        )

                    output_path = report_dir / f"Voltage_{voltage}_kV.docx"
                    _cancel(check_cancel)
                    doc.save(output_path)
                    _cancel(check_cancel)
                    written.append(output_path)
                    _log(log, f"Wrote report: {output_path}")

                for temporary_dir in (
                    report_dir / "_envelope_exports",
                    report_dir / "_dashboard_exports",
                ):
                    shutil.rmtree(temporary_dir, ignore_errors=True)

    return written
