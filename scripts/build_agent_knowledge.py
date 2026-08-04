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

这些文件沿用《本体元模型模板》的字段名称，字段顺序不能改变。

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
| 是否主逻辑实体 | 是 | 统一使用 `是` 或 `否`；每个业务对象必须且只能有一个 `是` |
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
| 是否主键 | 是 | 统一使用 `是` 或 `否` |
| 是否非空 | 是 | 统一使用 `是` 或 `否` |

### `entity_relations.csv`：实体关系

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 关系编码 | 是 | 稳定关系编码 |
| 源逻辑实体编码 | 是 | 关系源实体 |
| 源逻辑实体名称 | 是 | 关系源实体名称 |
| 目标逻辑实体编码 | 是 | 关系目标实体 |
| 目标逻辑实体名称 | 是 | 关系目标实体名称 |
| 关系分类编码 | 否 | 关系分类编码 |
| 关系分类 | 是 | 只能使用字典值 `关联`、`依赖`、`继承`、`组合`、`聚合` |
| 关系中文名称 | 是 | 正向关系名称 |
| 关系英文名称 | 否 | 正向关系英文名 |
| 关系基数 | 是 | 只能使用字典值 `1:1`、`1:N`、`N:1`、`M:N`；逻辑模型规范要求最终拆解 `M:N` |
| 反向关系中文名称 | 否 | 反向关系名称 |
| 反向关系英文名称 | 否 | 反向关系英文名 |
| 关系描述 | 是 | 关系语义和证据说明 |
| 源关联属性编码 | 否 | 源端关联属性，必须能在业务属性结果中找到 |
| 源关联属性英文名 | 否 | 源端属性英文名 |
| 源关联属性中文名 | 否 | 源端属性中文名 |
| 目标关联属性编码 | 否 | 目标端关联属性 |
| 目标关联属性英文名 | 否 | 目标端属性英文名 |
| 目标关联属性中文名 | 否 | 目标端属性中文名 |

`关系分类编码` 必须沿用输入模型或本体库已有编码，不能把 `1:N`、中文分类名或自造英文单词填入该列；没有可追溯编码时留空并在报告中说明。关系分类和关系基数由服务端上传前校验，使用未定义值会被拒绝。

### `business_rules.csv`：业务规则

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| 规则编码 | 是 | 稳定规则编码 |
| 规则名称 | 是 | 业务规则名称 |
| 分类 | 是 | 规则分类，例如约束规则、流程规则 |
| 规则描述 | 是 | 可验证的业务约束或判断条件 |
| 来源内容 | 是 | 来源模型、文件、页面、代码位置等证据摘要；多个来源合并到同一字段 |

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
    "本体元模型.xlsx",
    "本体元模型模板.xlsx",
]
V6_STANDARD_FILENAME = "通用业务对象与逻辑实体识别规范_V6.md"
V6_STANDARD_PATH = OUTPUT_DIR / V6_STANDARD_FILENAME
SOURCE_DOCS = {
    "source_code": "源代码本体建模.docx",
    "system_page": "系统页面本体建模.docx",
    "business_document": "业务文档本体建模.docx",
    "multi_source_data": "多源数据建模.docx",
    "natural_language": "自然语言本体建模.docx",
}

LAYERED_MODELING_ARTIFACTS = """## 分层建模与 artifact 依赖

建模不是可以任意组合的平面任务，必须按服务端提供的 `modelingPlan` 执行。计划身份固定为：
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

对应 artifact 必须保持以下依赖：

- `termArtifact` 独立，不依赖逻辑模型或业务对象；
- `logicalModelArtifact` 内部严格按候选属性、逻辑实体、正式业务属性、实体关系顺序执行；
- `businessObjectArtifact` 必须引用已校验的 `logicalModelArtifact`，并保留实体族、候选主实体、R1–R5 和三类业务对象结论；
- `ruleArtifact` 和 `metricArtifact` 都必须引用已完成的 `businessObjectArtifact`，二者彼此独立；
- 同一任务同时请求多层时，先写入并校验上游 artifact，再进入下游；历史上游结果必须通过 execution-context 的已完成 artifact 引用接入；
- 缺少依赖时禁止生成下游 CSV，也不得把待确认或驳回结果伪装成已完成 artifact。
"""


