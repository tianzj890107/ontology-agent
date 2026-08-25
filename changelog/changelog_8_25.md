# 20260825 变更记录

> 本文档记录 `20260727` 分支在 2026-08-25 的变更。

## 维护规则

- 每次功能修改后，在本记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。

## 2026-08-25

### 1. 8-24 会话状态同步修复部署收尾（跨天）

- 8-24 会话的「会话状态同步统一修复」功能代码 `b256e68` 已于 8-24 部署并验证（47313/47314 均 `/`、`/health` 200，默认模型 `Qwen/Qwen3-80B-AWQ`，47313 已服务新 bundle `index-DNajaSjr.js`）。
- 8-25 上午完成收尾：docs 提交 `4dc1f79`（changelog 部署记录）经本地 bundle+scp 同步到服务器（服务器直连 github 超时），服务器 HEAD 与 `origin/20260727` 一致（`4dc1f79`）。
- 纯文档同步，无需重启服务。
- 主要文件：`changelog/changelog_8_24.md`。

### 2. 47313 工作台 P0 并发与长会话性能修复（本日实现，未部署）

- 背景：47313 单任务可达数十万事件，旧实现每个事件都重写全部任务完整 log 到 `.web_tasks.json`；任务详情打开即下载全量历史；同任务并发执行依赖长时间 `Task.lock` 阻塞。
- P0-1 事件持久化：
  - `.task_history/<taskId>.jsonl` 成为任务事件唯一事实源，新事件只追加一行 JSON，不再每次重写全局快照。
  - `.web_tasks.json` 只保存任务摘要、`eventSeq`、`activeExecutionId`、`executionStartedAt` 等运行恢复字段，不再包含完整 log；摘要保存节流为状态变化（working/idle/error/blocked、平台回调、上传、完成）时触发，普通 thinking/text 只追加 journal。
  - `Task.log` 改为有界热窗口（`EVENT_LOG_HOT_WINDOW=2000`），不再在内存保留几十万条事件；clientMessageId 去重使用有界索引（`EVENT_CLIENT_ID_INDEX_SIZE=2000`），O(1) 判重，不再扫描全量历史。
  - 恢复时以 journal 最后合法 seq 为准，不相信滞后的摘要 `eventSeq`；最后一行损坏时忽略该行、前面记录不丢失、下一 seq 从最后合法事件继续。
  - 旧快照 log 幂等迁移到 journal：journal 已存在不再重复导入；迁移成功后摘要不再写 log。
- P0-2 事件分页与绝对游标：
  - 新增 `GET /api/tasks/{taskId}/events`，参数与 47314 一致（`tail/limit`、`before/limit`、`since`），响应统一为 `taskId + events + eventStart/eventEnd/eventTotal/eventHasMore/nextCursor`。
  - `GET /api/tasks/{id}` 默认只返回摘要，仅 `tail/before/includeEvents` 时返回受 `limit<=200` 限制的窗口；`GET /api/tasks` 列表保持纯摘要。
  - 尾部读取使用反向 seek（43 万行取尾页只解析尾行，不构造全量 JSON 对象）；`before/since` 通过侧车行偏移索引定位（`<journal>.idx`，每 128 条一行，缺失/过期时幂等重建）。
- P0-3 同任务短锁原子认领：
  - `Task.claim_execution()/release_execution()`：`state_lock` 只保护认领检查、生成 `executionId`、置 working、按 executionId 清理；全程不持有长回合锁。
  - `POST /api/tasks/{id}/send`（execute 与 chat 均生效）已有执行时立即返回 `409 {"code":"ACTIVE_RUN_EXISTS","error":"该任务已有执行正在进行","taskId":...,"executionId":...}`，不记录第二个用户事件、不发 RUNNING 回调、不开第二条 SSE。
  - `stream_turn` 的 finally 按 `executionId` 清理认领，旧 worker 不能清除新 execution 的认领；重启后摘要为 working 时标记 `SERVER_RESTARTED_DURING_EXECUTION` 事件并清空认领，任务可重新执行，不会永久 ACTIVE_RUN_EXISTS。
