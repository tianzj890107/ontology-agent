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
CREATED/INPUT_READY → QUEUED → ANALYZING → VALIDATING → READY_FOR_EXPORT
                                      └────────→ FAILED
```

外部调用在 `QUEUED`、`ANALYZING`、`VALIDATING` 和 `READY_FOR_EXPORT` 状态不能上传输入、重复执行或重复校验；外部 `validate` 不允许借用 execute 的内部 `ANALYZING → VALIDATING` 转换。状态来源检查和转换在同一个 run 锁内原子完成；服务重启时排队或处理中状态会恢复为 `FAILED` 并记录中断原因。

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

创建数据库建模 run 时只提交 `databaseSourceId` 和选中的 `selectedTables`；完整连接配置由 47314 服务端安全配置解析，不能由浏览器覆盖。

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

47314 通过 `MODELING_SERVER_MAX_ACTIVE_RUNS` 控制同时执行的 run 数，默认值为 `2`，允许范围为 `1` 到 `32`。超过并发上限的 run 先进入 `QUEUED`，空闲 worker slot 释放后自动进入 `ANALYZING`；排队不返回 `ACTIVE_RUN_EXISTS`。每个运行仍保持独立线程、会话、工作区和事件日志。

事件接口支持增量读取：客户端保存已消费的事件数量后，将其作为 `since` 参数传入，避免重复下载完整思考历史。`GET /api/modeling-runs/{runId}?includeEvents=false` 只返回运行摘要和文件列表，适合轮询状态；不传该参数时保留完整事件响应以兼容旧客户端。

### 查看文件

```http
GET /api/modeling-runs/{runId}
GET /api/modeling-runs/{runId}/files
GET /api/modeling-runs/{runId}/files/content?path=work/modeling_state.json
```

文件 API 只允许 `input/`、`work/`、`output/`，并按 run 隔离。路径穿越、绝对路径和 symlink 越界会被拒绝。
