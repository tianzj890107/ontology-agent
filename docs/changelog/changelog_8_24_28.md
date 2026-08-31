# 20260824–20260828 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-24 至 2026-08-28 的变更（按功能主题归纳，替代每日 changelog）。

## 维护规则

- 本周结束后按功能主题归档为 `changelog_8_24_28.md`，原每日 changelog（8_24/8_25/8_26/8_27/8_28）已按用户要求删除。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃或排队任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。

## 1. 47313 工作台 P0/P1/P2 并发与长会话性能修复（8-24 ~ 8-25）

- 背景：47313 单任务可达数十万事件，旧实现每个事件都重写全部任务完整 log 到 `.web_tasks.json`；任务详情打开即下载全量历史；同任务并发执行依赖长时间 `Task.lock` 阻塞。
- P0-1 事件持久化：`.task_history/<taskId>.jsonl` 成为任务事件唯一事实源，新事件只追加一行 JSON，不再每次重写全局快照；`.web_tasks.json` 只保存任务摘要、`eventSeq`、`activeExecutionId`、`executionStartedAt` 等运行恢复字段；`Task.log` 改为有界热窗口（`EVENT_LOG_HOT_WINDOW=2000`）；clientMessageId 去重使用有界索引（`EVENT_CLIENT_ID_INDEX_SIZE=2000`）O(1) 判重；恢复时以 journal 最后合法 seq 为准，最后一行损坏时忽略该行、前面记录不丢失；旧快照 log 幂等迁移到 journal。
- P0-2 事件分页与绝对游标：新增 `GET /api/tasks/{taskId}/events`（参数与 47314 一致：`tail/limit`、`before/limit`、`since`），响应统一为 `taskId + events + eventStart/eventEnd/eventTotal/eventHasMore/nextCursor`；`GET /api/tasks/{id}` 默认只返回摘要；尾部读取使用反向 seek（43 万行取尾页只解析尾行），`before/since` 通过侧车行偏移索引定位。
- P0-3 同任务短锁原子认领：`Task.claim_execution()/release_execution()` 用 `state_lock` 只保护认领检查、生成 `executionId`、置 working、按 executionId 清理，全程不持有长回合锁；已有执行时 `POST /api/tasks/{id}/send` 立即返回 `409 ACTIVE_RUN_EXISTS`；`stream_turn` 的 finally 按 `executionId` 清理认领，旧 worker 不能清除新 execution；重启后 working 摘要标记 `SERVER_RESTARTED_DURING_EXECUTION` 并清空认领，可重新执行。
- 两服务复用：新建 `open-claude/open_claude/event_window.py`（统一 `[start,end)`、since/before、nextCursor==eventEnd、limit 上限 200）与 `event_journal.py`（JSONL 安全追加、合法行读取、尾部损坏容错、最后 seq 恢复、偏移索引、反向 tail）；47314 `/events` 改为等价复用同一窗口契约与 journal 读写。
- 前端：47313 打开会话只取摘要+尾页（`tail=1&limit=80`），上翻 `before=window.start`，working/blocked/error 时每 2s 经 `/events?since=nextCursor` 增量同步（轮询锁按 taskId 隔离，SSE 直播流期间以 `!busy` 门控暂停）；`ACTIVE_RUN_EXISTS` 删除对应乐观气泡并提示“任务正在执行，已恢复当前进度”；所有窗口继续走 `eventSync.js` 的 `mergeEvents`，React key 与游标不依赖数组下标。
- 主要文件：`open-claude/open_claude/event_journal.py`、`open-claude/open_claude/event_window.py`、`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`frontend/src/main.jsx`、`tests/test_event_journal.py`、`tests/test_event_window.py`、`tests/test_tasks.py`、`tests/test_frontend_contract.py`。
- 验证：新增公共模块单测 17 个（含 43 万行尾页不构造全量对象契约）；`tests/test_tasks.py` 新增 journal 持久化、分页游标、原子认领三类测试；全量 `pytest tests/` 420 passed / 3 skipped / 344 subtests。

## 2. 47313 工作台 P1 进程内并发调度（8-25，本日实现，未部署）

> 后续修订：本项为中间实现，最终由第 3 节的共享 `ExecutionCoordinator` 取代。

- 新增 `open-claude/open_claude/task_scheduler.py`：FIFO 队列 + 条件变量公平准入，全局 active 上限（默认 10）、单用户 active 上限（默认 3）、单用户排队上限（默认 3）、全局排队上限（默认 50），排队满抛 `SchedulerLimitError`；用户达 active 上限时跳过其排队项避免饿死其他用户；`provider_slots` / `database_slots` 两个 `BoundedSemaphore` 在回合执行期间持有。
- `oc_codex_server.py` 接线：`_handle_send` 认领执行后入队，超限返回 `429 USER_QUEUE_LIMIT_REACHED/GLOBAL_QUEUE_FULL` 并释放认领；排队期间任务状态为 `queued`（新增状态，持久化到摘要）；SSE 保持打开，先流式回放 `run_queued`（含队列位置），准入后回放 `run_started`；平台 RUNNING 回调从“认领时”移到“准入后”；`restore_tasks` 对 `queued` 快照按 `working` 处理。
- 前端：`EventFeed` 渲染 `run_queued`（“排队中 · 当前第 N 位”）与 `run_started`；任务列表、状态点、按钮禁用条件全部把 `queued` 视同 `working`；429 走通用错误分支显示服务端文案。
- 验证：`tests/test_task_scheduler.py` 12 个调度器单测；`tests/test_tasks.py` 新增 4 个集成测试（429 释放认领、排队→准入→执行与事件回放、queued 快照恢复、完成门禁阻断）共 59 通过；排除既有 flaky 的 `test_standalone_modeling_server.py` 后全量 382 passed / 3 skipped / 328 subtests。

## 3. 47313/47314 P1/P2 共享 ExecutionCoordinator 最终整改（8-25，本日最终状态，未部署）

- 背景/验收阻断点：上一轮 coordinator 配置写死 `backend="file"`；313 排队仍占用 HTTP/SSE 线程；313 存在双重 claim（`Task.claim_execution()` + `coordinator.claim()`，taskId/durable UUID/coordinator key 混用）；任意实例能从全局 Redis 队列取走只有原实例内存有 payload 的任务；queued 任务等待超过 lease TTL 会产生 ghost；恢复代码存在 token/meta 逻辑矛盾；heartbeat 在 `on_started` 之后启动；`ThreadPoolExecutor.shutdown(wait=True)` 可能无限等待；生产恢复代码存在 KEYS 回退。
- coordinator 配置修复：`configure_execution_coordinator()` 真正按 `TASKS_COORDINATOR_BACKEND=file|redis|none` 构造配置，Redis 时传入 `TASKS_REDIS_URL` 与 `TASKS_REDIS_PREFIX`（默认 `ontology:47313:`）；backend=redis 启动时 PING + EVAL 探针，Redis 不可用或客户端不支持 scan_iter 时启动失败，不静默退化；314 用 `MODELING_SERVER_COORDINATOR_BACKEND=redis` + `MODELING_REDIS_URL` 启用同一 coordinator。
- Redis lease Lua 协议：lease 主键直接保存不可猜测 ownership token，元数据放独立 hash（executionId/ownerInstanceId/fenceToken/queuedAt 等）；renew/release Lua 比较 token；FakeRedis 严格模拟真实 Lua 使用的存储结构。
- waiter 生命周期：调度项状态明确为 `WAITING/ADMITTED/CANCELLED/RELEASED`；取消与 admit 竞态只有一个最终结果；无 busy loop/永久等待。
- 立即准入事件：enqueue 返回 `admittedImmediately`/`queued`；立即准入不设 queued、不记录 `run_queued`，直接记录 `run_started` 进入 working；只有真正留在队列的任务才记录 `run_queued`。
- 313 排队不再占用 HTTP/SSE 线程：等待与执行移入有界后台 worker pool（daemon 线程 + 有界队列）；`POST /api/tasks/{id}/send` 原子认领、持久化用户事件与执行请求后立即返回 HTTP 202 JSON（taskId/executionId/status/queuePosition/nextCursor）；前端经 `/api/tasks/{id}/events?since=` 增量读取执行事件；SSE 保留为已开始任务的可选实时通道。
- 共享调度核心（P1）：新建 `open-claude/open_claude/execution_coordinator.py`，313/314 通过 adapter 复用同一套全局 active（默认 10）、单用户 active（3）、单用户 queued（3）、全局 queued（50）、硬上限（active 32 / queued 1000）、用户间公平轮转、队列取消、worker admission、provider/database semaphore（各 10）、metrics、execution lease/fencing；共享模块不 import 两个服务。
- P2 跨实例与 fencing：instanceId 为 hostname+pid+startup nonce；每次执行保存 resource_id/execution_id/owner_instance_id/fence_token/attempt/queuedAt/claimedAt/startedAt/heartbeatAt/leaseExpiresAt/finishedAt；fenceToken 用 Redis INCR 或文件锁内递增版本单调递增；所有正式副作用（最终状态写入、checkpoint、正式结果登记、MinIO 上传登记、RUNNING/SUCCESS/FAILED 回调、删除/替换旧结果、complete/release）前执行 `execution_guard.assert_current()`，旧 fence 返回 `STALE_EXECUTION` 不覆盖新执行。
- heartbeat 顺序：`_run()` 顺序为取 entry → `_start_heartbeat` → 创建 `ExecutionContext` → `assert_current` → `adapter.on_started` → 检查 token → `run_worker` → finally 停 heartbeat；heartbeat renew 失败或连续异常超过阈值时 `token.reason=LEASE_LOST`，追加 LEASE_LOST 事件，停止后续模型/工具执行，禁止上传与平台成功/失败回调，禁止正式完成状态写入。
- 生产恢复不使用 KEYS：Redis backend 启动时要求客户端 `callable(scan_iter)`，删除 `_iter_meta_keys()` 的 `keys()` 回退；静态契约测试断言生产路径不存在 `client.keys(` 与 `redis.call("KEYS"`。
- 主要文件：`open-claude/open_claude/execution_coordinator.py`（新建）、`open-claude/open_claude/execution_lease.py`、`open-claude/open_claude/task_scheduler.py`、`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`scripts/ensure_agent_venv.sh`、`scripts/deploy_server.sh`、`scripts/run_standalone_modeling.sh`、`API/standalone-modeling-api.md`、`docs/本体建模识别过程SOP.md`。
- 验证：`tests/test_tasks.py` 77 通过（含 `CoordinatorBackendConfigTests` 6、`TaskLifecycleGateTests` 8、EVAL 探针与 scan_iter 启动探针）；`tests/test_task_scheduler.py` + `tests/test_execution_lease.py` 60 通过（含 `FinalAcceptanceTests`）；`tests/test_standalone_modeling_server.py` 59 通过；真实 Redis 集成（临时本地测试 Redis，端口 6390、db15，非生产，无持久化）10/10 通过，测试后 db15 dbsize=0 并清理临时 pid/log；全量 `pytest tests/` 508 passed / 13 skipped / 344 subtests。

## 4. 会话状态同步统一修复：事件幂等合并与游标协议（8-24，跨天收尾）

- 问题 A（47314 重复用户气泡）：`/execute` 202 响应携带完整事件数组，前端快照+增量两条路径直接拼接无去重，出现两个气泡。
- 问题 B（CANCELLED 后提问显示旧错误）：从 CANCELLED 发起普通问题时，会话回合不清除旧 error，前端用裸 `if (started.error)` 把领域状态误判成接口失败。
- 统一事件身份与合并：新增 `frontend/src/eventSync.js`，两服务共用 `eventIdentity`（优先级：`clientMessageId → 服务端持久化 seq → 无标识旧事件的确定性指纹`）、`mergeEvents`（幂等合并后按 seq 升序稳定排序）、`appendStreamEvent`（SSE 实时流增量去重+相邻 thinking/text 拼接）、`eventKey`（React key 与事件身份一致）、`nextCursor`（取服务端绝对位置）。
- 47314 协议：`/execute`、`/cancel` 的 202 改为 `run.as_dict(include_events=False)` 摘要响应，事件统一走 `/events`；`/events` 响应补充 `eventEnd` 与 `nextCursor`；`since` 严格大于、`before` 严格小于，无重叠；前端游标推进改用服务端 `nextCursor/eventEnd`；`loadRun` 尾部窗口与既有缓存按 runId 合并（不替换、不收缩）。
- 47314 错误区分与生命周期：创建/继续/刷新全部改用 `standaloneRequestFailed`（HTTP 非 2xx/网络失败才算接口失败）；`execute()` 只在 FAILED/BLOCKED 上做会话问答时保留原错误，CANCELLED 提问与真实续跑立即清空 `run.error`。
- 47314 轮询与合成气泡：全局 `pollInFlightRef` 改为按 runId 的锁 Map；初始 prompt 气泡只在事件日志无正式 user 事件时合成（续跑不重复），BLOCKED 建议与 prompt 气泡带稳定 `_key`。
- 部署：功能提交 `b256e68` 已部署 47313/47314（部署前确认无活跃任务；47313 任务均 `idle`；47314 仅 FAILED run，无 QUEUED/ANALYZING）。本地直连 `git push origin 20260727` 成功；服务器绕开 `https_proxy` 直连 `git fetch` 并 `git merge --ff-only` 快进；本次改动在顶层脚本，不在依赖指纹内，venv 无需重装。两服务 `/`、`/health` 均 200，47313 线上 HTML 引用新 bundle `index-DNajaSjr.js`。
- 主要文件：`frontend/src/eventSync.js`（新增）、`frontend/src/main.jsx`、`frontend/dist/`、`open-claude/standalone_modeling_server.py`、`open-claude/oc_codex_server.py`、`tests/test_standalone_modeling_server.py`、`tests/test_tasks.py`、`tests/test_frontend_contract.py`。
- 验证：`tests/test_standalone_modeling_server.py` 新增 4 项、`tests/test_tasks.py` 新增 `TaskEventSyncTests` 4 项、`tests/test_frontend_contract.py` 新增 eventSync 纯函数 Node 行为测试；相关 97 项通过。

## 5. 47313 全部旧会话历史恢复（8-25）

- 问题：P0 事件 journal 上线后，47313 的 43 个任务仍存在且 `.task_history` 中约 62MB 历史数据完整，但旧 journal 事件没有 `seq` 字段；启动恢复只寻找最后一个显式 `seq`，将所有旧会话错误恢复为 `eventSeq=0`，点击会话返回空事件。
- 修复：共享 `event_journal.last_valid_seq()` 兼容旧格式，以有效事件的绝对位置和显式 `seq` 的较大者恢复最后事件位置；兼容纯旧 journal、纯新 journal 以及旧新混合 journal，不重写生产历史文件。
- 数据与部署：部署前将 `.web_tasks.json` 和完整 `.task_history` 备份到服务器 `open-claude/sandbox/session-recovery-backup-20260825-1800`（约 62MB、35 个 journal），未改写原始历史；修复提交 `b049e13` 已部署到 47313（pid `2983038`）。全量比较 43 个任务 API 与磁盘有效事件数：35 个有历史会话全部一致、8 个空任务保持为空、0 个失败；最大会话 433,942 条尾页正常返回 80 条。
- 主要文件：`open-claude/open_claude/event_journal.py`、`tests/test_event_journal.py`、`tests/test_tasks.py`。
- 验证：`tests.test_event_journal` + `tests.test_tasks` 共 89 项通过。

## 6. 团队模型目录、默认模型与 47314 运行体验（8-24）

- 团队模型目录由 8 个扩展为 24 个已验证可完成对话的模型，排除网关未路由或上游鉴权失败的 `mimo-v2-pro`、`mimo-v2-flash`、`claude-opus-4-8`、`test`；默认模型当日先统一为 `qwen3.8-27b`，随后按需求改回 `Qwen/Qwen3-80B-AWQ`（内置团队目录末尾显式保留 `qwen3.8-27b` 条目避免目录变 23 个）；`config.py` 内置默认、`.env.example` 与本地/服务器 `.env` 同步；`tests.test_team_config` 3 项通过。已部署提交 `8a70629`、`55cd46d`。
- 47314 建模暂停提示改为可折叠详情：暂停节点正式输出只保留【建模已暂停】、产物说明与继续运行指引，暂停原因与未通过门禁校验项收进“暂停详情（点击展开）”折叠区；前端 `AssistantText` 新增 `:::details` 折叠块渲染。已部署至 `12100b1`。
- 47314 独立建模默认模型固定：打开历史 run 不再用该 run 的历史模型覆盖当前选择，任何人刷新或重新进入页面都固定取服务端默认，仅用户在当前会话显式选择才会改变。已部署至 `a7fb0b0`。
- 47314 续跑用户输入显示为用户气泡：服务端 `execute` 收到显式 `prompt` 时先把用户文本作为 `user` 事件写入 run 日志（位于 `run_queued` 之前），并保留原始 `run.prompt`；事件顺序为 `user → run_queued`；无显式文本时不写入。已部署至 `55cd46d`。
- 47314 续跑意图误判修复：`is_conversational_turn` 在疑问词判定之前新增执行指令优先规则（`继续/接着/重新` + 执行动词），命中即按建模执行回合处理；`run_6ed2452ad3c447c1a2bfb4edbaff76a7` 由 FAILED 重置为 INPUT_READY 可续跑。已部署至 `8194cc2`。
- 47314 CANCELLED/BLOCKED 运行的提问与续跑修复：前端 `continueRun` 放行列表加 `CANCELLED`；服务端 `execute()` 的 QUEUED `allowed_from` 加 `CANCELLED`，问答回合不再清空 FAILED/BLOCKED 错误原因，只有真正续跑才清；`restore_after_question` 接受 BLOCKED 原样回退，保留暂停原因。
- 主要文件：`open-claude/open_claude/config.py`、`open-claude/standalone_modeling_server.py`、`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`.env.example`、`tests/test_team_config.py`、`tests/test_standalone_modeling_server.py`、`tests/test_frontend_contract.py`。

## 7. 建模规范修订与逻辑实体归属门禁（8-24）

- 建模规范第 12 条修订（低过拟合证据一致性门禁）：以用户更新的权威文件 `rules/数据模型建模规范-v.0.0.1.xlsx` 为基础，构建链固定读取名 `rules/数据模型建模规范v0.0.1.xlsx` 同步一份逐字节一致的副本；明确基础数据、规则数据、报告报表数据三类不是业务对象（分类/标签型参考数据、规则配置项/表达式/执行结果、报表模板/查询定义/统计展示），保留可独立治理的规则定义/规则版本、报告实例、主数据等例外；判定必须基于证据组合，不得仅凭名称/表名/数据类别一刀切；证据不足用 UNKNOWN/CANDIDATE 并形成确认问题。
- 运行时知识重建：`scripts/build_agent_knowledge.py` 重新生成 `agent_knowledge/modeling|integration/*v0.0.1.md`，均含新第 12/10 条；构建可重复、无额外漂移。
- 逻辑实体归属状态门禁：统一为 `ASSIGNED`（编码/名称必填且引用本次 CONFIRMED 业务对象、有且唯一主实体）/ `NOT_APPLICABLE`（编码/名称必须为空、主标志 `N`、必须带非业务对象分类/排除原因/证据并关联 REJECTED 候选决策）/ `UNRESOLVED`（证据不足，编码/名称为空、主标志 `N`、必须保留确认问题）；禁止创建 `BO0000`、`BO99999`、`非业务对象逻辑实体` 等占位业务对象；空编码且无审计状态是结构错误，绝不自动推断 `NOT_APPLICABLE`。
- CSV 契约：`modeling_csv_contract.py` 将 `logical_entities.csv` 的业务对象编码/名称改为条件必填（新增 `assignment_status_aware`、归属状态推断与 `FORMAL_CONTRACT_ASSIGNMENT_STATUS_MISSING`/`ASSIGNMENT_CONFLICT` 错误码）；未声明归属列的简化 CSV 保持 header-aware 兼容。
- 门禁：`modeling_reliability.py` 重写 `validate_logical_entity_assignments`（`NOT_APPLICABLE` 主标志 `Y`、填写编码/名称、缺审计证据、无对应 REJECTED 决策均阻断；`ASSIGNED` 缺编码或引用非 CONFIRMED 阻断；`UNRESOLVED` 主标志 `Y` 阻断）；新增 `CONFIRMED_WITH_NON_BUSINESS_OBJECT_KIND` 与 `R5_PASS_WITH_EXPLICIT_COUNTER_EVIDENCE`（STRUCTURAL_BLOCKER）；`apply_not_applicable_normalization` 确定性自动修复。
- 测试与部署：`tests/test_modeling_reliability.py` 新增 `NotApplicableAssignmentTests`（12 项）；`python -m unittest discover -s tests` 373 项通过；提交 `45c02ca` 已部署 47313/47314（本次修改 `open_claude/` 源码导致依赖指纹变化，按既有离线流程构建本地 wheel 并更新 `.venv/.ontology-agent-deps.sha256`）。
- 主要文件：`rules/数据模型建模规范v0.0.1.xlsx`、`agent_knowledge/modeling|integration/*v0.0.1.md`、`open-claude/open_claude/modeling_csv_contract.py`、`open-claude/open_claude/modeling_rule_registry.py`、`open-claude/open_claude/modeling_reliability.py`、`open-claude/oc_codex_server.py`、`tests/test_modeling_reliability.py`。

## 8. 本体可视化：五层筛选、径向布局、网络图与统一布局交互（8-25 ~ 8-26）

- 本体层级一键画图预览（8-25，已部署）：47313 任务文件面板新增“画图”入口，首次点击按当前任务正式 CSV 动态构造 ECharts Tree 并在预览弹窗展示；逻辑实体是唯一必需产物，按产物齐全度展示三层/两层/仅实体节点；节点编码仅用于内部关联，标签与悬浮只显示名称；多业务对象挂到不可见技术根节点下全部展示；树图缓存绑定任务 ID，切换任务清空旧图，旧任务迟到响应不能覆盖新任务；属性默认按需展开；固定可滚动视口、画布按叶子行数动态增高（每行 58px），防重叠布局；全屏/退出全屏控制，全屏铺满浏览器视口。
- 业务属性默认折叠（8-25）：本体可视化打开时默认只展示业务对象和逻辑实体，属性通过“展开业务属性”按钮按需显示。
- Sigma + Graphology + ForceAtlas2 本体网络图 Beta POC（8-26，已部署）：与 ECharts 并存，预览内保留“环形图 / 网络图 Beta”切换，默认优先启动网络图 Beta，不初始化环形 renderer；空闲时后台预加载 ECharts 资源。新增 `frontend/src/ontologyGraphModel.js` 统一图模型，只按正式编码/名称来源字段生成 BO→LE、LE→Attribute 和 Metric→来源节点关系，缺可信归属的 Rule 仅生成孤立节点；ForceAtlas2 采用 `scalingRatio=4.5`、`gravity=0.25`、`edgeWeightInfluence=1`、`slowDown=4`、Barnes-Hut + LinLog，真实 963 节点/964 边数据 160 次迭代约 299ms；Sigma 支持 pan/zoom、hover 标签、1-hop 邻域高亮、重新布局、ResizeObserver 与卸载 `kill()`。
- 五层筛选与径向共享轨道布局（8-26，已部署）：预览卡片右上角新增漏斗图标，固定提供业务对象、逻辑实体、业务属性、指标、业务规则五项 Checkbox（缺少或没有有效数据的图层置灰）；默认勾选当前 task/run 实际存在的全部本体文件层；`draftLayers`/`appliedLayers` 两阶段状态，确认才重建图。`frontend/src/ontologyRadialLayout.js` 改为可测试的高密度语义带装箱：业务对象层多内轨、其余语义层从上一实际外边缘开始、AABB 碰撞 + 逐轨 compact pass；布局接收当前预览宽高，全屏/普通窗口/ResizeObserver 重算均使用对应宽高；fit 允许大于 1。指标优先使用正式 `metrics.csv`（兼容 `indicators.csv` 等别名），规则只在精确命中时建立连线。
- 布局失败恢复：以“最后一次真正成功渲染”为准，`onRendered` 更新 `lastGoodLayout`，失败后保留上一成功布局、恢复下拉框并允许再次尝试，不在 network/radial 之间循环切换。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/ontologyGraphModel.js`、`frontend/src/ontologyForceLayout.js`、`frontend/src/OntologySigmaPreview.jsx`、`frontend/src/ontologyRadialLayout.js`、`frontend/src/styles.css`、`frontend/package*.json`、`frontend/tests/ontologyGraphModel.test.mjs`、`frontend/tests/ontologyForceLayout.test.mjs`、`frontend/tests/ontologyRadialLayout.test.mjs`、`tests/test_frontend_contract.py`、`frontend/dist/`。
- 验证与部署：前端 Node 测试逐步增至 33 项；headless Chrome + 软件 WebGL 使用仓库真实 8 BO/26 LE/904 Attribute 数据完成渲染；`npm run build` 成功；部署提交 `8579de6`、`5513434`、`a3b205a`、`48ad47b`、`912c43f`、`7403242`、`7d1be7d`、`a1c0187`、`d91c39f`、`d47e65b` 均已推送并部署，两服务 `/`、`/health` 均 200。

## 9. 本体可视化统一布局选择与运行时加固（8-27）

- 统一布局选择交互：预览右上角收敛为统一“布局”下拉框，仅“关系聚类可视化”（ForceAtlas2/网络图）与“语义环形可视化”（径向语义分层图）两项；打开预览默认优先关系聚类可视化；网络图展示期间空闲时后台完成 `layoutOntologyRadial` 布局数据计算并写入有界缓存（LRU 上限 8 条），不创建隐藏 ECharts 实例；切换语义环形时优先复用缓存，未就绪显示统一加载态并复用 in-flight Promise；缓存键 `radial:<数据指纹>:<layerKey>:<宽>x<高>:<布局版本>`，`appliedLayers` 确认、viewport 实质变化（含全屏/退出全屏）、任务/run 数据变化后失效并后台重算。
- 新增 `frontend/src/ontologyLayoutOptions.js`、`frontend/src/ontologyRadialPrecompute.js` 与 `frontend/tests/ontologyLayoutOptions.test.mjs`、`frontend/tests/ontologyRadialPrecompute.test.mjs`（12 项：指纹稳定性、缓存键失效、viewport 归一化、缓存 LRU 与 Promise 复用）。
- 七层真实挂载：关系聚类可视化扩展为业务对象、逻辑实体、业务属性、实体关系、指标、业务规则、动作七类真实挂载；指标/规则/动作按真实业务对象、逻辑实体编码或名称精确交叉解析（不做模糊猜测），未命中保持孤立，不凭常识臆造归属；仅关系聚类布局移除最外层边框和圆角。服务器真实产物只读核验：实体关系 18/18、指标 8/8、规则 12/12、动作 16/16 均命中真实挂载目标。提交 `79dff00` 已推送并部署，线上 bundle `index-BqyXHrdA.js`。
- 布局选择器移除外边框（`f5c67a1`，已部署）。
- 可视化运行时错误隔离：修复 `useCallback` 漏导入导致的整页空白（`React` 导入补上 `useCallback`）；47313/47314 两处预览 Modal 的 `<OntologyTreePreview>` 整体包在 `<OntologyPreviewErrorBoundary resetKey={ontologyPreviewResetKey(...)}>` 内，渲染异常、hooks 初始化异常、图层筛选/布局选择器异常、Sigma/ECharts 初始化异常、React.lazy 加载异常都只影响预览卡片；新增 `frontend/tests/hooksContract.test.mjs`（静态 hooks 契约）与 `frontend/tests/ontologyPreviewRuntime.test.mjs`（Vite SSR 真实加载渲染）；新增 devDependency `react-test-renderer@18.3.1`。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/OntologySigmaPreview.jsx`、`frontend/src/styles.css`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/dist/`、`frontend/tests/hooksContract.test.mjs`、`frontend/tests/ontologyPreviewRuntime.test.mjs`、`frontend/tests/fixtures/react-dom-client-stub.mjs`、`tests/test_frontend_contract.py`。
- 验证：全量 `pytest tests` 664 passed / 13 skipped / 445 subtests；Node 测试 60/60。

## 10. 本体建模 CSV 上传门禁修复：规范化、门禁分离与语义非阻断完成（8-27）

- 问题：`entity_relations.csv` 历史兼容字段名被误报“期望16列、实际16列”；`logical_entities.csv` 空业务对象编码的实体因缺少内部审计归属状态被上传门禁拒绝；中文名称含 ID/PDF 等英文缩写被误拒；英文关系分类被误拒；语义校验问题错误地禁用了“完成”按钮。
- 表头与受控值规范化（集中式契约）：`modeling_csv_contract.py` 新增 `HEADER_ALIASES`、`RELATION_CATEGORY_ALIASES` 与 `enum_aliases`，以及 `normalize_header_cell/normalize_csv_header/normalize_enum_value/normalize_csv_blob/header_mismatch_messages` 纯函数；规范化顺序：UTF-8 BOM → 首尾空白/零宽字符清理 → 表头别名映射 → 受控枚举别名映射 → 与正式契约比较；`entity_relations.csv` 登记历史等价表头别名；`关系分类` 登记英文枚举别名（大小写与首尾空白兼容，未知英文值仍拒绝）；`CSV_NORMALIZATION_VERSION` 记录契约版本，完成门禁按同版本重放规范化后比较哈希。
- 中文名称规则：所有 `chinese_name` 字段统一要求包含至少一个中文字符，允许混用英文缩写/数字/常用标点（如 `源头单据ID`、`财报PDF文档`、`API调用记录`、`2D图纸`、`3D模型`）；纯英文、纯数字或纯符号被拒绝。
- 表头错误信息：改为逐列指出 `第 N 列期望“X”，实际为“Y”`、缺失字段、未知字段；字段集合正确但顺序错误时明确报告“字段顺序不符合模板”。
- 上传对象规范化：`/api/minio/upload` 对建模 CSV 先在内存中规范化表头与受控字段值，MinIO 对象与响应 `sha256` 均对应规范化后的 blob；本地原文件保留英文关系分类与旧表头不被覆盖；历史任务原 CSV 不修改。
- 上传/完成门禁分离：上传阶段（`validate_modeling_upload_artifact_detailed`）只执行文件自身的确定性结构规则，不再读取 `work/modeling_state.json` 或决策审计；多行逐行校验修复（原先 boolean/enum/整数/编码/中文名等规则只检查最后一个数据行）。
- 规范化上传双哈希完成校验：上传记录保存 `sha256`（规范化 blob）、`sourceSha256`（本地原始文件）、`normalized`、`normalizationVersion`；完成门禁重放规范化后比较 `sha256`；旧记录只有 `sha256` 时保持原始哈希语义，版本不匹配 fail-closed 要求重新上传。
- 空上下文防护：`Task.set_mission_context` 对规范化后仍为空的上下文直接返回，不写入空指纹的 `modeling_state.json`；`validation_report.json` 作为非阻断 warnings 保持可读。
- 语义校验改为非阻断 warnings：`completionReady` 与完成回调不再因语义/治理问题拒绝完成，继续保存在 `validation_report.json`、决策审计与 `modeling_state.json`，通过 `completionWarnings`/`completionHint` 提示，用户确认后仍发送 `SUCCESS`，本地记录 `completedWithWarnings`（不伪造 PASSED、不删除报告）。
- completionReady 单一权威：新增 `completion_readiness(task, gate_error=None)` 返回 `{"ready", "blockers", "warnings"}`；确定性阻断（任务执行中/排队、活动 execution、FAILED/CANCELLED、expectedFiles 为空或上下文无效、文件缺失或上传记录不完整、本地内容与已上传对象不一致、对象不在可信 outputPrefix）控制按钮与完成回调；前端合并 `result.task` 时以服务端外层最终值为准。
- 主要文件：`open-claude/open_claude/modeling_csv_contract.py`、`open-claude/open_claude/modeling_reliability.py`、`open-claude/open_claude/modeling_rule_registry.py`、`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`frontend/src/main.jsx`、`tests/test_modeling_csv_contract.py`、`tests/test_gate_action_normalization.py`、`tests/test_semantic_finalize_upload_boundary.py`、`tests/test_frontend_contract.py`。
- 验证与部署：提交 `bc0a380` 已推送并部署 47313/47314（部署前确认无 active/queued execution；47313 重启 pid `3040408`、47314 pid `3045138`）；全量 `pytest tests` 663 passed / 13 skipped / 445 subtests；Node 测试 47/47。

## 11. 动作元模型、业务对象编码契约与工作区统一命名（8-27）

- 动作元模型：按 `rules/本体元模型模板v.0.0.1.xlsx` 动作 Sheet 将“动作”落地为正式独立元模型，正式产物 `actions.csv` 严格使用模板九个字段（动作编码、动作名称、动作英文名、动作描述、动作类型、业务对象编码、协议、服务节点、服务名称）；动作类型仅支持 新增/修改/删除（内部 CREATE/UPDATE/DELETE，写入 CSV 用中文）；动作编码 `ACT` + 6 位流水码；识别策略“明确证据优先、合理推断兜底”，推断动作在描述中注明“演示候选动作”，无服务证据时协议/服务节点/服务名称留空不得虚构；无业务对象不生成动作。
- 动作生产接入：动作识别接入 47313/47314 正式 finalize 流程，与实体关系、指标、规则同批落盘 `actions.csv`；运行时知识、提示词与模板同步；提交 `2372291` 已推送并部署。
- 业务对象编码契约收紧：正式建模产物中的 `业务对象编码` 统一为 `BO` + 4 位流水码（`^BO\d{4}$`），不再接受任意字母开头的旧格式（`CO001`、`BO1`）；契约生效范围含 `business_objects.csv`、`logical_entities.csv`、`business_object_relations.csv`、`statuses.csv`、`actions.csv`；决策审计候选编码属中间态内部标识，不强制 BO 格式；历史任务旧格式产物保留、不做批量迁移；`scripts/build_agent_knowledge.py` 的 `CODE_STANDARD_RULES` 改为“本体元素编码契约（强制）”，`agent_knowledge/*` 重新生成；全量 pytest 676 passed / 13 skipped / 448 subtests，Node 74/74；本批未部署、未 commit。
- 运行工作区统一命名：47313 任务工作区与 47314 run 工作区统一为 `input/work/output` 三目录，移除 `mission-*` 符号链接命名；历史 run/任务通过兼容层继续解析旧 `mission-work/modeling_state.json` 下载路径；提交 `4813811` 已推送并部署（部署前备份服务器配置/索引至 `backup-pre-2026-08-27-111442/`）；新 run 磁盘只生成 `input/work/output`，历史 run 文件列表 53 项全部 canonical 逻辑路径，47313 历史任务 `/api/files`（280 项）无 mission 命名路径。
- 主要文件：`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`open-claude/open_claude/modeling_csv_contract.py`、`scripts/build_agent_knowledge.py`、`agent_knowledge/*`、`API/backend-agent-interaction-api.md`、`frontend/src/main.jsx`、`frontend/dist/`。

## 12. 其余运行与前端修复（8-27）

- 默认模型切换为 DeepSeek V4 Flash：团队网关默认模型由 `Qwen/Qwen3-80B-AWQ` 调整为 `direct-deepseek-v4-flash`（`config.py` 内置回退值、`.env.example`、本地/服务器 `.env` 同步）；47313 任务详情与增量事件窗口新增 `model` 字段，取任务 conversation 的实际 live model；前端打开任务和轮询事件时同步实际模型，事件窗口没有 `model` 时回退读取 `/api/meta`。
- 思考过程跨批次合并：`EventFeed` 在完整去重、排序后的展示层对相邻增量再次归并，跨 SSE、轮询、刷新、历史分页边界的连续 `thinking`/`text` 显示为单一节点；服务端原始逐 token journal、单调 `seq`、绝对游标和审计历史完全保留。
- 自动确认修复：202 后台执行的审批自动放行（旧的自动确认只挂在 SSE `consume` 分支）；`eventSync.js` 新增 `unresolvedApprovalRequests` 与 `approvalsNeedingAutoApprove` 纯函数，轮询、刷新恢复、重开历史会话、动态开启开关统一使用；`openTask`/`toggleAutoApprove` 不再用 `find` 匹配已存在 `approval_result` 的历史请求。
- 模型传输/协议错误改为本地可重试暂停、自动确认修复与“完成”回调网络错误修复：流式 timeout/传输错误进入本地可重试暂停而不是直接失败；“完成”回调网络错误结构化返回、保留 execution context parse elements、可重试；`b0fcec5`、`ff0851d`、`31db5ce`、`4298426`、`652c15b`、`b62bd10`、`16e03cf` 等提交均已部署。
- 文件面板操作区移除完成态旁注（`bc74d0a`，已部署）。
- 主要文件：`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`open-claude/open_claude/openai_compat.py`、`frontend/src/main.jsx`、`frontend/src/eventSync.js`、`frontend/dist/`、`tests/test_tasks.py`、`tests/test_frontend_contract.py`。
- 验证：全量 `pytest tests` 663 passed / 13 skipped / 445 subtests；Node 47/47；提交 `bc0a380` 已推送并部署。

## 13. 品牌统一、文档整理与协作规则（8-28）

- 品牌统一与全屏预览：47313 左上角改为与 47314 一致的“硕磐智能建模 + v0.1.0”，47314 版本由 v0.0.1 改为 v0.1.0；`frontend/src/main.jsx` 定义 `PRODUCT_NAME`/`PRODUCT_VERSION` 单一常量，两个入口共同使用；知识规范和建模契约中的 v0.0.1 未修改。全屏预览 Modal 从左上角开始并占满 `100vw × 100dvh`，全屏下所有预览容器 `border-radius:0!important`，普通模式圆角保持不变。
- 项目 README、正式版本文档与工程记录目录整理：原根目录 `README (1).md`（Eimosp Foundation File Service 文档）归档到 `docs/eimosp-foundation-fileserver.md`；新建根 `README.md`；正式版本说明统一使用 `docs/versions/`（`README.md` 版本索引 + `v0.1.0.md`）；原 `changelog/` 整体迁移到 `docs/changelog/`；`AGENTS.md` 活动路径同步并新增“正式版本文档工作流”；新增 `tests/test_documentation_layout.py`（10 项布局契约断言）。
- 47314 独立建模 `actions.csv` 契约修复：`DEFAULT_ARTIFACTS` 加入 `actions.csv`，`ARTIFACT_PARSE_ELEMENTS` 将 `actions.csv` 映射为 `ACTION`；白名单不扩大到前端未提供的其他产物；未知产物仍返回 422。
- 全局协作规则：`AGENTS.md` 新增“提交与禁止部署（最高优先级）”；同步修订 `debug.md`、`DEPLOYMENT.md`、`日报.md` 等；新增防回归测试 `tests/test_repository_workflow_contract.py`（7 项断言）。
- Git 双远端私有镜像工作流：新增 `personal` 私有远端 `git@github.com:zhenzhang0408/ontology-agent.git`（目标分支 `main`），同一 commit 双 push（`HEAD == origin/20260727 == personal/main`）；新增 `scripts/push_dual_remotes.py` 与本地 bare remote 测试 `tests/test_dual_remote_push.py`（13 项）；`personal` 仅作为镜像与个人版本归档，禁止个人仓库独立提交。
- GitHub Release 双仓库发布规范：用户在当前任务明确授权创建某版本的 GitHub Release 时，必须在 `tianzj890107/ontology-agent`（origin）与 `zhenzhang0408/ontology-agent`（personal）两个仓库同时发布绑定同一 immutable annotated tag 的 Release；两个 Release 的 tag object hash、peeled commit、标题、正文、draft、prerelease 必须一致；已存在且符合要求的 Release 复用并验收，不重复创建；任一仓库失败时报告部分成功，保留已成功 Release 只重试缺失仓库；Release 不等于部署。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`README.md`、`docs/versions/*`、`docs/changelog/README.md`、`docs/git-dual-remote-workflow.md`、`AGENTS.md`、`debug.md`、`DEPLOYMENT.md`、`scripts/push_dual_remotes.py`、`tests/test_documentation_layout.py`、`tests/test_repository_workflow_contract.py`、`tests/test_dual_remote_push.py`。
- 验证：全量 pytest 705 passed；Node 76/76；production build 成功；`git diff --check` 通过。

## 14. v0.1.0 定版、双 Release 与部署（8-28）

- v0.1.0 正式定版：`docs/versions/v0.1.0.md` 状态“已定版”，正式 annotated tag `v0.1.0`（object `38eae0402176e2e801ba92bcd00ee304b83eacf0`、peeled `188057d8a81b7d83f0aeb858e40c3ef14fddf539`）；新增 `docs/versions/versioning-policy.md` 版本管理规范（语义化版本、每日稳定发布、部署与版本边界、禁止事项）；定版 commit `188057d`。
- v0.1.0 功能部署与线上验证：服务器由 `f5c67a1` 快进到 `3af6d14`（含 47314 `actions.csv` 默认产物契约、统一“硕磐智能建模 v0.1.0”、全屏无圆角、文档目录整理、双远端推送工具）；部署前本地全量 pytest `722 passed / 13 skipped / 448 subtests`、Node `76/76`；47313 重启 pid `4122195`、47314 重启 pid `4125590`，两服务 `/`、`/health` 均 200，线上加载 `assets/index-DvhxxeJ3.js` 与全屏 `border-radius:0!important` CSS。
- v0.1.0 双仓库 GitHub Release：personal 仓库已存在 `v0.1.0` Release（id 378309186）验收并复用（正文统一），origin 仓库缺失已创建（id 378324865）；两个 Release 均绑定 `v0.1.0` tag、标题“硕磐智能建模 v0.1.0”、非 draft、非 prerelease、正文一致；链接见 `docs/versions/v0.1.0.md`。

## 15. v0.1.1 开发、定版、双 Release 与部署（8-28）

- 功能开发：为 47313 任务工作台和 47314 独立建模服务建立有界的内存会话缓存（`frontend/src/sessionCache.js`：namespaced cache key、LRU 上限 10、graph 产物签名、in-flight Promise 去重、缓存即时恢复、`createOpenGate` 请求 generation），会话打开后后台预加载本体 CSV 并构建 ontology graph，点击可视化时复用已缓存 graph 或同签名在途请求；mission/task 请求使用 generation 与 AbortController 隔离快速切换竞态，旧响应不能覆盖新会话、mission context、model、events 或 loading 状态；缓存仅当前页面内存有效，不使用 localStorage/sessionStorage/IndexedDB。
- 测试：`frontend/tests/sessionCache.test.mjs`、`frontend/tests/ontologyPreviewRuntime.test.mjs`（替换源码字符串测试为真实行为测试）、`frontend/tests/ontologyForceLayout.test.mjs`（新增可提交的五层 CSV 夹具 `frontend/tests/fixtures/five-layer/`，修复对运行时 `output/` 的依赖）；定版前前端 Node 117/117、Python 全量 739 passed / 13 skipped / 452 subtests、production build 成功、`git diff --check` 通过。
- 定版：产品 UI 版本常量更新为 `v0.1.1` 并重建 `frontend/dist`；`docs/versions/v0.1.1.md` 状态“已定版、已部署”；定版 commit `e5cc67e`；annotated tag `v0.1.1`（object `1b5a129b7a8026234469c352f3b5bccadb62a997`、peeled `e5cc67e464f65bdfa1df3d50955853b197c407ab`）精确双推 origin 与 personal；双仓库 Release 均已创建：origin `https://github.com/tianzj890107/ontology-agent/releases/tag/v0.1.1`、personal `https://github.com/zhenzhang0408/ontology-agent/releases/tag/v0.1.1`（标题“硕磐智能建模 v0.1.1”、非 draft、非 prerelease、正文一致）。
- 部署：用户明确授权后服务器绕开 `https_proxy` 直连 `git fetch` 并 `git merge --ff-only` 快进到 `e5cc67e`；47313 经 `scripts/deploy_server.sh` 部署（25 项部署门禁测试通过，pid `678197`），47314 经 `scripts/run_standalone_modeling.sh` 重启（pid `679841`）；两服务 `/`、`/health` 均 200，线上 HTML 引用新 bundle `index-Q74jSlUt.js`（sha256 与本地 `frontend/dist` 一致），界面产品版本 `v0.1.1`；`v0.1.0` tag 未移动。
- 部署后文档记录：`docs: record v0.1.1 deployment`（commit `1d8d2c9`）更新 README 当前线上版本、`docs/versions/v0.1.1.md` 状态、版本索引与 changelog 部署记录，已双推。

## 验证与部署基线

- 完整测试集由本周初 `117` 项（8-24 门禁测试）增长至期末 `739 passed / 13 skipped / 452 subtests`（Python 全量）+ 前端 Node `117/117`；production build、`py_compile`、`git diff --check` 均通过。
- 本周所有功能修复均以同一 commit 部署 47313/47314，部署前确认两服务无活跃或排队任务；最终服务器 HEAD 与 `origin/20260727` 同步（`1d8d2c9`），两服务 `/`、`/health` 200，启动日志无 Traceback，默认模型 `direct-deepseek-v4-flash`，界面产品版本 `v0.1.1`。
- 服务器工作树保留 `.runs.json`/`.runs.sqlite3` 运行数据本地修改，未受影响；`.env`、`.venv`、`open-claude/sandbox/` 和会话数据未提交。
