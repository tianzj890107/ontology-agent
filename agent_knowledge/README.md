# Agent 静态知识库

本目录是给 Ontology Agent 使用的静态 Markdown 知识库，由 `rules/` 中的产品目标、规则文档和 Excel 规则表离线生成。

## 使用方式

- 运行服务只读取已经生成的 Markdown，不会在服务器实时解析 DOCX/XLSX，也不会修改本目录。
- `integration.md` 用于智能消歧与整合，包含目标、规则和整合模板。
- `modeling/base.md` 用于所有智能建模任务；各 `modeling/*.md` 文件在此基础上补充对应输入源的专项规则。
- `本体元模型.md`、`本体元模型模板.md` 和 `本体建模步骤拆解.md` 是单独可审阅的参考 Markdown；同样内容也已编入 `modeling/base.md`，由 system prompt 静态注入 Agent。
- `智能消歧与整合模板.md` 是整合任务输出/对齐结构的静态 Markdown 参考，并已编入 `integration.md`，由 integration system prompt 静态注入 Agent。
- 规则源文件变更后，在本地执行 `python scripts/build_agent_knowledge.py`，检查 Markdown 差异，再提交并部署。

## 安全边界

这些文件只作为服务端 Agent 的私有 system prompt 输入，不复制到任务 sandbox，不通过网页文件树展示，也不应在用户对话中复述原文。
