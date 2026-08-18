# 20260810–20260816 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-10 至 2026-08-16 的变更。

## 维护规则

- 每次功能修改后，在本周记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`。
- 本周结束后，将本文件归档为对应日期范围，并新建下一周的变更记录。

## 2026-08-10

### 1. 文件目录箭头垂直对齐

- 文件目录折叠和展开箭头改用统一尺寸的 SVG 图标，固定在目录标题行中垂直居中。
- 折叠与展开状态的箭头保持同一位置，不再受文字基线影响产生上下偏移。
- 已完成前端构建和 12 项契约测试，最新静态产物已部署到服务器。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 2. 本体元模型与输出模板切换到版本 3

- 建模任务固定参考文件切换为 `本体元模型3.xlsx`、`本体元模型模板3.xlsx`。
- 逻辑实体和业务属性结果按模板 3 输出，所有布尔字段统一使用 `Y/N`；每个业务对象只能有一个 `是否主逻辑实体=Y`，`是否唯一`按业务上的唯一标识判断。
- 当前暂不生成维度输出，`是否层级编码`、`是否层级名称`统一填 `N`；逻辑实体映射和业务属性映射仅作为参考输入，不进入结果文件。
- 实体关系结果严格按模板 3 的 16 列输出，不生成模板外的关系分类编码等字段。
- 服务端增加布尔字段和主逻辑实体唯一性的上传前校验；已完成知识文件生成、21 项全量测试和前端生产构建，并已同步部署。
- 主要文件：`scripts/build_agent_knowledge.py`、`open-claude/oc_codex_server.py`、`agent_knowledge/`、`rules/本体元模型3.xlsx`、`rules/本体元模型模板3.xlsx`、`tests/test_ontology_knowledge.py`。

## 2026-08-11

### 3. 本体任务继续执行与任务复用逻辑修复

- 本体平台任务模式隐藏“+ 新会话”，后端对同一 `repositoryId + taskCode + user` 做幂等复用，始终在原任务会话上继续操作。
- 已确认完成的任务重新输入执行指令或上传新结果时，会先删除旧结果对象、回写 `RUNNING`，再继续当前任务，不再被错误拦截。
- 失败任务不再显示“完成”按钮，仍可在原会话中重新执行；成功任务的历史会话和文件面板支持继续上传与建模。
- 已补充任务复用、旧结果清理和状态恢复回归校验；完成 21 项后端/前端契约测试和前端生产构建。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`、`tests/test_ontology_knowledge.py`。

### 4. 旧 ontology 工作区与会话数据迁移

- 将旧目录 `/home/wugefei/ontology/ontology-agent` 中的本体工作区、任务输入输出、任务状态文件、`bi_agent` 和兼容包完整合并到 `/home/zhangzhen/ontology/ontology-agent`。
- 迁移 35 条任务记录、27 条可回放会话及对应 transcript；8 条旧任务本身没有历史日志或 transcript，确认不是迁移遗漏。
- 保留当前修复后的代码和重新创建的 `.venv`，不复用旧虚拟环境；旧 macOS `._*` 元数据和未被新构建引用的历史前端静态产物不迁移。
- 已保留迁移前备份：`/home/zhangzhen/ontology/.backup-before-history-migration-20260811`；服务器测试 21 项通过，服务健康检查返回 200。

## 2026-08-12

### 5. 历史会话、建模中间态与独立结果导出

- 取消 UI 事件 10000 条上限；完整任务日志同时写入任务快照和 `.task_history/<taskId>.jsonl`，模型上下文压缩不再影响历史回放；增加大日志回归测试。
- 建模结果按 `parseElements` 独立生成，`expectedFiles` 只负责文件名和上传白名单，不再把其他结果文件作为强制依赖；新增任务级 `mission-work/modeling_state.json`，保存结构化资产、候选、证据和校验，不作为正式输出或上传结果。
- 任务完成回调使用 `SUCCEED`，兼容读取历史 `COMPLETED/SUCCESS`；修正完成按钮、上传、历史会话、默认折叠、思维链图标和结果文件基础校验契约。
- Excel 预览改为按需加载，图片 URL 及时释放，前端资源使用内容哈希缓存；执行/上传期间禁用完成操作，移除不可信浏览器上下文降级。

## 2026-08-13

### 6. v0.0.1 运行时规范、任务生命周期与工作台契约

