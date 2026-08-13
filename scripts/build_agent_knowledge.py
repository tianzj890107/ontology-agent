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
SOURCE_DIR = next((path for path in (ROOT / "rules", ROOT / "rules_goals")
                   if path.is_dir()), ROOT / "rules")
OUTPUT_DIR = ROOT / "agent_knowledge"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}

KNOWLEDGE_VERSION = "v0.0.1"


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


def workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """Return worksheets in workbook order with their user-facing names."""
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        relationships = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        targets = {
            item.attrib.get("Id", ""): item.attrib.get("Target", "")
            for item in relationships.findall("pr:Relationship", NS)
        }
        result = []
        for sheet in workbook.findall(".//m:sheets/m:sheet", NS):
            target = targets.get(sheet.attrib.get(f"{{{NS['r']}}}id", ""), "")
            if not target:
                continue
            normalized = target.lstrip("/")
            if not normalized.startswith("xl/"):
                normalized = "xl/" + normalized
            result.append((sheet.attrib.get("name", "未命名工作表"), normalized))
        if result:
            return result
    except (KeyError, ET.ParseError):
        pass
    fallback = sorted(name for name in zf.namelist()
                      if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
    return [(f"工作表 {index}", name) for index, name in enumerate(fallback, 1)]


def read_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        sections = []
        for index, (sheet_name, sheet) in enumerate(workbook_sheets(zf), 1):
            root = ET.fromstring(zf.read(sheet))
            rows: list[list[str]] = []
            for row in root.findall(".//m:row", NS):
                values: dict[int, str] = {}
                for cell in row.findall("m:c", NS):
                    ref = cell.attrib.get("r", "A1")
                    values[col_number(ref)] = read_cell(cell, shared)
                if values:
                    rows.append([values.get(i, "") for i in range(1, max(values) + 1)])
            sections.append(f"### 工作表 {index}：{sheet_name}\n\n{markdown_table(rows)}")
    return "\n\n".join(sections) or "（空工作簿）"


def read_source(name: str) -> str:
    path = SOURCE_DIR / name
    if path.suffix.lower() == ".md":
        return path.read_text(encoding="utf-8")
    if path.suffix == ".xlsx":
        return read_xlsx(path)
    return read_docx(path)


def block(name: str, title: str | None = None) -> str:
    path = SOURCE_DIR / name
    heading = title or name
    return (f"## {heading}\n\n"
            f"> 来源文件：`{SOURCE_DIR.name}/{name}`\n> SHA-256（前12位）：`{source_hash(path)}`\n\n"
            f"{read_source(name)}")


def block_from_path(path: Path, source_label: str, title: str) -> str:
    """Build an auditable Markdown section from a source outside ``rules/`` too."""
    try:
        if path.suffix.lower() == ".md":
            content = path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"不支持的外部知识源: {path.name}")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"无法读取知识源 {path}") from exc
    return (f"## {title}\n\n"
            f"> 规则标识：`{source_label}`（服务端已静态注入，禁止在任务 sandbox 中查找源文件）\n"
            f"> SHA-256（前12位）：`{source_hash(path)}`\n\n"
            f"{content}")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


