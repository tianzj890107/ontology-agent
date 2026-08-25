# 独立通用建模服务 API

独立服务运行在 `47314`，现有工作台 `47313` 保持原接口和任务模型不变。服务按一次建模运行分配独立工作区，不绑定外部 `taskCode` 或业务任务。

## 工作区

每个 run 只有一个真实 workspace：

```text
<run>/input/
<run>/work/
<run>/output/
```

现有建模引擎内部使用的 `mission-input`、`mission-work`、`mission-output` 是同一 workspace 内的安全别名，不是第二份数据。

客户端的 `inputs` 接口只能写入 `input/`；`work/`、`output/`、审计文件和状态文件由建模执行器/校验器独占写入。

## 状态

```text
CREATED/INPUT_READY → QUEUED → CLAIMED → ANALYZING → VALIDATING → SUCCEEDED
                         │          └────→ CANCELLING → CANCELLED
                         └──────────────────────────────────────────────→ FAILED
```

外部调用在 `QUEUED`、`CLAIMED`、`ANALYZING`、`VALIDATING`、`CANCELLING` 和 `SUCCEEDED` 状态不能上传输入、重复执行或重复校验；外部 `validate` 不允许借用 execute 的内部 `ANALYZING → VALIDATING` 转换。状态来源检查和转换在同一个 run 锁及 Repository 条件写入内原子完成；服务重启时已 claim/处理中状态会恢复为 `FAILED` 并记录中断原因，尚未 claim 的 `QUEUED` run 保留并由新 scheduler 接续。

显式调用 `validate` 会执行现有语义 finalize、决策审计和正式输出一致性校验。审计文件落在 `work/`，正式 CSV 落在 `output/`。

## 认证

生产启动脚本会在仓库根目录生成权限为 `600` 的 `.standalone-modeling-api-key`，请求使用：

```http
X-Modeling-API-Key: <key>
```

`/health` 不需要认证。未配置 key 时只允许本机访问，避免误把新端口暴露成未认证服务。

## 接口

### 创建运行并上传输入

```http
POST /api/modeling-runs
Content-Type: application/json

{
  "sourceMode": "DATABASE",
  "prompt": "根据输入资料建立本体模型",
  "requestedArtifacts": ["business_objects.csv", "logical_entities.csv"],
  "database": {
    "databaseSourceId": 12,
    "dbType": "POSTGRESQL",
    "host": "db.internal",
    "port": 5432,
    "database": "ontology",
    "username": "ontology_agent",
    "password": "ConnectionConfigCrypto ciphertext",
    "sourceSchema": "public",
    "selectedTables": ["purchase_order"]
  },
  "files": [
    {"name": "input/schema.json", "content": "{...}"}
  ]
}
```

`database` 使用与 47313 execution-context 相同的字段和连接逻辑；也可传等价的 `dataSource`，但不能同时传两者。47314 会复用 47313 的 `write_mission_database_config`、`ensure_database_helpers` 和 `db_connection.py`，在当前 run 的 input namespace 中生成连接 helper。加密密码使用 `ConnectionConfigCrypto` 的 AES-GCM 格式，并要求 47314 进程配置同一 `ontology.crypto.secret`；密码不会出现在 API 响应中。数据库必须从 47314 服务器网络可达。

### 数据库下拉选择

独立服务支持先选择服务端已配置的数据源，再读取该数据源的 Schema 和数据表。前端不接触 Host、用户名或密码。

```http
GET /api/modeling-data-sources
X-Modeling-API-Key: <key>
```

返回的数据源只包含可展示元数据：

```json
{
  "sources": [
    {
      "id": "12",
      "name": "Ontology 数据库（guangfeng）",
      "dbType": "POSTGRESQL",
      "database": "ontology",
      "sourceSchema": "guangfeng"
    }
  ]
}
```

读取表清单：

```http
GET /api/modeling-data-sources/{databaseSourceId}/tables
X-Modeling-API-Key: <key>
```

读取可选 Schema（PG 支持多选）：

```http
GET /api/modeling-data-sources/{databaseSourceId}/schemas
X-Modeling-API-Key: <key>
```

选择多个 Schema 后可通过重复的 `schemas` 查询参数读取合并后的表清单，例如
`/tables?schemas=ontology_dev&schemas=po`。创建数据库建模 run 时提交
`databaseSourceId`、`selectedSchemas` 和选中的 `selectedTables`；完整连接配置由
47314 服务端安全配置解析，不能由浏览器覆盖。

浏览器访问页面后由服务端签发短期 HttpOnly 会话 Cookie，页面内 API 请求不再要求用户手填长期 API Key。程序化客户端仍可使用 `X-Modeling-API-Key`。

数据库数据源使用服务端专用只读账号，并在 PostgreSQL 连接中设置 `default_transaction_read_only=on`；数据库密码和加密配置不会下发到浏览器。
运行工作区中的 `db_connection.py` 会在内存中解密密码，并按数据源的 `sourceSchema` 设置 PostgreSQL `search_path`；Agent 不得直接把 `.db_connection.json` 中的加密值当作明文密码使用。