- 两服务复用：新建 `open-claude/open_claude/event_window.py`（`parse_window`/`window_response`，统一 `[start,end)`、since/before、nextCursor==eventEnd、limit 上限 200）与 `event_journal.py`（JSONL 安全追加、合法行读取、尾部损坏容错、最后 seq 恢复、偏移索引、反向 tail）；47314 `/events` 改为等价复用同一窗口契约与 journal 读写，接口响应和调度行为不变。
- 前端：
  - 47313 打开会话只取摘要+尾页（`tail=1&limit=80`），上翻 `before=window.start`，新增轮询补偿 `since=nextCursor`（working/blocked/error 时每 2s 经 `/events` 同步，轮询锁按 taskId 隔离；SSE 直播流期间以 `!busy` 门控暂停轮询，避免 token 片段与正式事件合并重复）。
  - `ACTIVE_RUN_EXISTS`：删除对应乐观气泡、`messageApi.info("任务正在执行，已恢复当前进度")`、恢复已有执行的事件同步，不显示通用红色报错。
  - 所有窗口（快照/tail/since/before/SSE）继续走 `eventSync.js` 的 `mergeEvents`，React key 与游标不依赖数组下标或本地长度。
- 主要文件：`open-claude/open_claude/event_journal.py`、`open-claude/open_claude/event_window.py`、`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`frontend/src/main.jsx`、`tests/test_event_journal.py`、`tests/test_event_window.py`、`tests/test_tasks.py`、`tests/test_frontend_contract.py`、`frontend/dist/`（bundle 构建见 P1/P2，最终 bundle 见第 5 节：`index-DAkuCftD.js`/`index-IgQ4J5mi.css`；旧 `index-DNajaSjr.js` 已删）。
- 验证结果：
  - 新增公共模块单测 17 个（`test_event_window.py` + `test_event_journal.py`，含 43 万行尾页不构造全量对象契约）。
  - `tests/test_tasks.py` 新增 journal 持久化、分页游标、原子认领三类测试（含并发双线程单胜出、旧 finally 不清新认领、重启 INTERRUPTED 恢复）。
  - 全量 `pytest tests/`：420 passed, 3 skipped, 344 subtests passed。
  - `npm run build` 成功（P0 中间构建为 `index-CNqFJiAB.js`，最终被 P1/P2 的 `index-C0_gbpmE.js` 取代）；`py_compile` 与 `git diff --check` 通过。
  - 未部署、未提交、未推送。

### 3. 47313 工作台 P1 进程内并发调度（本日实现，未部署）

> 后续修订：本项为中间实现，最终由第 5 节的共享 `ExecutionCoordinator` 取代（313/314 统一调度、租约与 fencing，313 排队不再占用 HTTP/SSE 线程）。

- 背景：P0 后同一任务有短锁原子认领，但不同任务之间仍是“每请求一个执行线程”的无界并发；本项为 47313 增加有界、公平的进程内调度（P1 范围，不含 worker pool 全局线程池的分布式扩展）。
- 新增 `open-claude/open_claude/task_scheduler.py`：
  - `TaskScheduler` 以 FIFO 队列 + 条件变量实现公平准入：全局 active 上限（默认 10，`TASKS_MAX_ACTIVE`）、单用户 active 上限（默认 3）、单用户排队上限（默认 3）、全局排队上限（默认 50），排队满时抛 `SchedulerLimitError`。
  - 用户已达 active 上限时跳过其排队项，避免单用户占满队列饿死其他用户（与 47314 `ModelingRunManager` 语义一致）。
  - `provider_slots` / `database_slots` 两个 `BoundedSemaphore`（`TASKS_PROVIDER_CONCURRENCY` / `TASKS_DATABASE_CONCURRENCY`，默认等于 max_active），由调用方在回合执行期间持有。
  - 模块无服务依赖，不接触任务存储或全局状态。
- `oc_codex_server.py` 接线：
  - `_handle_send` 在认领执行后、打开 SSE 前入队；超限立即返回 `429 {"code":"USER_QUEUE_LIMIT_REACHED"|"GLOBAL_QUEUE_FULL","error":...,"taskId":...,"executionId":...}` 并释放认领，不记录用户事件、不发 RUNNING、不开第二条 SSE。
  - 排队期间任务状态为 `queued`（新增状态，持久化到摘要）；SSE 保持打开，先流式回放持久化的 `run_queued`（含队列位置），准入后回放 `run_started`，同一连接继续流式输出回合；客户端排队期间离开时请求仍在后台执行（与既有断流语义一致）。
  - 平台 RUNNING 回调从“认领时”移到“准入后”，平台只在真正开始执行时看到 RUNNING。
  - `stream_turn` 在 provider（数据库任务再叠加 database）信号量内执行；请求线程本身即执行线程，保持 SSE 流式契约，不引入跨线程写 socket。
  - `restore_tasks` 对 `queued` 快照按 `working` 同样处理：重启后标 `SERVER_RESTARTED_DURING_EXECUTION`、清空认领、可重新执行；`task_completion_gate` 对 `queued` 同样阻断完成。
  - `main()` 启动时 `configure_task_scheduler(_build_task_scheduler())`，配置来自环境变量。
- 前端：
  - `EventFeed` 渲染 `run_queued`（“排队中 · 当前第 N 位”）与 `run_started`（“开始执行”）事件，新增 `queued`/`started` 样式。
  - 任务列表、任务头状态点、发送/上传/完成按钮的禁用条件全部把 `queued` 视同 `working`；侧栏任务显示“排队中/执行中/已阻断”标签。
  - 429 时前端走通用错误分支显示服务端文案（不改乐观气泡处理）。
- 主要文件：`open-claude/open_claude/task_scheduler.py`、`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`（新 bundle，最终见第 5 节：`index-DAkuCftD.js`/`index-IgQ4J5mi.css`）、`tests/test_task_scheduler.py`、`tests/test_tasks.py`、`tests/test_frontend_contract.py`。
- 验证结果：
  - `tests/test_task_scheduler.py` 12 个调度器单测（FIFO、全局/单用户 active 上限、排队上限、公平跳过、release 幂等、信号量、快照、配置校验）。
  - `tests/test_tasks.py` 新增 4 个集成测试（429 释放认领、排队→准入→执行与事件回放、queued 快照恢复、完成门禁阻断），共 59 通过。
  - 排除既有 flaky 的 `test_standalone_modeling_server.py` 后全量：382 passed, 3 skipped, 328 subtests passed；该文件单跑多次 54 passed（偶发挂起在 HEAD 基线同样存在，与本项无关）。
  - `npm run build` 成功；`py_compile` 与 `git diff --check` 通过。
  - 未部署、未提交、未推送。

### 4. 47313 工作台 P2 跨进程/多实例执行租约（本日实现，未部署）

> 后续修订：本项为中间实现，最终由第 5 节的共享 `ExecutionCoordinator` 统一接管（Redis Lua 协议、owner-affinity、fencing、heartbeat 与恢复均在第 5 节收敛）。

- 背景：P0/P1 的执行认领仍只在进程内存中，同一任务在第二个 47313 进程（或未来多实例部署）上可能被再次执行；进程崩溃后摘要里的 `working` 只能等重启手动恢复，且旧实现会永久返回 ACTIVE_RUN_EXISTS。
- 新增 `open-claude/open_claude/execution_lease.py`（服务无关公共模块，不接触任务存储/工作目录）：
  - `LeaseRecord`（task_id/execution_id/owner_id/acquired_at/lease_expires_at）持久化“谁拥有该任务执行”。
  - `FileExecutionLeaseStore`：每任务 `.lease.json` + `flock`（`fcntl` 不可用时回退进程内线程锁），同主机跨进程原子认领；`try_claim` 只在无租约或租约已过期时成功，`renew`/`release` 都校验 execution_id 令牌，过期租约自动可被回收。
  - `RedisExecutionLeaseStore`：`SET NX PX` 认领 + token 校验的 Lua 释放/续租，多实例共享一个协调存储；`build_lease_store()` 工厂按 `TASKS_LEASE_STORE=file|redis|none`、`TASKS_LEASE_DIR`、`REDIS_URL`、`TASKS_LEASE_SECONDS`（默认 120）、`TASKS_REDIS_LEASE_PREFIX` 构建。
- `oc_codex_server.py` 接线：
  - `Task` 增加 `lease_store`、`_lease_owner_id`（`pid-uuid8`）、`lease_seconds`/`heartbeat_seconds`；`claim_execution()` 先做持久租约认领再落内存认领，成功即启动后台心跳线程续租，租约被占时立即返回 `("", active_id)`（走既有 409 ACTIVE_RUN_EXISTS 通道）；`release_execution()` 幂等停心跳并释放租约，旧 execution 的 finally 不能清除新 execution。
  - 内存认领与租约一致性加固：内存有 active 认领但租约已过期/缺失/被其他 execution 接管时（如外部 worker 崩溃或完成后释放），下一次 `claim_execution` 自动清掉陈旧内存认领并重新可执行，不再依赖重启；租约存储读取瞬时故障时保守保持阻断，不误放行。
  - `restore_tasks()` 启动恢复：`working/queued` 快照若存在未过期的外部租约（owner 非本进程），保持原状态并恢复 `active_execution_id`（后续请求由租约 409），不再强制打断真正在另一个进程运行的任务；租约缺失/过期时照旧标 `SERVER_RESTARTED_DURING_EXECUTION`、清空认领、可重新执行，不会永久 ACTIVE_RUN_EXISTS。
  - `main()` 在 `restore_tasks()` 之前调用 `configure_task_leases()`（构建租约存储并绑定所有任务），使恢复逻辑能按租约状态判断；配置来自环境变量，未配置时退化为纯内存认领，单进程行为与 P0/P1 完全一致。
- 前端：无需改动。`ACTIVE_RUN_EXISTS` 轻量提示、乐观气泡清理、事件同步恢复均为 P0 已有行为，P2 的跨进程 409 走同一通道。
- 主要文件：`open-claude/open_claude/execution_lease.py`、`open-claude/oc_codex_server.py`、`tests/test_execution_lease.py`。
- 验证结果：
  - 新增 `tests/test_execution_lease.py` 17 个测试：文件租约 claim/renew/release/过期回收、多进程（fork）并发单胜出与子进程租约父进程可见、Redis 假客户端 NX/令牌校验/TTL、工厂环境选择、Task 集成（租约占用阻断、并发单胜出、恢复尊重未过期外部租约、过期租约恢复可重试、陈旧内存认领在租约释放后自动清除）。
  - `tests.test_tasks`（59）、`tests.test_task_scheduler`（12）、事件模块（17）、`tests.test_frontend_contract` 等全量（排除既有 flaky 的 `test_standalone_modeling_server.py`）：402 passed, 3 skipped；该文件本次单跑 54 passed（偶发挂起在 HEAD 基线同样存在，与本项无关）。
  - `npm run build` 成功（前端源码未变，bundle 见第 5 节最终构建）；`py_compile` 与 `git diff --check` 通过。
  - 未部署、未提交、未推送。

### 5. 47313/47314 P1/P2 共享 ExecutionCoordinator 最终整改（本日最终状态，未部署）

- 背景/验收阻断点：上一轮 313 的 `configure_execution_coordinator()` 虽读取 `TASKS_COORDINATOR_BACKEND`，但构造 `CoordinatorConfig` 时写死 `backend="file"`、`redis_url=None`，真实 Redis 下 renew/release 必然失败；313 排队仍占用 HTTP/SSE 线程；313 存在双重 claim（`Task.claim_execution()` + `coordinator.claim(..., lease_pre_claimed=True)`，taskId/durable UUID/coordinator key 混用）；任意实例能从全局 Redis 队列取走只有原实例内存有 payload 的任务；queued 任务等待超过 lease TTL 会丢失 token/meta 产生 ghost；恢复代码存在“token 不存在但 meta 存在”的逻辑矛盾；heartbeat 在 `on_started` 之后启动，RUNNING 网络回调阻塞时租约无人续期；`ThreadPoolExecutor.shutdown(wait=True)` 可能无限等待；313 queued/working 期间上传、完成、edit、输入替换无统一门禁；部署脚本不保证 redis 包已安装；生产恢复代码存在 KEYS 回退。
- 313 coordinator 配置修复：`configure_execution_coordinator()` 真正按 `TASKS_COORDINATOR_BACKEND=file|redis|none` 构造配置，Redis 时传入 `TASKS_REDIS_URL`（回退 `REDIS_URL`）与 `TASKS_REDIS_PREFIX`（默认 `ontology:47313:`），创建 `_RedisBackend`；backend=redis 启动时 PING + EVAL 探针，Redis 不可用或客户端不支持 scan_iter 时启动失败，不静默退化；314 用 `MODELING_SERVER_COORDINATOR_BACKEND=redis` + `MODELING_REDIS_URL` 启用同一 coordinator。
- Redis lease Lua 协议：lease 主键直接保存不可猜测 ownership token，元数据放独立 hash（executionId/ownerInstanceId/fenceToken/queuedAt 等）；renew/release Lua 比较 token，成功后再 PEXPIRE/DEL；FakeRedis 严格模拟真实 Lua 使用的存储结构与命令，不再自行解析 JSON。
- waiter 生命周期：调度项状态明确为 `WAITING/ADMITTED/CANCELLED/RELEASED`；`wait_for_slot` 在 ADMITTED 返回 true、CANCELLED/RELEASED 返回 false 或抛明确取消异常；release queued waiter 后等待线程有限时间退出；重复 release 幂等；取消与 admit 竞态只有一个最终结果；无 busy loop/永久等待。
- 立即准入事件：enqueue 返回 `admittedImmediately`/`queued`；立即准入不设 queued、不记录 `run_queued`、不显示“第 0 位”，直接记录 `run_started` 进入 working；只有真正留在队列的任务才记录 `run_queued`，position 从 1 开始。
- 313 排队不再占用 HTTP/SSE 线程：等待与执行移入有界后台 worker pool（daemon 线程 + 有界队列）；`POST /api/tasks/{id}/send` 原子认领、持久化用户事件与执行请求后立即返回 HTTP 202 JSON（taskId/executionId/status/queuePosition/nextCursor），不为 queued 任务长期保持 SSE；前端经 `/api/tasks/{id}/events?since=` 增量读取执行事件；SSE 保留为已开始任务的可选实时通道，浏览器断线/刷新不终止后台执行；active worker 数与 queued 数严格有界。
- 共享调度核心（P1）：新建 `open-claude/open_claude/execution_coordinator.py`，313/314 通过 adapter（task/run ID、user ID、状态读取迁移、事件追加、执行 callback、取消 token）复用同一套全局 active（默认 10）、单用户 active（3）、单用户 queued（3）、全局 queued（50）、硬上限（active 32 / queued 1000）、用户间公平轮转、队列取消、worker admission、provider/database semaphore（各 10）、metrics、execution lease/fencing；默认配置兼容既有 314 环境变量，313 保留 `TASKS_*` 环境变量；共享模块不 import 两个服务。
- P2 跨实例与 fencing：instanceId 为 hostname+pid+startup nonce，进程内所有任务共享；每次执行保存 resource_id/execution_id/owner_instance_id/fence_token/attempt/queuedAt/claimedAt/startedAt/heartbeatAt/leaseExpiresAt/finishedAt；fenceToken 用 Redis INCR 或文件锁内递增版本单调递增；所有正式副作用（最终状态写入、checkpoint、正式结果登记、MinIO 上传登记、RUNNING/SUCCESS/FAILED 回调、删除/替换旧结果、complete/release）前执行 `execution_guard.assert_current()`（token 未取消 + `verify_fence` + ownerInstanceId 匹配），旧 fence 返回 `STALE_EXECUTION`，不覆盖新执行；普通事件日志允许保留旧 worker 的 LEASE_LOST 审计事件，但不写正式完成结论。
- heartbeat 顺序：`_run()` 顺序为取 entry → `_start_heartbeat` → 创建 `ExecutionContext` → `assert_current` → `adapter.on_started` → 检查 token → `run_worker` → finally 停 heartbeat；on_started 前 heartbeat 已运行、阻塞期间租约正常续期；heartbeat renew 失败或连续异常超过阈值时 `token.reason=LEASE_LOST`，追加 LEASE_LOST 事件，停止后续模型/工具执行，禁止上传与平台成功/失败回调，禁止正式完成状态写入，finally 只尝试释放自己的 token。
- 有界优雅停机：自定义 `_TaskHandle`/`_BoundedWorkerPool`（daemon 线程 + 有界 queue）替代 `ThreadPoolExecutor`；`shutdown(timeout)` 拒绝新 claim（`COORDINATOR_STOPPING`）→ 停 dispatcher → 取消 queued 并原子归还计数 → 取消 active token → 有界等 future → 超时标 `entry.abandoned=True`、停心跳（租约自然过期由其他实例恢复，旧 worker 不再写正式状态）；不依赖私有、不可控线程自然退出。
- 313 生命周期门禁：新增 `task_lifecycle_conflict(task, action)`，任务 status 为 queued/working、`activeExecutionId` 非空或 coordinator 存在有效 execution/lease 时，MinIO 上传、完成回调、edit、输入替换、重新执行等统一返回 HTTP 409 `EXECUTION_ACTIVE`（含 taskId/executionId）；Agent 内部 checkpoint/finalize 走 ExecutionContext fencing，不受外部 HTTP 门禁误伤；只读查看、下载、事件读取继续放行。
- 取消贯穿 313/314：`_TaskExecutionAdapter.run_worker()` 不再 `del token`；`stream_turn` 及内部调用接受 cancellation token，在每轮模型调用前、provider/database semaphore 等待（`acquire(timeout=0.2)` 可取消循环）、provider 流事件循环、每个工具调用前后、上传前、平台回调前、最终状态落盘前检查；semaphore 获取不无限阻塞，异常/取消不泄漏 slot。
- 部署闭环：`scripts/ensure_agent_venv.sh` 支持 `ONTOLOGY_AGENT_VENV_EXTRA`（从本地 wheel 安装 `open-claude[<extra>]`，fingerprint 包含 extra）；`scripts/deploy_server.sh` 与 `scripts/run_standalone_modeling.sh` 在 redis 模式透传 `ONTOLOGY_AGENT_VENV_EXTRA=redis`，部署日志记录非敏感配置（coordinatorBackend/prefix/leaseSeconds/heartbeatSeconds/quotaScope/queueScope/multiHostSafe），不打印 REDIS_URL/密码；`open-claude/pyproject.toml` 保持 `open-claude[redis]` 可选依赖（wheel 校验 `Provides-Extra: redis`）。
- 能力边界与文档：file 后端同一任务 lease 为同主机多进程安全，但 active/queued 配额与公平队列仅限单进程（`quotaScope=process`、`queueScope=process`、`multiHostSafe=false`）；redis 后端 task lease、active/queued 与单用户配额、公平队列均为集群共享（`quotaScope=cluster`、`queueScope=cluster`、`multiHostSafe=true`）；`/health` 的 `concurrency`/`coordination` 为 313/314 统一结构，不暴露 userId、Redis URL、密码或租约 token；已同步 `API/standalone-modeling-api.md` 与 `docs/本体建模识别过程SOP.md`。
- 生产恢复不使用 KEYS：Redis backend 启动时要求客户端 `callable(scan_iter)`（真实 redis-py 与 FakeRedis 均支持），删除 `_iter_meta_keys()` 的 `keys()` 回退；静态契约测试断言生产路径不存在 `client.keys(` 与 `redis.call("KEYS"`。
- 前端：`ACTIVE_RUN_EXISTS` 轻量提示“任务正在执行，已恢复当前进度”、删除对应重复乐观气泡、复用已有执行的事件同步（P0 行为保持）；202 与 HTTP 2xx 中的业务 `error` 字段不被当作请求失败。
- 主要文件：`open-claude/open_claude/execution_coordinator.py`（新建）、`open-claude/open_claude/execution_lease.py`、`open-claude/open_claude/task_scheduler.py`、`open-claude/oc_codex_server.py`、`open-claude/standalone_modeling_server.py`、`scripts/ensure_agent_venv.sh`、`scripts/deploy_server.sh`、`scripts/run_standalone_modeling.sh`、`API/standalone-modeling-api.md`、`docs/本体建模识别过程SOP.md`、`tests/test_task_scheduler.py`、`tests/test_execution_lease.py`、`tests/test_redis_integration.py`、`tests/fake_redis.py`、`tests/test_tasks.py`、`tests/test_standalone_modeling_server.py`、`tests/test_frontend_contract.py`。
- 验证结果：
  - 针对性：`tests/test_tasks.py` 77 通过（含 `CoordinatorBackendConfigTests` 6、`TaskLifecycleGateTests` 8、EVAL 探针与 scan_iter 启动探针）；`tests/test_task_scheduler.py` + `tests/test_execution_lease.py` 60 通过（含 `FinalAcceptanceTests`：heartbeat 前置、shutdown 有界、COORDINATOR_STOPPING、abandoned 不写正式状态、KEYS 静态契约、scan_iter 必需）；`tests/test_standalone_modeling_server.py` 59 通过；`tests/test_frontend_contract.py` 11 通过。
  - 真实 Redis 集成：启动临时本地测试 Redis（端口 6390、db15，非生产，无持久化）后 `tests/test_redis_integration.py` 10/10 通过（Lua claim/renew/release、两实例 global/per-user active 上限、owner-affinity、queued 超 TTL 不 ghost、owner 消失后清理、recovery 单胜出、fence 递增、旧 fence 不能 release、计数归零）；测试后 db15 dbsize=0，Redis 已 shutdown，临时 pid/log 已按删除安全规则清理。
  - 全量 `pytest tests/`：508 passed, 13 skipped（10 个真实 Redis 集成用例在未设 `ONTOLOGY_TEST_REDIS_URL` 时 skip + 3 个 Linux bubblewrap sandbox 用例，macOS 无法运行）, 344 subtests passed。
  - `npm run build` 成功（最终 bundle `index-DAkuCftD.js`/`index-IgQ4J5mi.css`，旧 `index-DNajaSjr.js`/`index-DhhPofaH.css` 已删）；全部修改 Python 文件 `py_compile` 通过；`git diff --check` 通过；部署脚本 `bash -n` 通过。
  - 未部署、未提交、未推送。

### 6. 部署记录（c58c879，47313/47314）

- 2026-08-25 下午按 DEPLOYMENT.md 本地发布流程部署：门禁测试（`tests.test_ontology_knowledge` + `tests.test_frontend_contract`，19 通过）→ `npm run build` → 选择性提交（排除 `mission-input/`、`mission-output/`、`mission-work/`、`work/`、`rules/` 用户数据）→ 推送 `origin/20260727`（`4dc1f79..c58c879`）。
- 服务器（company-server）部署前确认无 queued/working 活跃任务（43 个任务中 2 个 blocked 为稳定状态）。
- 47313：`bash scripts/deploy_server.sh` 成功，`commit=c58c879`，新 pid 2378228，`/` 与 `/health` 均 200，启动日志含部署基线 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`，`/health` 含 `coordinator_ready`。
- 47314：重启 `standalone_modeling_server.py --port 47314`（新 pid 2380165），`/` 与 `/health` 均 200，`core: ready`，启动日志含同一 provider transport 基线。
- 两服务 `/health` 均报告 `coordination.backend=file`、`quotaScope=process`（file 后端能力边界，与实现一致；未启用 Redis 模式，未安装/使用 redis 依赖）。
- 服务器工作树保留 `.runs.json`/`.runs.sqlite3` 运行数据本地修改，未受影响。
- 已提交、已推送；部署完成。

### 7. 本体层级一键画图预览（5513434，已部署）

- 47313 任务文件面板在“下载所选 / 上传到 MinIO”后新增“画图”按钮；首次点击按当前任务已有正式 CSV 动态构造 ECharts Tree，并像文件一样在预览弹窗中展示，成功后按钮改为“展示”，可直接再次打开已生成图。
- 逻辑实体是唯一必需产物：三份产物齐全时展示“业务对象 → 逻辑实体 → 业务属性”三层；缺少业务属性时展示“业务对象 → 逻辑实体”；缺少业务对象时展示“逻辑实体 → 业务属性”；只有逻辑实体时展示实体节点；缺少 `logical_entities.csv` 时按钮禁用并说明原因。
- 节点编码仅用于跨表关联、唯一标识与内部定位，树图标签和悬浮内容只显示名称；属性默认按需展开，支持节点展开/收起及画布缩放、平移，避免大量属性一次性铺满。
- 新增 `echarts` 前端依赖、树图预览样式及前端契约测试；主要文件：`frontend/package.json`、`frontend/package-lock.json`、`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。
- 验证结果：发布门禁 `tests.test_ontology_knowledge` + `tests.test_frontend_contract` 共 20 个测试通过；`npm run build` 成功（ECharts 独立异步 chunk `index-CzJ1nSGZ.js`，Vite 仅报告既有的大 chunk 警告）；`git diff --check` 通过。部署前确认 47313/47314 均无 active/queued/working/analyzing/validating 任务。
- 部署结果：功能提交 `5513434` 已推送 `origin/20260727`；47313 经 `scripts/deploy_server.sh` 部署为 pid `2507913`，线上 HTML 已引用 `index-DjjgQVmz.js`；47314 重启为 pid `2509907`。两服务 `/`、`/health` 均 200，`core/coordinator` ready、active/queued 均为 0，启动日志均含 `connect=5s read=600s write=600s pool=600s` transport 基线；服务器仅保留既有运行数据文件本地修改。
- 多业务对象显示修复：ECharts Tree 只消费单根树，旧版把多个业务对象直接作为多个根传入，导致仅绘制第一个；现统一挂载到不可见的技术根节点下，全部业务对象可同时展示，技术根不显示名称、节点或悬浮内容，并按是否存在业务对象自动调整默认展开深度。
- 当前任务沙盒隔离修复：树图缓存改为绑定任务 ID，画图请求使用点击时当前任务的 project/task 身份和当前任务文件快照；切换任务时立即清空旧文件与旧图，异步文件列表或画图结果返回前再次校验任务 ID/请求序号，旧任务的迟到响应不能覆盖新任务，避免不同任务错误展示同一棵树。
- 修复提交 `a3b205a` 已推送并部署：47313 pid `2548223`、47314 pid `2549346`；发布门禁 20 个测试通过，线上主 bundle 更新为 `index-5hOX7Xr2.js`，两服务健康检查通过。
- 47314 文件面板同步在“下载所选”右侧提供本体树入口，严格读取当前 run 的文件接口；47313/47314 按钮文案统一固定为“本体可视化”，不再随加载完成切换“画图/展示”。
- 两端文件与本体图预览弹窗统一垂直居中，默认上下留白一致；标题栏关闭按钮左侧新增仅图标的全屏/退出全屏控制，全屏模式铺满浏览器视口。
- 树节点由“圆点 + 外部名称”改为内嵌名称的横向椭圆：业务对象、逻辑实体、业务属性分别使用蓝色、绿色、灰色节点，节点宽度按名称长度自适应，编码继续仅用于内部关联、不显示。
- 功能提交 `48ad47b` 已推送并部署：47313 pid `2585121`、47314 pid `2586215`；发布门禁 20 个测试通过，线上主 bundle/CSS 更新为 `index-IwxpnWft.js` / `index-WmgdUGGT.css`，两服务健康检查通过。
- 文件面板移除常态下的“当前任务范围”辅助字样；任务已完成时仍保留“上传新结果将恢复执行”的必要状态提示。
- 隐藏技术根到第一层节点的连接线，业务对象直接作为可视树第一层；缺少业务对象时逻辑实体直接作为第一层，不再在最左侧出现无意义的引导线。
- 修复提交 `912c43f` 已推送并部署：47313 pid `2610214`、47314 pid `2611342`；发布门禁 20 个测试通过，线上主 bundle 更新为 `index-bEXMX4D6.js`，两服务健康检查通过。
- 树图防重叠布局：预览改为固定可滚动视口，内部 ECharts 画布按当前可见叶子行数动态增高，每行预留 58px（高于 38px 椭圆节点）；展开/收起由组件统一控制并即时重算画布高度，大量属性不再被强压到固定高度。画布最小宽度 980px，窄窗口改为横向滚动，避免不同层级的椭圆和文字发生横向交叉。
- 防重叠提交 `7403242` 已推送并部署：47313 pid `2637437`、47314 pid `2638781`；发布门禁 20 个测试通过，线上主 bundle/CSS 更新为 `index-CilNwYst.js` / `index-B2AZdIOC.css`，两服务健康检查通过。
- 第一列起点修复：隐藏根虽然不可见但仍占用 ECharts 第一列空间，导致业务对象整体右移；现按是否存在业务对象将技术根移到视口外，有业务对象时直接从业务对象列开始，无业务对象时直接从逻辑实体列开始，同时保留正常左侧边距。
- 起点修复提交 `7d1be7d` 已推送并部署：47313 pid `2674784`、47314 pid `2676433`；发布门禁 20 个测试通过，线上主 bundle 更新为 `index-DaRn_0v-.js`，两服务健康检查通过。
- 根据实际视觉反馈继续微调第一列起点：三层树技术根偏移由 `-28%` 调至 `-32%`，两层树由 `-65%` 调至 `-71%`，第一列约再左移 25～30px，同时保留防裁切边距。
- 微调提交 `f85817f` 已推送并部署：47313 pid `2710428`、47314 pid `2711640`；发布门禁 20 个测试通过，线上主 bundle 更新为 `index-ee44do8i.js`，两服务健康检查通过。
- 全屏定位修复：全屏时不再继承 Ant Modal 的垂直居中布局，弹窗外层固定覆盖当前浏览器视口并锁定外层滚动，卡片从 `top: 0` 开始铺满；退出全屏后恢复默认居中，避免全屏卡片被排到当前页面下方。
- 全屏修复提交 `3298572` 已推送并部署：47313 pid `2751298`、47314 pid `2752664`；发布门禁 20 个测试通过，线上主 bundle/CSS 更新为 `index-D73hYdaY.js` / `index-BwjkoW1K.css`，两服务健康检查通过。
- 预览标题栏图标对齐：全屏/退出全屏按钮改为固定定位在关闭按钮左侧，统一 `top: 12px`、32px 点击区域并收紧右侧间距，确保与叉号始终处于同一水平行；标题右侧同步预留空间，长文件名不会覆盖操作按钮。
- 图标对齐提交 `e3be9cb` 已推送并部署：47313 pid `2778895`、47314 pid `2780119`；发布门禁 20 个测试通过，线上主 bundle/CSS 更新为 `index-Bo9Ksg8a.js` / `index-BkbfpntV.css`，两服务健康检查通过。
- 仅微调三层树业务对象列：技术根偏移由 `-32%` 调至 `-35%`，业务对象列约再左移 20px；无业务对象的两层树继续保持 `-71%`，逻辑实体起点不变。
- 混合归属列对齐：当正式业务对象与未归属业务对象的逻辑实体同时存在时，未归属实体不再作为第一层根落入业务对象列；新增不可见的占位父层并隐藏其节点/连线，只保留布局深度，使未归属实体与已归属实体统一显示在逻辑实体列。
- 列对齐提交 `954ccee` 已推送并部署：47313 pid `2799792`、47314 pid `2802043`；发布门禁 20 个测试通过，线上主 bundle 更新为 `index-BJSv_-jy.js`，两服务健康检查通过。
- 按相同视觉步长再次左移三层树业务对象列：技术根偏移由 `-35%` 调至 `-38%`，约再左移 20px；逻辑实体列、未归属实体占位层和无业务对象两层树位置均保持不变。
- 业务对象列左移提交 `878c38f` 已推送并部署：47313 pid `2820906`、47314 pid `2822251`；发布门禁 20 个测试通过，前端生产构建通过（仅保留既有大包体积提示），线上主 bundle 更新为 `index-C42oGBer.js`。
- 根据视觉反馈将三层树业务对象列明显左移约 100px：技术根偏移由 `-38%` 调至 `-48%`（按 980px 最小画布约为 98px），逻辑实体列及无业务对象两层树布局不变。