INTEGRATION_OUTPUT_SCHEMA = """# 智能消歧与整合输出文件字段契约

本文件是 Agent 生成消歧与整合结果 CSV 的固定字段规范。Ontology 后端会按
`execution-context.expectedFiles` 读取这些文件并导入；文件名、第一行表头和字段含义必须保持一致。

## 通用 CSV 要求

- 每个文件必须存在，即使没有记录也必须保留表头；但如果文件不在当前任务 `expectedFiles` 中，禁止创建或上传。
- 第一行必须是下面列出的完整表头，不要在表头之前增加标题、注释或空行。
- 使用 UTF-8 编码、逗号分隔；字段内含逗号、换行或双引号时按 CSV 规则使用双引号转义。
- 每行代表一条记录；不能把多条记录拼在一个字段中。多值字段（如“原名称集合”“来源模型”）使用 JSON 数组字符串，例如 `[\"RM001\",\"RM002\"]`。
- 空值留空，不要写 `None`、`undefined` 或 `********`。相似度使用 0 到 1 之间的小数。

## 本体元素结果文件

这些文件沿用《本体元模型模板 v0.0.1》的字段名称，字段顺序不能改变。

### `business_objects.csv`：业务对象

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 业务对象编码 | 是 | 整合后的稳定编码；已有本体库编码优先，否则选择保留编码 |
| 业务对象名称 | 是 | 整合后的业务对象名称 |
| 业务对象英文名 | 否 | 英文名称 |
| 业务对象定义 | 是 | 按规则写清定义、目的和范围 |
| 数据类别 | 否 | 数据/业务分类 |

### `logical_entities.csv`：逻辑实体

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 业务对象编码 | 是 | 所属业务对象编码 |
| 业务对象名称 | 是 | 所属业务对象名称 |
| 逻辑实体编码 | 是 | 整合后的稳定编码 |
| 逻辑实体名称 | 是 | 整合后的逻辑实体名称 |
| 逻辑实体英文名 | 否 | 英文名称 |
| 逻辑实体定义 | 是 | 按规则写清定义、目的和范围 |
| 是否主逻辑实体 | 是 | 统一使用 `Y` 或 `N`；每个业务对象必须且只能有一个 `Y` |
| 数据类别 | 否 | 数据/业务分类 |

### `business_attributes.csv`：业务属性

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 逻辑实体编码 | 是 | 所属逻辑实体编码 |
| 逻辑实体名称 | 是 | 所属逻辑实体名称 |
| 业务属性编码 | 是 | 整合后的稳定编码 |
| 业务属性名称 | 是 | 整合后的属性名称 |
| 业务属性英文名称 | 否 | 英文名称 |
| 业务属性定义 | 是 | 用“是指……”描述业务含义 |
| 数据类型 | 是 | 统一的数据类型名称 |
| 数据长度 | 否 | 来源明确时填写字段长度；无法取得时留空，不得猜测 |
| 数据精度 | 否 | 数值型字段来源明确时填写小数精度；不适用或无法取得时留空 |
| 是否物理主键 | 是 | 物理来源表主键；无明确物理主键信息时填 `N` |
| 是否逻辑主键 | 是 | 业务上唯一标识实体实例的属性；允许多个属性共同组成复合逻辑主键 |
| 是否唯一 | 是 | 表示业务上的唯一标识；属性能在业务范围内唯一识别实体实例时填 `Y`，否则填 `N` |
| 是否非空 | 是 | 统一使用 `Y` 或 `N` |
| 是否页面显示 | 是 | 逻辑实体同时存在 `XXX编码`（逻辑主键）和 `XXX名称` 时，`XXX名称` 为 `Y`；其他业务属性为 `N` |
| 是否层级编码 | 是 | 当前未实现维度输出，统一填 `N` |
| 是否层级名称 | 是 | 当前未实现维度输出，统一填 `N` |

### `entity_relations.csv`：实体关系

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 关系编码 | 是 | 稳定关系编码 |
| 源逻辑实体编码 | 是 | 关系源实体 |
| 源逻辑实体名称 | 是 | 关系源实体名称 |
| 目标逻辑实体编码 | 是 | 关系目标实体 |
| 目标逻辑实体名称 | 是 | 关系目标实体名称 |
| 关系分类 | 是 | 只能使用字典值 `关联`、`依赖`、`继承`、`组合`、`聚合` |
| 关系中文名称 | 是 | 正向关系名称 |
| 关系英文名称 | 否 | 正向关系英文名 |
| 关系基数 | 是 | 只能使用字典值 `1:1`、`1:N`、`N:1`、`M:N`；逻辑模型规范要求最终拆解 `M:N` |
| 反向关系中文名称 | 否 | 反向关系名称 |
| 反向关系英文名称 | 否 | 反向关系英文名 |
| 关系描述 | 是 | 关系语义和证据说明 |
| 源业务属性编码 | 否 | 源端业务属性，必须能在业务属性结果中找到 |
| 源关联属性英文名 | 否 | 源端属性英文名 |
| 源关联属性中文名 | 否 | 源端属性中文名 |
| 目标业务属性编码 | 否 | 目标端业务属性，必须能在业务属性结果中找到 |
| 目标关联属性英文名 | 否 | 目标端属性英文名 |
| 目标关联属性中文名 | 否 | 目标端属性中文名 |

关系分类和关系基数由服务端上传前校验，使用未定义值会被拒绝。

模板 v0.0.1 是结果 CSV 的最终字段契约；即使元模型的属性定义中存在其他字段，结果也不得自行增加模板没有的列。模板的“逻辑实体映射”和“业务属性映射”仅作为参考输入，不进入 expectedFiles，不生成对应结果文件。

### `business_object_relations.csv`：对象关系

表头：`关系编码,源业务对象编码,源业务对象名称,关系类型,关系英文名称,关系中文名名称,目标业务对象编码,目标业务对象名称,关系基数,关系描述`

关系类型只能使用模板和元模型声明的组合、聚合、分类、关联、依赖、隶属、等价等业务对象关系类型；源和目标业务对象编码必须引用当前结果或已有本体库中的稳定编码。

### `statuses.csv`：状态

表头：`业务对象编码,业务对象名称,状态编码,状态英文名,状态中文名,状态含义,触发条件,是否终态,是否主终态`

`是否终态`、`是否主终态` 使用 `Y/N`。`是否主终态=Y` 时必须同时满足 `是否终态=Y`；状态必须归属到明确的业务对象，证据不足时不得臆造生命周期。

### `events.csv`：事件

表头：`事件编码,事件名称,事件中文名称,事件含义,触发结果`

事件必须来自输入中的业务动作、状态变化、流程、消息或代码证据，不得把普通数据记录自动认定为事件。

### `business_rules.csv`：业务规则

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 规则编码 | 是 | 稳定规则编码；字段名以模板 v0.0.1 为准 |
| 规则名称 | 是 | 业务规则名称 |
| 规则描述 | 否 | 业务规则总体说明 |
| 触发条件 | 是 | 启动规则执行的前置场景或条件 |
| 判断或结果 | 是 | 条件校验后的逻辑结论 |
| 处置动作 | 是 | 规则判断后执行的业务操作 |

元模型、模板和含样例数据模板统一使用“规则编码”。新增规则必须使用 `R` + 7 位流水码，例如 `R0000001`。

## 消歧整合报告文件

这些文件对应《智能消歧与整合模板》的五类工作表，字段名必须按模板保留。

### `integration_report.csv`：总体检核报告

表头：`检核项,问题类型,涉及源模型,处理结果,说明`

- `检核项`：一致性、完整性或正确性检查项。
- `问题类型`：同名不同义、同义不同名、同名同义、缺失、冲突等。
- `涉及源模型`：涉及的模型任务编码或来源文件；多值用 JSON 数组。
- `处理结果`：已合并、已修正、待确认、冲突、缺失或无需处理。
- `说明`：判断依据、证据和后续动作。

### `merged_elements.csv`：已合并元素

表头：`整合后名称,元素类型,原名称集合,来源模型,合并策略,相似度`

`元素类型` 使用 `BUSINESS_OBJECT`、`LOGICAL_ENTITY`、`BUSINESS_ATTRIBUTE`、`ENTITY_RELATION`、`RULE` 等枚举；`原名称集合` 和 `来源模型` 为 JSON 数组；`合并策略` 写明保留编码/推荐名称等处理；必须有语义或结构证据支持合并。

新版元素还可以使用 `BUSINESS_OBJECT_RELATION`、`STATUS`、`EVENT`；这些类型的正式结果分别使用 `business_object_relations.csv`、`statuses.csv`、`events.csv`，并接受 execution-context 明确给出的兼容文件名。

### `pending_elements.csv`：待人工确认元素

表头：`候选名称 A,候选名称 B,推荐名称,元素类型,来源模型,相似度,待确认原因`

相似但证据不足、不能自动合并的候选必须放在这里，不得强行写入 `merged_elements.csv`。

### `conflict_elements.csv`：冲突元素

表头：`元素名称,冲突类型,来源模型,冲突描述,来源内容`

记录同名不同义、定义冲突、类型/长度冲突、主键或关系冲突等；`来源内容` 保留可追溯的原始定义或字段摘要。

### `missing_elements.csv`：缺失元素

表头：`元素名称,元素类型,来源模型,缺失说明`

记录业务对象缺少逻辑实体、逻辑实体缺少主键/业务属性/关系等完整性问题；不能用虚构数据填充缺失项。

## 生成前后校验

生成后必须逐个检查当前任务 `expectedFiles` 中的文件：文件存在、表头精确匹配、CSV 可解析、编码稳定、记录数真实。最后创建 `ok.csv` 作为整合完成标记；只有所有 expectedFiles 已生成并验证后，才允许上传 `ok.csv` 并回写完成状态。
"""


