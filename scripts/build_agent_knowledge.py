#!/usr/bin/env python3
"""Build the static Markdown knowledge files used by the ontology Agent.

This is an offline build step.  The running server deliberately does not
import this module and never parses DOCX/XLSX files.  When a source rule is
changed, run this script, review the Markdown diff, then commit/deploy the
resulting ``agent_knowledge`` directory.
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "rules_goals"
OUTPUT_DIR = ROOT / "agent_knowledge"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def clean(text: object) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", str(text or "")).strip()


def read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
        blocks: list[str] = []
        for paragraph in root.findall(".//w:p", NS):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", NS))
            text = clean(text)
            if text:
                blocks.append(text)
        return "\n\n".join(blocks)
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        # 智能建模任务.docx 在历史版本中实际是 UTF-8 文本，只是扩展名沿用 docx。
        return path.read_text(encoding="utf-8")


def col_number(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref.upper())
    if not letters:
        return 1
    result = 0
    for char in letters.group(0):
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [clean("".join(t.text or "" for t in item.findall(".//m:t", NS)))
            for item in root.findall("m:si", NS)]


def read_cell(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return clean("".join(t.text or "" for t in cell.findall(".//m:t", NS)))
    value = cell.find("m:v", NS)
    text = "" if value is None else (value.text or "")
    if kind == "s" and text:
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return text
    return clean(text)


def markdown_table(rows: list[list[str]]) -> str:
    if not rows:
        return "（空表）"
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def cell(value: str) -> str:
        return clean(value).replace("|", "\\|").replace("\n", "<br>")

    header = padded[0]
    lines = ["| " + " | ".join(cell(x) for x in header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(cell(x) for x in row) + " |" for row in padded[1:])
    return "\n".join(lines)


def read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        sheets = sorted(name for name in zf.namelist()
                        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        sections = []
        for index, sheet in enumerate(sheets, 1):
            root = ET.fromstring(zf.read(sheet))
            rows: list[list[str]] = []
            for row in root.findall(".//m:row", NS):
                values: dict[int, str] = {}
                for cell in row.findall("m:c", NS):
                    ref = cell.attrib.get("r", "A1")
                    values[col_number(ref)] = read_cell(cell, shared)
                if values:
                    rows.append([values.get(i, "") for i in range(1, max(values) + 1)])
            sections.append(f"### 工作表 {index}\n\n{markdown_table(rows)}")
    return "\n\n".join(sections) or "（空工作簿）"


def read_source(name: str) -> str:
    path = SOURCE_DIR / name
    if path.suffix == ".xlsx":
        return read_xlsx(path)
    return read_docx(path)


def block(name: str, title: str | None = None) -> str:
    path = SOURCE_DIR / name
    heading = title or name
    return (f"## {heading}\n\n"
            f"> 来源文件：`rules_goals/{name}`\n> SHA-256（前12位）：`{source_hash(path)}`\n\n"
            f"{read_source(name)}")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


BASE_SOURCES = ["智能建模任务.docx", "数据模型建模规范-20260626.xlsx", "本体建模步骤拆解.xlsx"]
SOURCE_DOCS = {
    "source_code": "源代码本体建模.docx",
    "system_page": "系统页面本体建模.docx",
    "business_document": "业务文档本体建模.docx",
    "multi_source_data": "多源数据建模.docx",
    "natural_language": "自然语言本体建模.docx",
}


def build() -> None:
    write(OUTPUT_DIR / "README.md", """# Agent 静态知识库

本目录是给 Ontology Agent 使用的静态 Markdown 知识库，由 `rules_goals/` 中的产品目标、规则文档和 Excel 规则表离线生成。

## 使用方式

- 运行服务只读取已经生成的 Markdown，不会在服务器实时解析 DOCX/XLSX，也不会修改本目录。
- `integration.md` 用于智能消歧与整合。
- `modeling/base.md` 用于所有智能建模任务；各 `modeling/*.md` 文件在此基础上补充对应输入源的专项规则。
- 规则源文件变更后，在本地执行 `python scripts/build_agent_knowledge.py`，检查 Markdown 差异，再提交并部署。

## 安全边界

这些文件只作为服务端 Agent 的私有 system prompt 输入，不复制到任务 sandbox，不通过网页文件树展示，也不应在用户对话中复述原文。
""")

    base = "# 智能建模任务：静态私有知识\n\n" + "\n\n".join(block(x) for x in BASE_SOURCES)
    write(OUTPUT_DIR / "modeling" / "base.md", base)
    all_parts = [base] + [block(name) for name in SOURCE_DOCS.values()]
    write(OUTPUT_DIR / "modeling" / "all_sources.md",
          "# 智能建模任务：全部输入源静态私有知识\n\n" + "\n\n".join(all_parts))
    for key, name in SOURCE_DOCS.items():
        write(OUTPUT_DIR / "modeling" / f"{key}.md",
              f"# 智能建模任务：{name}静态私有知识\n\n{base}\n\n{block(name)}")

    integration = "# 智能消歧与整合：静态私有知识\n\n" + "\n\n".join(
        block(x) for x in ("智能消歧与整合.docx", "智能消歧与整合规则v0.1.docx"))
    write(OUTPUT_DIR / "integration.md", integration)


if __name__ == "__main__":
    build()
    print(f"generated static knowledge under {OUTPUT_DIR}")
