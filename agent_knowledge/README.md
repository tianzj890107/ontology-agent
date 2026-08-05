# Agent 静态知识库

本目录是给 Ontology Agent 使用的静态 Markdown 知识库，由 `rules/` 中的产品目标、规则文档和 Excel 规则表离线生成。

## 使用方式

- 运行服务只读取已经生成的 Markdown，不会在服务器实时解析 DOCX/XLSX，也不会修改本目录。
- `integration/` 用于智能消歧与整合：`base.md` 是目标和规则，`template.md` 是 Excel 模板，`output_schema.md` 是十类结果 CSV 的字段契约，`all_sources.md` 是组合后的 system prompt 知识。
- `modeling/base.md` 用于所有智能建模任务；各 `modeling/*.md` 文件只保存对应输入源的专项规则，运行时由 Agent 加载器按需拼接公共规则和专项规则，避免重复复制。
- `modeling/本体元模型2.md`、`modeling/本体元模型模板 2.md` 和 `modeling/本体建模步骤拆解.md` 是当前建模参考 Markdown；同样内容也已编入 `modeling/base.md`，由 modeling system prompt 静态注入 Agent。
- 每个任务固定输入文件为 `本体元模型2.xlsx` 和 `本体元模型模板 2.xlsx`；旧版 `本体元模型.xlsx`、`本体元模型模板.xlsx` 仅保留为历史参考，不再复制到任务目录。
- `modeling/通用业务对象与逻辑实体识别规范_V6.md` 是所有建模任务唯一的核心判定规范：业务属性、逻辑实体、关系分类、实体族、业务对象 R1–R5、UNKNOWN/冲突和一致性校验均以 V6 为准。
- `modeling/数据模型建模规范-v0.2.md` 已编入 `modeling/base.md`，作为每个建模任务都会注入的公共数据模型参考；它不能覆盖 V6，也不需要用户在每个任务中重复上传。
- 根目录的 `业务术语.md`、`业务规则.md`、`指标.md` 是按解析要素动态加载的建模专项技能；任务的 `parseElements` 包含 `TERM`、`RULE`、`METRIC`（或其对应的结果文件）时，加载器会在 V6 与输入源专项规则后追加对应技能；未选择的技能不会注入，也不得生成额外结果文件。
- 服务端会为每个建模任务生成 `modelingPlan`：以 `repositoryId + taskCode + modelVersion + inputFingerprint` 隔离 `termArtifact`、`logicalModelArtifact`、`businessObjectArtifact`、`ruleArtifact` 和 `metricArtifact`，并在 Agent 执行前校验层级依赖。
- `modeling/数据模型建模规范-20260626.md`、`modeling/本体建模步骤拆解.md` 和 `modeling/自底向上业务对象识别规范_v3.md` 保留为历史参考，不再作为运行时建模判定依据。
- 规则源文件变更后，在本地执行 `python scripts/build_agent_knowledge.py`，检查 Markdown 差异，再提交并部署。

## 安全边界

这些文件只作为服务端 Agent 的私有 system prompt 输入，不复制到任务 sandbox，不通过网页文件树展示，也不应在用户对话中复述原文。