BASE_REFERENCE_SOURCES = [
    "Ontology平台模型编码规范v0.0.1.xlsx",
    "本体元模型v0.0.1.xlsx",
    "本体元模型模板v0.0.1.xlsx",
    "数据模型建模规范v0.0.1.xlsx",
]
MISSION_REFERENCE_SOURCES = [
    "Ontology平台模型编码规范v0.0.1.xlsx",
    "本体元模型v0.0.1.xlsx",
    "本体元模型模板v0.0.1.xlsx",
    "本体元模型模板v0.0.1（含样例数据）.xlsx",
]
DATA_MODELING_STANDARD_FILENAME = "数据模型建模规范v0.0.1.md"
ENCODING_STANDARD_FILENAME = "Ontology平台模型编码规范v0.0.1.md"
V6_STANDARD_FILENAME = "通用业务对象与逻辑实体识别规范v0.0.1.md"
V6_STANDARD_PATH = OUTPUT_DIR / V6_STANDARD_FILENAME
SOURCE_DOCS = {
    "source_code": "源代码本体建模v0.0.1.docx",
    "system_page": "系统页面本体建模v0.0.1.docx",
    "business_document": "业务文档本体建模v0.0.1.docx",
    "multi_source_data": "多源数据建模v0.0.1.docx",
    "natural_language": "自然语言本体建模v0.0.1.docx",
}

