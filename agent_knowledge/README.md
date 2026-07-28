# Agent 静态知识库

本目录是给 Ontology Agent 使用的静态 Markdown 知识库，由 `rules/` 中的产品目标、规则文档和 Excel 规则表离线生成。

## 使用方式

- 运行服务只读取已经生成的 Markdown，不会在服务器实时解析 DOCX/XLSX，也不会修改本目录。
- `integration/` 用于智能消歧与整合：`base.md` 是目标和规则，`template.md` 是 Excel 模板，`output_schema.md` 是十类结果 CSV 的字段契约，`all_sources.md` 是组合后的 system prompt 知识。
- `modeling/base.md` 用于所有智能建模任务；各 `modeling/*.md` 文件只保存对应输入源的专项规则，运行时由 Agent 加载器按需拼接公共规则和专项规则，避免重复复制。
- `modeling/本体元模型.md`、`modeling/本体元模型模板.md` 和 `modeling/本体建模步骤拆解.md` 是建模参考 Markdown；同样内容也已编入 `modeling/base.md`，由 modeling system prompt 静态注入 Agent。
- `modeling/数据模型建模规范-20260626.md` 是数据模型命名、定义、主键、关系和建模质量规范的独立 Markdown；同样内容也已编入 `modeling/base.md`。
- 规则源文件变更后，在本地执行 `python scripts/build_agent_knowledge.py`，检查 Markdown 差异，再提交并部署。

## 安全边界

这些文件只作为服务端 Agent 的私有 system prompt 输入，不复制到任务 sandbox，不通过网页文件树展示，也不应在用户对话中复述原文。