- 将编码规范、元模型、模板、含样例模板、数据模型、五类输入源规则、消歧整合、术语/规则/指标知识统一升级为 v0.0.1；规则构建按 Excel 实际工作表名称和顺序读取，避免字典序错位。
- 适配 v0.0.1 输出：业务属性补充数据长度/精度，对象关系、状态、事件增加解析与输出映射；固定参考文件按内容哈希刷新，旧任务只清理系统投放副本，不删除用户输入；规则正式字段、规则编码和重复校验统一收口，未定义编码不自行发明。
- 同步 API/联调文档：`SUCCEED` 为成功回调，上传后保持 `RUNNING`，用户点击完成才成功，修改时恢复 `RUNNING`；`parseElements` 是识别范围唯一来源，`expectedFiles` 是文件白名单，`ok.csv` 仅适用于消歧整合。
- 任务执行、输入替换、结果上传、完成和修改统一使用任务锁；只信任服务端 execution-context 的 `outputPrefix`、任务身份和解析范围；上下文或输入变化会使旧结果/中间态失效；普通提问保持聊天态，明确执行才重新运行。
- 任务日志和会话复用按 `repositoryId + taskCode + user` 幂等，恢复历史会话不重复创建任务；完成按钮检查全部文件、对象 Key、SHA-256 和预览地址。
- 工作台完善完成/修改、文件区、预览、刷新、折叠、文件选择和任务身份传递；XLSX 解析按需加载，前端构建产物启用哈希缓存。
- 新增 `AGENTS.md` 固化仓库变更记录规则：当天 changelog 按最终状态维护，周 changelog 只在周末按每日记录压缩汇总。

### 7. 数据库凭据与文档联调

- 新增与 Java `ConnectionConfigCrypto` 对齐的 AES-256-GCM 解密，密文只保存在受保护任务输入，明文不进入 system prompt；补充 `API/ConnectionConfigCrypto.java`、部署脚本、README 和联调文档。
- 静态知识构建、规则版本、输出契约和参考文件统一使用 v0.0.1；已完成语法检查、知识/上下文契约测试、前端契约测试和生产构建。

## 2026-08-14

### 8. Sandbox 与运行时安全

- 新增统一任务级 `TaskSandboxBoundary`，基于真实规范化路径和 `commonpath` 处理相对/绝对路径、`.`、`..`、重复斜杠、前缀攻击及多级 symlink；`Read/Write/Edit/Glob/Grep`、任务恢复、项目/文件/前端资源访问共用边界，写入校验真实父目录并使用目录 fd/`O_NOFOLLOW` 防止 TOCTOU。
- Linux Shell、Hook、MCP、Skill 命令和 Git 探测通过 bubblewrap mount namespace 只绑定当前任务目录；安全运行时不可用时拒绝执行，不回退到不受限 Shell；越界写入 `SANDBOX_VIOLATION` 结构化日志且不暴露内部路径。
- 新增 Sandbox 越界、symlink、兄弟任务、绝对路径和真实 `tasks/mission-output` 事故回归；服务器 Linux 安全测试通过，macOS 仅跳过无 bubblewrap 的既有条件测试。

### 9. 本体事实可靠性：Evidence Gate、COMPOSITION 与决策审计

- 统一 `modeling_reliability.py` 的 Evidence/Provenance/Decision/ValidationIssue：正式关系必须是有足够证据和 provenance 的 `CONFIRMED`，`CANDIDATE/UNRESOLVED/REJECTED` 只保留在中间态和审计；Validator 只读，不能因缺失关系、WARNING、重试或模板要求创造事实。
- 统一 COMPOSITION 语义：`source=component/dependent/child`、`target=owner/parent`；校验方向、角色、Owner 唯一性、self-loop、cycle、0/1/>1 main、candidate edge，REFERENCE/ASSOCIATION/TRANSFORMATION 等不参与正式聚合，错误方向不自动翻转。
- 每个 Business Object 候选保存 R1–R5 独立 `PASS/FAIL/UNKNOWN`、证据和 provenance；任一 FAIL→`REJECTED`，无 FAIL 且有 UNKNOWN→`CANDIDATE`，全部 PASS→`CONFIRMED`，confidence 不改变结论；全量候选审计写入 `mission-work/business_object_decisions.csv`，正式 `business_objects.csv` 仅消费 CONFIRMED，REJECTED 不删除 Logical Entity。
- Decision/Audit 层进一步统一关系稳定 ID、VIEW JOIN 与 derivation lineage、FK structural reference 与 composition/transformation、跨实体/循环 Evidence、FK coverage、OR JOIN 歧义、UNKNOWN 无新证据不得升级等规则；逻辑实体归属支持 `ASSIGNED/UNASSIGNED/UNRESOLVED`。
- Business Rule 拆分 discovery、validation、enforcement、effectiveness；按规则类型分别验证完整性、告警、计算、状态流转、资格/决策，Alert hit 不等于 violation/effectiveness，0 violation 不等于 ENFORCED；指标保留 formula、grain、scope、unit、aggregation semantics，物理字段不能直接升级为业务指标。
- 建模 finalize 由代码强制写入并校验 `business_object_decisions.csv`、`relation_decisions.csv`、`rule_decisions.csv`、`indicator_decisions.csv`、`logical_entity_decisions.csv`、`pending_confirmations.csv`、`validation_report.json`、`modeling_state.json`；覆盖率必须 100%，正式输出只消费 Decision Layer，生成器不重新判定语义。
- 任务编排按 workspace 持久化 Task ID 和状态，处理幂等创建、非法转换、`TASK_NOT_FOUND`、artifact/completion gate 和 finalization 错误传播；Artifact 已生成但任务状态更新失败时不得宣称完整成功，辅助 Task 不决定 Mission 完成。

