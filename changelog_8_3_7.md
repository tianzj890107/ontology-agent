# 20260803–20260807 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-03 至 2026-08-07 的变更。

## 维护规则

- 每次功能修改后，在本周记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/wugefei/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`。
- 下周开始时，将本文件归档为对应日期范围，并新建下一周的变更记录。

## 2026-08-03

### 1. 任务执行状态与用户确认完成闭环

- Agent 真正开始执行前向本体平台回调 `RUNNING`；模型/工具流以不可恢复错误结束时回调 `FAILED`，包含统一的错误码和审计提示。
- MinIO 上传不再自动回调 `COMPLETED`，上传成功后任务仍保持 `RUNNING`，可继续检查、修改并重新上传结果。
- 对话任务栏新增“完成”按钮：仅当全部期望输出文件已上传、且本地文件 SHA-256 与已上传版本一致时，才回调 `COMPLETED`；完成后按钮变为“修改”，点击后回调 `RUNNING` 并恢复上传和继续执行。
- 上传清单（对象键、预览地址、文件指纹）与平台状态随会话持久化，服务器重启后仍可继续确认；已完成任务再次上传或执行前会明确提示先点击“修改”。
- 兼容本次状态字段上线前已在本体平台成功的历史任务：当平台返回“任务已成功，不能再次执行”时，将对应本地会话迁移为 `COMPLETED`，任务栏直接显示“修改”。
- 适配平台新版任务读取返回：兼容 `executionContext`、`taskContext`、`context` 等嵌套上下文，以及 `taskStatus`、`agentStatus`、`executionStatus` 等显式状态字段；恢复 `outputPrefix`、`expectedFiles` 和解析要素读取。
- 平台已验证当前任务后，会将旧版 `local:` 浏览器身份下的同一任务会话安全迁移到当前平台用户，修复历史任务能查看但无法读取文件、上传或修改的权限断链。
- 修复平台 `execution-context` 返回“解析要素未配置输出文件”时的任务不可用：仅对该明确配置异常回退到同任务的持久化上下文；若历史 `mission-output` 已具备全部期望文件，则恢复为 `COMPLETED` 显示“修改”。认证、无权限和任务不存在仍拒绝回退。
- 修复建模接口配置异常被后续整合接口“任务不存在”覆盖的问题；任务读取现在保留正确类型已确认的上下文配置异常，从而触发缓存恢复。
- 同步更新 Agent 与本体平台的状态接口约定，明确 `RUNNING`、`FAILED`、用户确认 `COMPLETED` 和“修改”恢复运行中的时机。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`backend-agent-interaction-api.md`、`tests/test_ontology_knowledge.py`、`tests/test_frontend_contract.py`。

### 2. 历史会话恢复提示降噪

- 打开历史会话自动恢复审批时，已处理或已过期的审批请求不再弹出错误提示；鉴权、网络等真实审批失败仍保留提示。
- 当前任务信息仅作为侧栏辅助内容；上游任务信息暂不可获取时改为页面空态，不再在打开对话时弹出“获取任务信息失败”。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 13. 审批结果节点样式与完成后收起操作

- `approval_result` 成功节点的思维链圆圈改为 `✓`，标题和内容使用与“模型切换”一致的紫色样式。
- 当前审批对应的 Agent 执行产生 `done` 事件后，审批请求下的“✓ 已允许执行”和“拒绝”操作按钮全部隐藏。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 14. 折叠思维链摘要宽度

- 思维链折叠状态下的摘要最长占当前行宽度的 80%，超出内容继续以省略号显示；展开状态不受影响。
- 主要文件：`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 3. Qwen 与团队模型重名路由修复

- 修复团队模型目录与 Qwen 模型目录存在同名模型时的 Provider 污染问题。
- Qwen 模式下，共享模型继续走 Qwen Base URL 和 Qwen Key；仅团队专属模型不会混入 Qwen 模型列表。
- 团队模式下仍按 `TEAM_MODELS` 暴露模型，并将共享模型标记为团队网关模型。
- 主要文件：`open-claude/open_claude/config.py`、`tests/test_team_config.py`。

### 4. OpenAI 兼容客户端纳入运行依赖

- 将 `openai` 纳入 Open Claude 的基础依赖，确保 Qwen、团队网关及其他兼容接口在按项目依赖安装后即可调用。
- 同步更新 `open-claude/open_claude/requirements.txt`、`open-claude/pyproject.toml` 与安装说明。

### 5. 任务上下文鉴权转发修复

- 读取 execution-context 和完成回写时保留平台传入的 Bearer JWT，避免 Agent 为本地任务隔离生成的临时用户标识覆盖上游登录态。
- 对无效或过长的鉴权头不转发，继续由服务端按现有鉴权规则处理。
- 主要文件：`open-claude/oc_codex_server.py`、`tests/test_ontology_knowledge.py`。

### 6. 术语、规则与指标建模专项技能