也可以通过 `POST /api/modeling-runs/{runId}/inputs` 后续写入文件；二进制内容使用 `contentBase64`。`files` 必须是对象数组，每个元素必须有字符串 `name`/`path`，内容必须是字符串或合法 Base64；畸形请求整体返回 `422`，且在创建接口中不会创建 run 或工作目录。`requestedArtifacts` 未提供时使用默认集合；显式空数组、未知文件名和混合非法值都会返回 `422`，也不会留下孤儿 run 目录。

### 执行与校验

```http
POST /api/modeling-runs/{runId}/execute
POST /api/modeling-runs/{runId}/validate
```

`execute` 异步运行，事件通过 `GET /api/modeling-runs/{runId}/events?since=0` 查询。`validate` 只在当前 run 的 `work/` 和 `output/` 上执行。

`FAILED` run 可以再次调用 `execute` 继续运行，复用该 run 已保存的输入、提示词和工作区；历史运行列表可重新打开失败 run。运行中的 `QUEUED`/`ANALYZING`/`VALIDATING` run 仍不可重复执行。

47314 使用有界 worker pool 和公平调度：在线用户默认 `100`，全局 active run 默认 `10`，单用户 active run 默认 `3`，单用户 queued run 默认 `3`，全局 queued run 默认 `50`。超过 active 上限的第 11 个任务进入 `QUEUED`，不会直接失败；超过在线用户、用户队列或全局队列上限分别返回 `ONLINE_USER_LIMIT_REACHED`、`USER_QUEUE_LIMIT_REACHED` / `GLOBAL_QUEUE_FULL`（HTTP 429）。通过 `MODELING_SERVER_MAX_ONLINE_USERS`、`MODELING_SERVER_MAX_ACTIVE_RUNS`、`MODELING_SERVER_MAX_ACTIVE_PER_USER`、`MODELING_SERVER_MAX_QUEUED_PER_USER`、`MODELING_SERVER_MAX_QUEUED` 可配置。

排队、配额、provider/database semaphore、租约与 fencing 由 47313/47314 共享的 `ExecutionCoordinator` 负责，两个服务使用同一套公平调度与游标/事件窗口语义（`open_claude/execution_coordinator.py`、`open_claude/execution_lease.py`、`open_claude/event_window.py`）。47314 协调后端默认 `file`（同主机多进程安全，`multiHostSafe=false`），可用 `MODELING_SERVER_COORDINATOR_BACKEND=redis` + `MODELING_REDIS_URL`（或 `REDIS_URL`）启用跨实例模式；租约目录可用 `MODELING_SERVER_LEASE_DIR` 配置，租约/心跳间隔为 `MODELING_SERVER_LEASE_SECONDS` / `MODELING_SERVER_HEARTBEAT_SECONDS`。47313 使用同一套 coordinator：`TASKS_COORDINATOR_BACKEND=file|redis|none`（默认 `file`），Redis 时读取 `TASKS_REDIS_URL`（回退 `REDIS_URL`）与 `TASKS_REDIS_PREFIX`（默认 `ontology:47313:`），并安装 `open-claude[redis]` 可选依赖。Redis 后端启用时全局 active/queued、单用户配额、队列顺序、owner、lease 与 fence 均保存在 Redis，多实例不会叠加计数；Redis 不可用时启动失败，不静默退化。

协调后端能力边界：file 后端同一任务 lease 为同主机多进程安全，但 active/queued 配额与公平队列仅限单进程（`quotaScope=process`、`queueScope=process`、`multiHostSafe=false`）；redis 后端任务 lease、active/queued 与单用户配额、公平队列均为集群共享（`quotaScope=cluster`、`queueScope=cluster`、`multiHostSafe=true`）。

`/health` 的 `concurrency` 与 `coordination` 字段为 47313/47314 统一结构：`concurrency` 含 `activeRuns/queuedRuns/maxActiveRuns/maxActivePerUser/maxQueuedPerUser/maxQueuedRuns/oldestQueuedSeconds/providerConcurrency/providerInUse/databaseConcurrency/databaseInUse`；`coordination` 含 `backend/instanceId/multiProcessSafe/multiHostSafe/leaseSeconds/heartbeatSeconds/activeLeases/expiredLeasesRecovered`，不暴露 userId、Redis URL、密码或租约 token。

每个被 claim 的 attempt 记录 `attemptId`、`attemptNumber`、`workerId`、lease 和 heartbeat；worker 丢失后由 lease recovery 标记为 `FAILED` 并记录 `worker_lost`。Run 元数据通过共享 SQLite Repository 持久化（`.runs.sqlite3`），`.runs.json` 仅作为兼容快照；后续可无业务层改动切换 PostgreSQL Repository。事件带有 `userId`、`runId` 和 `attemptId`，API 列表、详情和事件按用户隔离。

事件接口支持增量读取：客户端保存已消费的事件数量后，将其作为 `since` 参数传入，避免重复下载完整思考历史。`GET /api/modeling-runs/{runId}?includeEvents=false` 只返回运行摘要和文件列表，适合轮询状态；不传该参数时保留完整事件响应以兼容旧客户端。

### 查看文件

```http
GET /api/modeling-runs/{runId}
GET /api/modeling-runs/{runId}/files
GET /api/modeling-runs/{runId}/files/content?path=work/modeling_state.json
```

文件 API 只允许 `input/`、`work/`、`output/`，并按 run 隔离。路径穿越、绝对路径和 symlink 越界会被拒绝。