DOCUMENT_OUTPUT_CONTRACT = """## 文档建模输入与输出契约

`DOCUMENT_MODELING` 任务会把 DOCX、PPTX、PDF 下载到当前任务的 `mission-input/`，由服务端为每个原文件生成 `manifest.json`、`content.md` 和 `tables/*.csv`。必须先读取 manifest，再完整读取正文、全部章节/页和全部表格；证据引用必须包含文件名以及章节或页码。

文档中的业务语义按 `parseElement` 选择输出，文件名不能自行改名或扩展：

| parseElement | 规范输出文件 | 层级与依赖 |
| --- | --- | --- |
| `TERM` | `business_terms.csv`（兼容 `terms.csv`） | 独立，可单独执行 |
| `LOGICAL_ENTITY` | `logical_entities.csv` | 逻辑模型；正式业务属性和实体关系之前 |
| `BUSINESS_ATTRIBUTE` | `business_attributes.csv` | 必须归属已识别逻辑实体 |
| `ENTITY_RELATION` | `entity_relations.csv` | 必须引用已归属实体和属性 |
| `BUSINESS_OBJECT` | `business_objects.csv` | 必须先完成逻辑实体、正式业务属性、实体关系 |
| `BUSINESS_OBJECT_RELATION` | `business_object_relations.csv` | 业务对象之间的对象关系，可独立导出但引用的业务对象必须存在 |
| `STATUS` | `statuses.csv` | 业务对象生命周期状态，可独立导出但必须明确归属业务对象 |
| `EVENT` | `events.csv` | 业务事件，可独立导出且必须有动作、流程、消息或状态变化证据 |
| `RULE` | `business_rules.csv`（兼容 `rules.csv`） | 必须引用已完成业务对象 |
| `METRIC` | `metrics.csv`（兼容 `indicator.csv`） | 必须引用已完成业务对象 |
| `ACTIVITY` | `activities.csv` | 仅在 execution-context 声明时输出 |
| `ACTIVITY_FLOW` | `activity_flows.csv`（兼容 `activity_flow.csv`） | 仅在 execution-context 声明时输出 |

只生成并上传 execution-context 的 `expectedFiles` 中列出的文件。各结果文件可以独立导出；共享分析结果统一写入任务目录的 `mission-work/modeling_state.json`，不得把 `mission-output` 中的正式文件当作识别输入。未选择的解析要素不得因文档内容丰富而额外生成文件。"""

