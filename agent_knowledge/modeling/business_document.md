# 智能建模任务：业务文档本体建模.docx专项静态私有知识

## 业务文档本体建模.docx

> 来源文件：`rules/业务文档本体建模.docx`
> SHA-256（前12位）：`502e0ef02518`

5.4 业务文档建模

5.4.1 功能描述

面向业务规范完善、暂无完整落地数据的场景，通过大模型深度解析业务制度、需求文档、流程手册、规范文件，从业务语义层面自上而下抽取核心业务概念、属性、关联关系、业务规则、业务流程，构建贴合业务诉求的本体体系，解决纯数据建模缺失业务语义、脱离业务流程的问题。

5.4.2 支持文档类型

WPS文档：Word/PPT/VISIO 业务需求文档、流程图

PDF文档：业务规范、制度文件、行业标准文档、业务手册

文本文件：TXT业务说明、流程描述文档

电子表格文件：Excel电子表格设计的流程活动、业务规则等文档

5.4.3 核心解析生成规则

从文档业务概念、核心对象中抽取标准逻辑实体（如用户、套餐、订单、设备等）

从对象特征、业务描述中提炼业务属性及属性释义

自动识别或者补充逻辑实体的业务主键

从业务流程、业务关联描述中挖掘实体关系，定义业务联动逻辑

从逻辑实体中提炼、聚合业务对象，提炼业务对象关系

从管理办法、流程文档中提炼活动、活动流图

从业务限制、管理规范中提取业务规则与约束条件

自动剔除文档冗余话术、无效描述、格式内容，聚焦核心业务语义，保证本体精准贴合业务诉求

支持长文档分段解析、多文档合并建模，适配复杂业务体系构建场景

## 文档建模输入与输出契约

`DOCUMENT_MODELING` 任务会把 DOCX、PPTX、PDF 下载到当前任务的 `mission-input/`，由服务端为每个原文件生成 `manifest.json`、`content.md` 和 `tables/*.csv`。必须先读取 manifest，再完整读取正文、全部章节/页和全部表格；证据引用必须包含文件名以及章节或页码。

文档中的业务语义按 `parseElement` 选择输出，文件名不能自行改名或扩展：

| parseElement | 规范输出文件 | 层级与依赖 |
| --- | --- | --- |
| `TERM` | `business_terms.csv`（兼容 `terms.csv`） | 独立，可单独执行 |
| `LOGICAL_ENTITY` | `logical_entities.csv` | 逻辑模型；正式业务属性和实体关系之前 |
| `BUSINESS_ATTRIBUTE` | `business_attributes.csv` | 必须归属已识别逻辑实体 |
| `ENTITY_RELATION` | `entity_relations.csv` | 必须引用已归属实体和属性 |
| `BUSINESS_OBJECT` | `business_objects.csv` | 必须先完成逻辑实体、正式业务属性、实体关系 |
| `RULE` | `business_rules.csv`（兼容 `rules.csv`） | 必须引用已完成业务对象 |
| `METRIC` | `metrics.csv`（兼容 `indicator.csv`） | 必须引用已完成业务对象 |
| `ACTIVITY` | `activities.csv` | 仅在 execution-context 声明时输出 |
| `ACTIVITY_FLOW` | `activity_flows.csv`（兼容 `activity_flow.csv`） | 仅在 execution-context 声明时输出 |

只生成并上传 execution-context 的 `expectedFiles` 中列出的文件。业务对象、规则和指标不能绕过前置 artifact；未选择的解析要素不得因文档内容丰富而额外生成文件。
