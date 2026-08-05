"""Dependency-light document preparation for ontology modeling tasks.

The Agent works best with bounded, line-oriented inputs.  This module converts
the document formats used by ``DOCUMENT_MODELING`` tasks into a small bundle:

* ``content.md`` keeps paragraphs, headings and slide/page boundaries;
* ``tables/*.csv`` keeps extracted tables in UTF-8 CSV form;
* ``manifest.json`` records chapters/pages/tables and the source fingerprint.

DOCX and PPTX are Open XML ZIP packages and are parsed with the standard
library.  PDF uses the optional-but-required ``pypdf`` runtime dependency so a
missing installation produces an actionable preparation error instead of a
silent empty model.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


DOCUMENT_EXTENSIONS = {".docx", ".pptx", ".pdf"}
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _safe_name(value: object, fallback: str = "document") -> str:
    name = re.sub(r"[^\w\-.一-鿿]+", "_", str(value or "")).strip("._")
    return name[:100] or fallback


def _escape_cell(value: object) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_table(output_dir: Path, index: int, rows: list[list[object]], page: int | None = None) -> dict:
    rows = [[_escape_cell(cell) for cell in row] for row in rows]
    width = max((len(row) for row in rows), default=0)
    rows = [row + [""] * (width - len(row)) for row in rows]
    filename = f"{index:03d}-table.csv"
    table_dir = output_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    path = table_dir / filename
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(rows)
    item = {
        "id": f"table-{index}",
        "file": f"tables/{filename}",
        "rows": len(rows),
        "dataRows": max(len(rows) - 1, 0),
        "columns": width,
    }
    if page is not None:
        item["page"] = page
    return item


def _heading_level(style: str) -> int:
    match = re.search(r"heading\s*([1-6])", style or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _docx_text(element: ET.Element) -> str:
    return "".join(str(node.text or "") for node in element.iter()
                   if _local(node.tag) == "t").strip()


def _docx_table(element: ET.Element) -> list[list[str]]:
    rows = []
    for row in element.iter():
        if _local(row.tag) != "tr":
            continue
        cells = []
        for cell in row:
            if _local(cell.tag) == "tc":
                cells.append(_docx_text(cell))
        if cells:
            rows.append(cells)
    return rows


def _extract_docx(source: Path, output_dir: Path) -> tuple[str, list[dict], list[dict], int]:
    with zipfile.ZipFile(source) as package:
        root = ET.fromstring(package.read("word/document.xml"))
    body = next((node for node in root.iter() if _local(node.tag) == "body"), root)
    blocks: list[str] = []
    sections: list[dict] = []
    tables: list[dict] = []
    section_index = 0
    table_index = 0
    for child in list(body):
        kind = _local(child.tag)
        if kind == "p":
            text = _docx_text(child)
            if not text:
                continue
            style = ""
            for node in child.iter():
                if _local(node.tag) == "pStyle":
                    style = node.attrib.get(f"{{{_W_NS}}}val", "")
                    break
            level = _heading_level(style)
            if level:
                section_index += 1
                title = text
                sections.append({"id": f"section-{section_index}", "title": title,
                                 "level": level, "kind": "heading"})
                blocks.append(f"{'#' * level} {title}")
            else:
                blocks.append(text)
        elif kind == "tbl":
            rows = _docx_table(child)
            if rows:
                table_index += 1
                tables.append(_write_table(output_dir, table_index, rows))
                blocks.append(f"[表格 {table_index}：tables/{table_index:03d}-table.csv]")
    return "\n\n".join(blocks).strip() + "\n", sections, tables, 1


def _pptx_table(element: ET.Element) -> list[list[str]]:
    rows = []
    for row in element.iter():
        if _local(row.tag) != "tr":
            continue
        cells = []
        for cell in row:
            if _local(cell.tag) == "tc":
                cells.append("".join(str(node.text or "") for node in cell.iter()
                                      if _local(node.tag) == "t").strip())
        if cells:
            rows.append(cells)
    return rows


def _pptx_shape_text(shape: ET.Element) -> str:
    return " ".join(str(node.text or "").strip() for node in shape.iter()
                     if _local(node.tag) == "t" and str(node.text or "").strip()).strip()


def _slide_paths(package: zipfile.ZipFile) -> list[str]:
    paths = [name for name in package.namelist()
             if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)]
    return sorted(paths, key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))


def _extract_pptx(source: Path, output_dir: Path) -> tuple[str, list[dict], list[dict], int]:
    blocks: list[str] = []
    sections: list[dict] = []
    tables: list[dict] = []
    table_index = 0
    with zipfile.ZipFile(source) as package:
        slides = _slide_paths(package)
        for slide_number, path in enumerate(slides, 1):
            root = ET.fromstring(package.read(path))
            sections.append({"id": f"slide-{slide_number}", "title": f"第 {slide_number} 页",
                             "level": 2, "kind": "slide", "page": slide_number})
            blocks.append(f"## 第 {slide_number} 页")
            for node in root.iter():
                if _local(node.tag) == "tbl":
                    rows = _pptx_table(node)
                    if rows:
                        table_index += 1
                        tables.append(_write_table(output_dir, table_index, rows, slide_number))
                        blocks.append(f"[表格 {table_index}：tables/{table_index:03d}-table.csv]")
            for node in root.iter():
                if _local(node.tag) == "sp":
                    text = _pptx_shape_text(node)
                    if text:
                        blocks.append(text)
    return "\n\n".join(blocks).strip() + "\n", sections, tables, len(slides)


def _pdf_heading_level(line: str) -> int:
    value = str(line or "").strip()
    if re.match(r"^第[一二三四五六七八九十百千\d]+[章节篇部]", value):
        return 1
    if re.match(r"^[一二三四五六七八九十百千]+[、.]", value):
        return 2
    if re.match(r"^\d+(?:\.\d+){0,3}[、. ]+\S+", value):
        return min(value.split()[0].count(".") + 1, 6)
    return 0


def _extract_pdf(source: Path, output_dir: Path) -> tuple[str, list[dict], list[dict], int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("解析 PDF 需要安装 pypdf，请执行 pip install -r open-claude/open_claude/requirements.txt") from exc
    reader = PdfReader(str(source))
    blocks: list[str] = []
    sections: list[dict] = []
    tables: list[dict] = []
    table_index = 0
    section_index = 0
    for page_number, page in enumerate(reader.pages, 1):
        blocks.append(f"## 第 {page_number} 页")
        text = page.extract_text() or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            level = _pdf_heading_level(line)
            if level:
                section_index += 1
                sections.append({"id": f"section-{section_index}", "title": line,
                                 "level": level, "kind": "heading", "page": page_number})
                blocks.append(f"{'#' * level} {line}")
            else:
                blocks.append(line)
        # Preserve obvious text-extracted tables without claiming arbitrary
        # aligned prose is a table: pipe/tab-delimited rows are explicit.
        table_rows = []
        for line in lines:
            if "\t" in line:
                table_rows.append(line.split("\t"))
            elif line.count("|") >= 2:
                table_rows.append([cell.strip() for cell in line.strip("|").split("|")])
        if table_rows:
            table_index += 1
            tables.append(_write_table(output_dir, table_index, table_rows, page_number))
            blocks.append(f"[表格 {table_index}：tables/{table_index:03d}-table.csv]")
    return "\n\n".join(blocks).strip() + "\n", sections, tables, len(reader.pages)


def extract_document(source_path: str | Path, output_dir: str | Path) -> tuple[dict | None, str | None]:
    """Extract one supported document into a manifest bundle."""
    source = Path(source_path)
    output = Path(output_dir)
    suffix = source.suffix.lower()
    if suffix not in DOCUMENT_EXTENSIONS:
        return None, f"不支持的文档格式 {suffix or '(无扩展名)'}，当前支持 DOCX、PPTX、PDF"
    try:
        output.mkdir(parents=True, exist_ok=True)
        for child in output.iterdir():
            if child.name == "manifest.json":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        if suffix == ".docx":
            content, sections, tables, pages = _extract_docx(source, output)
            parser = "builtin-docx-v1"
        elif suffix == ".pptx":
            content, sections, tables, pages = _extract_pptx(source, output)
            parser = "builtin-pptx-v1"
        else:
            content, sections, tables, pages = _extract_pdf(source, output)
            parser = "pypdf-v1"
        (output / "content.md").write_text(content, encoding="utf-8")
        manifest = {
            "source": source.name,
            "format": suffix.lstrip("."),
            "parser": parser,
            "sourceSha256": _sha256(source),
            "contentFile": "content.md",
            "sections": sections,
            "tables": tables,
            "pages": pages,
            "instructions": "先读取 content.md；再按 tables/*.csv 读取所有表格，按 manifest.sections 追踪章节/页码，禁止只取摘要或前几页。",
        }
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest, None
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, RuntimeError) as exc:
        return None, f"文档解析失败: {exc}"


def prepare_mission_documents(cwd: str | Path) -> tuple[list[dict], list[dict]]:
    """Prepare all DOCX/PPTX/PDF inputs under ``mission-input``."""
    input_dir = Path(cwd) / "mission-input"
    if not input_dir.is_dir():
        return [], []
    manifests: list[dict] = []
    errors: list[dict] = []
    for source in sorted(input_dir.iterdir(), key=lambda path: path.name):
        if not source.is_file() or source.suffix.lower() not in DOCUMENT_EXTENSIONS:
            continue
        output_dir = input_dir / f"{source.stem}-document"
        manifest_path = output_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                cached = json.loads(manifest_path.read_text(encoding="utf-8"))
                if cached.get("sourceSha256") == _sha256(source) and (output_dir / "content.md").is_file():
                    manifests.append(cached)
                    continue
            except (OSError, ValueError, TypeError):
                pass
        manifest, error = extract_document(source, output_dir)
        if manifest:
            manifest["source"] = os.path.relpath(source, cwd).replace("\\", "/")
            manifest["bundle"] = os.path.relpath(output_dir, cwd).replace("\\", "/")
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            manifests.append(manifest)
        else:
            errors.append({"source": os.path.relpath(source, cwd).replace("\\", "/"),
                           "error": error or "未知文档解析错误"})
    return manifests, errors