LAYERED_MODELING_ARTIFACTS = """## 分层建模与任务级中间态

建模结果不是必须全部成套导出的平面任务，必须按服务端提供的 `modelingPlan` 执行。计划身份固定为：
`repositoryId + taskCode + modelVersion + inputFingerprint`。不同身份的输入、证据和结果文件禁止混用。

```text
TERM ─────────────────────────────── 独立，可单独执行

候选业务属性 → 逻辑实体 → 正式业务属性 → 实体关系
                                      ↓ 校验通过
                       实体族 → 候选主实体 → R1–R5
                                      ↓
                  CONFIRMED / CANDIDATE / REJECTED 业务对象
                                      ↓ 已完成业务对象
                         RULE        METRIC
```

每个 artifact 都可以在单独请求时独立导出。先把当前输入的资产盘点、候选属性、实体、关系、业务对象、术语、规则、指标候选、证据和校验结果写入任务目录的 `mission-work/modeling_state.json`，再从中导出当前 `parseElements` 选择的正式文件。这个中间态不是正式结果，不上传，不放入 `mission-output`，也不记录隐藏思维链。

- `parseElements` 是唯一的识别范围；`expectedFiles` 只约束具体文件名和上传白名单，不能反向选择建模要素；
- 同一任务请求多个类型时可以复用中间态，但不得创建未选择的正式文件；
- 业务对象、规则和指标的业务判断仍要遵循 V6 的证据和校验规则，但不因其他类型 CSV 尚未生成而阻止当前独立导出。
"""

PAGE_DISPLAY_RULES = """## 业务属性字段规则

`business_attributes.csv` 必须严格使用本体元模型模板 v0.0.1 的字段顺序，包含新增的 `数据长度` 和 `数据精度`，布尔字段统一使用 `Y/N`：

`logical_entities.csv` 的 `是否主逻辑实体` 也统一使用 `Y/N`，每个业务对象必须且只能有一个 `Y`。

- `是否物理主键` 仅表示来源物理表主键；没有明确物理主键信息时填 `N`，不能据此判断业务身份。
- `是否逻辑主键` 表示业务上唯一标识实体实例的属性；允许多个属性共同组成复合逻辑主键。
- `是否唯一` 表示业务上的唯一标识；属性能在业务范围内唯一识别实体实例时填 `Y`，否则填 `N`，不得仅凭属性名称猜测。
- 复合业务唯一标识必须保留组成属性和组合关系；模板没有唯一组编号时，不得把复合唯一误写成每个单字段都单独唯一，应在执行审计中说明。
- `是否层级编码` 和 `是否层级名称` 当前全部填 `N`；当前不生成维度、层级或钻取映射结果。
- 当同一逻辑实体存在 `XXX编码`（且为逻辑主键）和 `XXX名称` 两个业务属性时，将 `XXX名称` 的 `是否页面显示` 设置为 `Y`。
- 其他所有业务属性的 `是否页面显示` 设置为 `N`，不得留空或使用其他枚举。
- `XXX编码` 与 `XXX名称` 必须属于同一逻辑实体；仅有编码或仅有名称时，不触发页面显示，全部使用 `N`。
"""