### 10. 凭据 fail-closed 与上传边界

- 加密凭据缺少 secret、错误 secret、Tag 校验失败或解密失败时统一返回 `DATABASE_CREDENTIAL_DECRYPTION_FAILED`，禁止把密文透传为数据库密码；服务器配置同源 Base64 32 字节 secret，47313 状态为 AES-256-GCM ready，明文历史凭据仅走显式兼容路径。
- 语义 Evidence Gate 收口到建模 finalize；上传阶段只检查文件存在、可读、编码、CSV 基础表头/行格式和最终结果，不再重算 R1–R5、关系、规则或指标语义；历史旧 `validation_report` 通过兼容迁移，`indicators.csv` 映射统一为 `METRIC`。
- 上传和完成回调只消费 finalize 的验证标记；已修复 Business Object 审计字段、R1–R5 状态读取、历史 `P/F/U` 兼容和 confidence 规则：新任务要求直接输出数值百分比，历史标签不迁移改写。

### 11. 服务器部署、文件树与前端体验

- 已将全部代码、知识、测试、前端构建产物和 changelog 部署到 `zhangzhen@being-SYS-740GP-TNRT` 的 `/home/zhangzhen/ontology/ontology-agent`，分支 `20260727`，服务 `0.0.0.0:47313`；未使用或修改 `wugefei` 环境。服务器虚拟环境 Python 3.10.12，`pypdf`/`anthropic` 已安装，服务器全量测试 77/77 通过。
- 修复任务文件树漏掉 `mission-work` 的根因：文件 API 不再排除该目录，运行时、文件 API、Validator、Uploader 共用当前任务 workspace；任务完成后中间态和决策审计继续保留。
- 文件树用户可见目录统一为 `root/`、`input/`、`work/`、`output/`：`project-shared` 显示为默认折叠的 `root`；四个 v0.0.1 文件直接显示于 `root/input`，XLSX `*-sheets` 中间目录及非决策运行文件显示于 `root/work`，决策审计显示于 `work`，正式结果显示于 `output`。后端保留 canonical `mission-*` 路径，API 增加 `displayPath`，前端按显示路径分组但读写/下载/上传仍使用 canonical 路径。
- 有正式输出的历史会话打开时自动展开文件栏；前端生产构建、文件 API、任务隔离、运行时创建/修改/读取和当前任务 97 个文件的远端 displayPath 均已验证。

### 12. 本周最终验证与已知限制

- 本地最新全量测试：103 项通过，3 项因 macOS 无 bubblewrap 按既有环境条件跳过；前端生产构建、`py_compile`、`git diff --check` 通过。服务器 Linux 定向与全量测试均通过，Sandbox 安全测试实际执行。
- 主要新增/修改范围：`open-claude/oc_codex_server.py`、`open-claude/open_claude/{modeling_reliability.py,credential_crypto.py,sandbox.py,tasks.py}`、`frontend/src/`、`frontend/dist/`、`agent_knowledge/`、`scripts/build_agent_knowledge.py`、`API/`、`DEPLOYMENT.md`、`AGENTS.md` 及对应测试。
- 当前没有可直接重跑的真实生产建模 fixture；语义决策、审计落盘、上传边界和文件树使用通用回归 fixture 验证。服务器真实数据库连通性仍需在具体任务刷新/重建后由 Agent 执行连接验证，不能仅以服务启动状态代替。

### 13. 完成回调状态与后端接口契约修正

- 核对后端真实接口后确认完成回调要求 `agentStatus=SUCCESS`，此前 Agent 代码和仓库文档误用 `SUCCEED`，会导致后端返回“回调状态不合法”。
- 已将建模和消歧整合的完成回调 payload、完成状态处理、错误提示、接口文档和测试断言统一改为发送 `SUCCESS`；读取端继续兼容历史 `SUCCEED`、`COMPLETED` 等状态。
- 已通过相关回归测试并准备重新部署 Agent 服务，避免完成按钮再次因状态枚举不一致失败。