def build() -> None:
    write(OUTPUT_DIR / "README.md", f"""# Agent 静态知识库

本目录是给 Ontology Agent 使用的静态 Markdown 知识库，由 `{SOURCE_DIR.name}/` 中的产品目标、规则文档和 Excel 规则表离线生成。

## 使用方式

- 运行服务只读取已经生成的 Markdown，不会在服务器实时解析 DOCX/XLSX，也不会修改本目录。
- `integration/` 用于智能消歧与整合：`base.md` 是目标和规则，`template.md` 是 Excel 模板，`output_schema.md` 是十类结果 CSV 的字段契约，`all_sources.md` 是组合后的 system prompt 知识。
- `modeling/base.md` 用于所有智能建模任务；各 `modeling/*.md` 文件只保存对应输入源的专项规则，运行时由 Agent 加载器按需拼接公共规则和专项规则，避免重复复制。
- `modeling/本体元模型.md`、`modeling/本体元模型模板.md` 和 `modeling/本体建模步骤拆解.md` 是建模参考 Markdown；同样内容也已编入 `modeling/base.md`，由 modeling system prompt 静态注入 Agent。
- `modeling/通用业务对象与逻辑实体识别规范_V6.md` 是所有建模任务唯一的核心判定规范：业务属性、逻辑实体、关系分类、实体族、业务对象 R1–R5、UNKNOWN/冲突和一致性校验均以 V6 为准。
- 根目录的 `业务术语.md`、`业务规则.md`、`指标.md` 是按解析要素动态加载的建模专项技能；任务的 `parseElements` 包含 `TERM`、`RULE`、`METRIC`（或其对应的结果文件）时，加载器会在 V6 与输入源专项规则后追加对应技能；未选择的技能不会注入，也不得生成额外结果文件。
- 服务端会为每个建模任务生成 `modelingPlan`：以 `repositoryId + taskCode + modelVersion + inputFingerprint` 隔离 `termArtifact`、`logicalModelArtifact`、`businessObjectArtifact`、`ruleArtifact` 和 `metricArtifact`，并在 Agent 执行前校验层级依赖。
- `modeling/数据模型建模规范-20260626.md`、`modeling/本体建模步骤拆解.md` 和 `modeling/自底向上业务对象识别规范_v3.md` 保留为历史参考，不再作为运行时建模判定依据。
- 规则源文件变更后，在本地执行 `python scripts/build_agent_knowledge.py`，检查 Markdown 差异，再提交并部署。

## 安全边界

这些文件只作为服务端 Agent 的私有 system prompt 输入，不复制到任务 sandbox，不通过网页文件树展示，也不应在用户对话中复述原文。
""")

    v6 = block_from_path(V6_STANDARD_PATH, V6_STANDARD_FILENAME, V6_STANDARD_FILENAME)
    references = "\n\n".join(block(x) for x in BASE_REFERENCE_SOURCES)
    base = ("# 智能建模任务：静态私有知识\n\n"
            "## 当前规范优先级\n\n"
            "`通用业务对象与逻辑实体识别规范_V6.md` 是所有建模任务唯一的核心判定规范。"
            "业务属性识别与归属、逻辑实体识别、关系分类、实体族聚合、候选主实体、R1–R5、UNKNOWN、冲突处理和一致性校验"
            "必须严格按 V6 执行。历史规则、示例和来源专项说明只能补充输入提取、字段映射或模板，"
            "不得改变或覆盖 V6 的结论、枚举和判定流程。\n\n"
            + LAYERED_MODELING_ARTIFACTS.rstrip() + "\n\n" + v6
            + "\n\n## 本体元模型与结果模板参考\n\n" + references)
    write(OUTPUT_DIR / "modeling" / "base.md", base)
    write(OUTPUT_DIR / "modeling" / "本体元模型.md",
          "# 本体元模型：静态 Markdown\n\n" + block("本体元模型.xlsx"))
    write(OUTPUT_DIR / "modeling" / "本体元模型模板.md",
          "# 本体元模型模板：静态 Markdown\n\n" + block("本体元模型模板.xlsx"))
    write(OUTPUT_DIR / "modeling" / "本体建模步骤拆解.md",
          "# 本体建模步骤拆解：静态 Markdown\n\n" + block("本体建模步骤拆解.xlsx"))
    write(OUTPUT_DIR / "modeling" / "数据模型建模规范-20260626.md",
          "# 数据模型建模规范-20260626：静态 Markdown\n\n"
          + block("数据模型建模规范-20260626.xlsx"))
    write(OUTPUT_DIR / "modeling" / "自底向上业务对象识别规范_v3.md",
          "# 自底向上业务对象识别与逻辑实体聚合规范 V3：静态 Markdown\n\n"
          + block("自底向上业务对象识别规范_v3.md"))
    write(OUTPUT_DIR / "modeling" / V6_STANDARD_FILENAME,
          "# 通用业务对象与逻辑实体识别规范 V6：运行时静态 Markdown\n\n"
          + v6)
    # 专项文件只保存对应输入源的规则，不重复复制公共建模规范。
    # 运行时由 ontology_knowledge.load_static_knowledge() 按需拼接 base.md。
    all_parts = [base] + [block(name) for name in SOURCE_DOCS.values()]
    write(OUTPUT_DIR / "modeling" / "all_sources.md",
          "# 智能建模任务：全部输入源静态私有知识\n\n" + "\n\n".join(all_parts))
    for key, name in SOURCE_DOCS.items():
        write(OUTPUT_DIR / "modeling" / f"{key}.md",
              f"# 智能建模任务：{name}专项静态私有知识\n\n{block(name)}")

    integration_base = "# 智能消歧与整合：目标与规则\n\n" + "\n\n".join(
        block(x) for x in ("智能消歧与整合.docx", "智能消歧与整合规则v0.1.docx"))
    integration_template = "# 智能消歧与整合模板：静态 Markdown\n\n" + block("智能消歧与整合模板.xlsx")
    integration_template += "\n\n" + INTEGRATION_OUTPUT_SCHEMA
    write(OUTPUT_DIR / "integration" / "base.md", integration_base)
    write(OUTPUT_DIR / "integration" / "template.md", integration_template)
    write(OUTPUT_DIR / "integration" / "output_schema.md",
          INTEGRATION_OUTPUT_SCHEMA)
    write(OUTPUT_DIR / "integration" / "all_sources.md",
          "# 智能消歧与整合：全部静态私有知识\n\n" + integration_base
          + "\n\n---\n\n" + integration_template)


if __name__ == "__main__":
    build()
    print(f"generated static knowledge under {OUTPUT_DIR}")