V001_ELEMENT_RULES = """## 元模型 v0.0.1 新增元素规则

### 数据长度与数据精度

- `数据长度`、`数据精度` 只记录输入结构、数据库元数据、接口 Schema 或受控文档中明确给出的值；不得依据样例值长度反推定义长度。
- 字符串和定长类型填写声明长度；整数、日期等没有独立精度概念时 `数据精度` 留空；DECIMAL/NUMERIC 按来源声明填写总长度和小数精度。
- 多来源合并且长度或精度冲突时保留冲突证据并进入待确认，不能任取最大值后假装一致。

### 对象关系

- 对象关系连接业务对象，实体关系连接逻辑实体，两者不得混用。只有源、目标均为已确认或已有稳定业务对象时，才生成正式对象关系。
- 关系证据优先取业务流程、生命周期交接、受控业务文档、对象级引用与治理关系；普通外键只能证明实体关系，不能单独证明对象关系。
- `关系类型` 只能使用组合、聚合、分类、关联、依赖、隶属、等价及模板允许的带“关系”后缀形式；证据不足时进入待确认，不得为了消除孤岛强造关系。
- `关系编码` 沿用编码规范中的 `REL` + 6 位流水码；关联的业务对象编码必须引用已有或本次生成的稳定编码。

### 状态

- 状态必须归属到明确业务对象。来源优先为状态字段及码表、状态机/流转配置、流程节点、代码枚举、事件日志和受控文档。
- 普通类型、分类、布尔标志和处理结果不是生命周期状态；只有能表达业务对象阶段性处境且可由业务操作、时间或事件驱动变化时，才识别为状态。
- `是否终态=Y` 表示正常流转不再继续；`是否主终态=Y` 必须同时满足 `是否终态=Y`。取消、作废等次要终态不能仅因无后续记录自动判为主终态。
- 状态编码优先沿用来源稳定编码。编码规范 v0.0.1 未声明状态新编码格式，无稳定来源时标记待确认，禁止自定义前缀。

### 事件

- 事件是业务执行过程中已发生或可明确触发的关键动作节点，应有动作、消息、流程、审计日志、状态变化或系统同步证据，并能说明触发结果。
- 普通数据行、静态属性、状态值本身不是事件；“状态发生变化”的动作可以是事件，变化后的状态仍应写入状态结果。
- `事件名称` 按元模型含义填写标准英文名称，`事件中文名称` 填业务中文名；没有可靠英文名称时留空并待确认，不得用拼音替代。
- 事件编码优先沿用来源稳定编码。编码规范 v0.0.1 未声明事件新编码格式，无稳定来源时标记待确认，禁止照抄样例的 `E` 前缀。

### 业务规则六列映射

- 正式业务规则按 `规则编码,规则名称,规则描述,触发条件,判断或结果,处置动作` 输出；详细形式化表达、校验 SQL、证据、强度和置信度留在任务中间态与执行审计。
- `触发条件` 对应 WHEN/ON/IF 前置条件，`判断或结果` 对应校验结论或推导结果，`处置动作` 对应 THEN 后续动作；来源只表达约束但没有处置动作时不得臆造，应标记待确认。
- 元模型、模板和样例统一使用“规则编码”；编码使用 `R` + 7 位流水码。
"""

CODE_STANDARD_RULES = """## 本体平台模型编码规范（强制）

所有结果文件中的元素自身编码必须遵循《Ontology平台模型编码规范v0.0.1.xlsx》。编码前缀和流水号位数如下：

| 模型元素 | 编码格式 | 示例 |
| --- | --- | --- |
| 术语 | `T` + 6 位流水码，位数不足左侧补 `0` | `T000008` |
| 业务对象 | `BO` + 5 位流水码，位数不足左侧补 `0` | `BO0005` |
| 逻辑实体 | `LE` + 6 位流水码，位数不足左侧补 `0` | `LE000020` |
| 业务属性 | `AT` + 7 位流水码，位数不足左侧补 `0` | `AT0000839` |
| 实体关系 | `REL` + 6 位流水码，位数不足左侧补 `0` | `REL000006` |
| 指标 | `M` + 4 位流水码，位数不足左侧补 `0` | `M0012` |
| 业务规则 | `R` + 7 位流水码，位数不足左侧补 `0` | `R0000001` |

执行要求：

- 规范只约束元素自身编码；业务对象编码、逻辑实体编码、业务属性编码等关联字段必须引用已生成或已存在的对应编码，不能重新拼接或改写。
- 已有本体库编码、输入资产中已有编码和整合任务中需要保留的稳定编码优先沿用，不得仅因名称调整或跨模型合并而随意重编。
- 新增元素按元素类型使用对应前缀和固定流水位数，流水号不足位数时左侧补零；不得使用临时名称、数据库自增 ID、随机字符串或其他前缀替代。
- 新增编码必须避开当前任务和已有本体库中同类型已占用的编码；合并时应保留被选中的稳定编码，并在执行审计中说明编码沿用或新增依据。
- 生成前后都要检查编码前缀、总长度、流水号格式、同类型唯一性以及所有关联字段是否能在对应结果文件中找到；不符合时不得宣称结果校验通过。
- 该规范不改变 V6 的业务语义判定、实体关系分类、业务对象聚合或模板字段顺序；它只规定编码格式和编码沿用/新增约束。
- 对象关系复用关系编码格式 `REL` + 6 位流水码。新版编码规范尚未声明状态编码和事件编码格式：有稳定来源编码时原样沿用；没有时必须标记待确认，禁止自行规定 `S`/`E` 前缀或随机生成。
- 元模型、模板和样例的业务规则列名统一为“规则编码”，并统一使用 `R` + 7 位流水码。
"""