- 新增业务术语、业务规则、指标三个静态建模技能；任务选择 `TERM`、`RULE`、`METRIC` 或对应结果文件时自动注入。
- 技能按需加载在 V6 和输入源专项规则后，未选择时不会引导 Agent 生成额外文件。
- 主要文件：`agent_knowledge/业务术语.md`、`agent_knowledge/业务规则.md`、`agent_knowledge/指标.md`、`open-claude/open_claude/ontology_knowledge.py`、`open-claude/oc_codex_server.py`。

### 7. 恢复结果上传后自动完成

- 根据交互调整，移除任务栏“完成/修改”按钮及对应手动状态接口；任务可继续执行和上传，不再因已完成状态锁定操作。
- 上传到 MinIO 后，服务端会校验全部期望输出文件及其 SHA-256 一致性；校验通过即自动回调本体平台 `COMPLETED`，文件未传齐则保持 `RUNNING` 并提示缺少项。
- 保留 Agent 实际开始时的 `RUNNING` 回调以及不可恢复错误的 `FAILED` 回调。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`backend-agent-interaction-api.md`、`tests/test_frontend_contract.py`、`tests/test_ontology_knowledge.py`。

### 8. 完整实现分层建模与 artifact 依赖

- 建模任务统一生成 `repositoryId + taskCode + modelVersion + inputFingerprint` 身份，并在当前任务信息中展示 `modelingPlan` 和五类 artifact。
- `TERM` 作为独立分支；逻辑模型强制按候选属性、逻辑实体、正式业务属性、实体关系顺序执行；业务对象必须依赖逻辑模型；规则和指标必须引用已完成业务对象。
- 服务端在 Agent 真正执行前校验依赖，缺少上游 artifact 时回调 `FAILED`（`MODELING_DEPENDENCY_BLOCKED`），阻止下游文件生成和上传。
- 上传记录会更新各 artifact 的 `RUNNING`、`COMPLETED` 状态；跨任务引用只接受明确完成状态的 artifact，结果文件别名按 execution-context 的实际清单判定。
- 主要文件：`open-claude/oc_codex_server.py`、`agent_knowledge/modeling/base.md`、`backend-agent-interaction-api.md`、`frontend/src/main.jsx`、`tests/test_ontology_knowledge.py`。

## 2026-08-04

### 9. 任务读取与静态知识构建一致性

- 已完成任务或服务器重启后，任务信息中的 `modelingPlan` 会从当前用户绑定的本地任务快照恢复上传文件状态，不再把已上传 artifact 显示为 `PENDING`。
- 术语、规则、指标的合法别名结果文件按 execution-context 的实际清单判定完成，不再因未同时上传其他别名文件而误报 `PARTIAL`。
- 输入指纹生成排除数据库密码、Token、密钥等敏感字段，避免凭据变化导致同一任务身份漂移。
- `LOGICAL_MODEL` 计划展开现在显式包含候选属性阶段；正式逻辑实体、业务属性和实体关系仍作为进入业务对象层的完成条件。
- 将分层建模与 artifact 依赖说明纳入 `scripts/build_agent_knowledge.py` 的生成源，后续重新生成静态知识时不会丢失该规则。
- 主要文件：`open-claude/oc_codex_server.py`、`scripts/build_agent_knowledge.py`、`agent_knowledge/README.md`、`agent_knowledge/modeling/all_sources.md`、`tests/test_ontology_knowledge.py`。

### 10. 思维链空闲阶段加载提示

- Agent 正在执行但暂时没有新的 SSE 思维链事件时，补显示一个临时“思考中”旋转节点；新事件到达、等待审批或本轮结束后自动切换/移除。
- 页面：`frontend/src/main.jsx`。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 11. 指标规范更新与数据模型建模规范切换

- 同步 `agent_knowledge/指标.md` 的最新内容，保留输入体检、候选指标识别、无数据源路径、L4 降级推断、产出下限和执行总结等规则。
- 数据模型建模公共参考切换为 `数据模型建模规范-v0.2.xlsx`，生成对应的 `agent_knowledge/modeling/数据模型建模规范-v0.2.md`，并纳入 `modeling/base.md` 与 `all_sources.md`。
- `modeling/base.md` 会在每个建模任务中自动注入该公共参考；V6 仍是建模决策的核心规范，v0.2 作为数据模型补充参考，不需要用户重复上传。
- 主要文件：`agent_knowledge/指标.md`、`rules/数据模型建模规范-v0.2.xlsx`、`agent_knowledge/modeling/数据模型建模规范-v0.2.md`、`scripts/build_agent_knowledge.py`、`tests/test_ontology_knowledge.py`。

## 2026-08-05

### 12. 审批按钮状态反馈

- 审批请求点击“允许执行”并成功回写后，按钮显示为禁用状态“✓ 已允许执行”。
- 已允许的审批请求隐藏“拒绝”按钮，避免同一请求被重复处理。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`。