def build() -> None:
    write(OUTPUT_DIR / "README.md", f"""# Agent 静态知识库 {KNOWLEDGE_VERSION}

本目录是给 Ontology Agent 使用的静态 Markdown 知识库，由 `{SOURCE_DIR.name}/` 中的产品目标、规则文档和 Excel 规则表离线生成。

## 使用方式

- 运行服务只读取已经生成的 Markdown，不会在服务器实时解析 DOCX/XLSX，也不会修改本目录。
- `integration/all_sourcesv0.0.1.md` 是智能消歧与整合的运行时知识；其规则、模板和输出契约分文件也统一使用 `v0.0.1`。
- `modeling/basev0.0.1.md` 用于所有智能建模任务；各输入源专项 Markdown 也统一使用 `v0.0.1`，运行时按需拼接。
- `modeling/本体元模型v0.0.1.md`、`modeling/本体元模型模板v0.0.1.md` 和 `modeling/本体元模型模板v0.0.1（含样例数据）.md` 是当前建模参考。
- 每个任务固定输入四份 `v0.0.1` 参考：编码规范、元模型、模板和含样例数据模板；旧版本只保留历史，不再复制到新任务。
- 含样例数据模板只用于理解字段填写示例；样例行不是当前任务真实数据，且样例编码与编码规范冲突时以编码规范为准。
- `modeling/通用业务对象与逻辑实体识别规范v0.0.1.md` 是所有建模任务唯一的核心判定规范。
- `modeling/Ontology平台模型编码规范v0.0.1.md` 是建模和消歧整合共同使用的编码规范。
- `modeling/数据模型建模规范v0.0.1.md` 已编入公共知识，不能覆盖核心判定规范。
- 根目录的 `业务术语v0.0.1.md`、`业务规则v0.0.1.md`、`指标v0.0.1.md` 按 `parseElements` 动态加载。
- 服务端会为每个建模任务生成 `modelingPlan`，并在任务目录的 `mission-work/modeling_state.json` 保存可复用的结构化中间态；正式输出只写入 `mission-output`，各选中类型可独立导出。
- 未带 `v0.0.1` 的生成文件和旧版源文件只作为历史参考，不作为当前运行时入口。
- 规则源文件变更后，在本地执行 `python scripts/build_agent_knowledge.py`，检查 Markdown 差异，再提交并部署。

## 安全边界

这些文件只作为服务端 Agent 的私有 system prompt 输入，不复制到任务 sandbox，不通过网页文件树展示，也不应在用户对话中复述原文。
""")

    v6 = block_from_path(V6_STANDARD_PATH, V6_STANDARD_FILENAME, V6_STANDARD_FILENAME)
    references = "\n\n".join(block(x) for x in BASE_REFERENCE_SOURCES)
    base = ("# 智能建模任务：静态私有知识\n\n"
            "## 当前规范优先级\n\n"
            "`通用业务对象与逻辑实体识别规范v0.0.1.md` 是所有建模任务唯一的核心判定规范。"
            "业务属性识别与归属、逻辑实体识别、关系分类、实体族聚合、候选主实体、R1–R5、UNKNOWN、冲突处理和一致性校验"
            "必须严格按 V6 执行。历史规则、示例和来源专项说明只能补充输入提取、字段映射或模板，"
            "不得改变或覆盖 V6 的结论、枚举和判定流程。\n\n"
            + LAYERED_MODELING_ARTIFACTS.rstrip() + "\n\n" + PAGE_DISPLAY_RULES.rstrip() + "\n\n"
            + V001_ELEMENT_RULES.rstrip() + "\n\n"
            + CODE_STANDARD_RULES.rstrip() + "\n\n" + v6
            + "\n\n## 本体元模型与结果模板参考\n\n" + references)
    write(OUTPUT_DIR / "modeling" / "basev0.0.1.md", base)
    write(OUTPUT_DIR / "modeling" / "本体元模型v0.0.1.md",
          "# 本体元模型 v0.0.1：静态 Markdown\n\n" + block("本体元模型v0.0.1.xlsx"))
    write(OUTPUT_DIR / "modeling" / ENCODING_STANDARD_FILENAME,
          "# Ontology 平台模型编码规范 v0.0.1：静态 Markdown\n\n" + block("Ontology平台模型编码规范v0.0.1.xlsx"))
    write(OUTPUT_DIR / "modeling" / "本体元模型模板v0.0.1.md",
          "# 本体元模型模板 v0.0.1：静态 Markdown\n\n" + block("本体元模型模板v0.0.1.xlsx"))
    write(OUTPUT_DIR / "modeling" / "本体元模型模板v0.0.1（含样例数据）.md",
          "# 本体元模型模板 v0.0.1（含样例数据）：静态 Markdown\n\n" + block("本体元模型模板v0.0.1（含样例数据）.xlsx"))
    write(OUTPUT_DIR / "modeling" / DATA_MODELING_STANDARD_FILENAME,
          "# 数据模型建模规范 v0.0.1：静态 Markdown\n\n"
          + block("数据模型建模规范v0.0.1.xlsx"))
    write(OUTPUT_DIR / "modeling" / V6_STANDARD_FILENAME,
          "# 通用业务对象与逻辑实体识别规范 V6：运行时静态 Markdown\n\n"
          + v6)
    # 专项文件只保存对应输入源的规则，不重复复制公共建模规范。
    # 运行时由 ontology_knowledge.load_static_knowledge() 按需拼接 base.md。
    document_rules = block("业务文档本体建模.docx") + "\n\n" + DOCUMENT_OUTPUT_CONTRACT
    all_parts = [base] + [document_rules if name == SOURCE_DOCS["business_document"] else block(name)
                           for name in SOURCE_DOCS.values()]
    write(OUTPUT_DIR / "modeling" / "all_sourcesv0.0.1.md",
          "# 智能建模任务：全部输入源静态私有知识\n\n" + "\n\n".join(all_parts))
    for key, name in SOURCE_DOCS.items():
        write(OUTPUT_DIR / "modeling" / f"{key}v0.0.1.md",
              f"# 智能建模任务：{name}专项静态私有知识\n\n"
              f"{document_rules if key == 'business_document' else block(name)}")

    integration_base = "# 智能消歧与整合：目标与规则\n\n" + "\n\n".join(
        block(x) for x in ("智能消歧与整合v0.0.1.docx", "智能消歧与整合规则v0.0.1.docx"))
    integration_base += ("\n\n" + V001_ELEMENT_RULES.rstrip() + "\n\n"
                         + CODE_STANDARD_RULES.rstrip() + "\n\n"
                         + block("Ontology平台模型编码规范v0.0.1.xlsx"))
    integration_template = "# 智能消歧与整合模板 v0.0.1：静态 Markdown\n\n" + block("智能消歧与整合模板v0.0.1.xlsx")
    integration_template += "\n\n" + INTEGRATION_OUTPUT_SCHEMA
    write(OUTPUT_DIR / "integration" / "basev0.0.1.md", integration_base)
    write(OUTPUT_DIR / "integration" / "templatev0.0.1.md", integration_template)
    write(OUTPUT_DIR / "integration" / "output_schemav0.0.1.md",
          INTEGRATION_OUTPUT_SCHEMA)
    write(OUTPUT_DIR / "integration" / "all_sourcesv0.0.1.md",
          "# 智能消歧与整合：全部静态私有知识\n\n" + integration_base
          + "\n\n---\n\n" + integration_template)


if __name__ == "__main__":
    build()
    print(f"generated static knowledge under {OUTPUT_DIR}")
