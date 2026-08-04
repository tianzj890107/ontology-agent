# Agent 联调 API 文档

> 适用范围：Agent 调用 Ontology 后端获取执行上下文、回调状态和查询本体库信息。  
> 本文只描述 Agent 调用 Ontology 后端的接口。

## 1. 调用方向

调用方向：

```text
Agent ──获取执行上下文────────→ Ontology 后端
Agent ──回调任务状态──────────→ Ontology 后端
Agent ──获取本体库信息────────→ Ontology 后端
```

## 2. 接口清单

| 调用方 | 接口提供方 | 方法 | 路径 | 用途 |
|---|---|---|---|---|
| Agent | Ontology 后端 | `GET` | `/intelligent/modeling/tasks/{taskCode}/execution-context` | 获取智能建模上下文 |
| Agent | Ontology 后端 | `POST` | `/intelligent/modeling/tasks/{taskCode}/callback` | 回调智能建模状态和结果文件 |
| Agent | Ontology 后端 | `GET` | `/intelligent/integration/tasks/{taskCode}/execution-context` | 获取消歧整合上下文 |
| Agent | Ontology 后端 | `POST` | `/intelligent/integration/tasks/{taskCode}/callback` | 回调消歧整合状态 |
| Agent | Ontology 后端 | `GET` | `/system/manager/ontology-repository` | 分页查询本体库列表 |
| Agent | Ontology 后端 | `GET` | `/system/manager/ontology-repository/{repositoryId}` | 获取本体库信息 |

## 3. 公共约定

### 3.1 请求头

```http
X-Ontology-Repository-Id: 1
Content-Type: application/json
```

`X-Ontology-Repository-Id` 必须是任务所属的本体库 ID。

Agent 使用 `taskCode` 调用任务接口，实际唯一定位条件为：

```text
(X-Ontology-Repository-Id, taskCode)
```

Agent 调用 `/tasks/{taskCode}/...` 时必须传 `taskCode`。

数据库仍以 `(repository_id, id)` 作为复合主键，同时在本体库内约束 `task_code` 唯一。Agent 接口按 `repositoryId + taskCode` 查询任务，不在 Query 或 Body 中重复传 `repositoryId`，避免同一个值出现两个来源。

联调及生产环境必须配置：

```yaml
ontology:
  repository:
    required: true
```

否则漏传 Header 时会使用默认本体库 ID，可能查询到默认本体库中相同 `taskCode` 的任务。

当前代码没有为 Agent 接口实现单独的服务身份鉴权：相关 Controller 没有权限注解，且仓库默认配置 `spring.security.enabled=false`。如果部署环境通过网关增加鉴权，以实际网关配置为准。

### 3.2 响应结构

Ontology 后端统一返回 `ApiResponse<T>`：

```json
{
  "success": true,
  "code": 200,
  "msg": null,
  "data": {}
}
```

失败时读取 `msg`：

```json
{
  "success": false,
  "code": 400,
  "msg": "任务状态不允许执行",
  "data": null
}
```

### 3.3 时间格式

`occurredAt` 使用 ISO-8601 带时区格式：

```text
2026-07-20T10:30:00+08:00
```

## 4. 智能建模接口

### 4.1 获取执行上下文

```http
GET /intelligent/modeling/tasks/{taskCode}/execution-context
X-Ontology-Repository-Id: 1
```

响应 `data` 示例：

```json
{
  "repositoryId": 1,
  "taskCode": "RM123456789",
  "taskName": "采购库智能建模",
  "modelName": "采购域模型",
  "taskType": "DATA_SOURCE_MODELING",
  "prompt": "优先识别采购订单与供应商",
  "parseElements": [
    "BUSINESS_OBJECT",
    "LOGICAL_ENTITY",
    "BUSINESS_ATTRIBUTE"
  ],
  "expectedFiles": [
    "business_objects.csv",
    "logical_entities.csv",
    "business_attributes.csv"
  ],
  "outputPrefix": "ontology/1/modeling-tasks/RM123456789/agent-output",
  "database": {
    "databaseSourceId": 12,
    "dbType": "POSTGRESQL",
    "host": "127.0.0.1",
    "port": 5432,
    "database": "purchase",
    "username": "ontology_agent",
    "password": "decrypted-password",
    "sourceSchema": "public",
    "selectedTables": ["purchase_order", "supplier"]
  },
  "document": null
}
```

状态规则：

- `PENDING` 或 `FAILED`：首次获取 context 后进入 `RUNNING`。
- `RUNNING`：重复获取 context 幂等返回。
- `SUCCESS`：拒绝再次获取 context。

`taskType=DOCUMENT_MODELING` 时，`database` 为 `null`，`document` 返回：

```json
{
  "fileSourceId": 25,
  "fileType": "PDF",
  "objectKey": "ontology/1/data-sources/25/source.pdf"
}
```

解析要素与输出文件对应关系：

| `parseElement` | 输出文件 |
|---|---|
| `BUSINESS_OBJECT` | `business_objects.csv` |
| `LOGICAL_ENTITY` | `logical_entities.csv` |
| `BUSINESS_ATTRIBUTE` | `business_attributes.csv` |
| `ENTITY_RELATION` | `entity_relations.csv` |
| `RULE` | `business_rules.csv` |

### 4.2 状态回调

```http
POST /intelligent/modeling/tasks/{taskCode}/callback
X-Ontology-Repository-Id: 1
Content-Type: application/json
```

RUNNING：

```json
{
  "agentStatus": "RUNNING",
  "occurredAt": "2026-07-20T10:30:00+08:00",
  "errorCode": null,
  "errorMessage": null,
  "files": null
}
```

FAILED：

```json
{
  "agentStatus": "FAILED",
  "occurredAt": "2026-07-20T10:33:00+08:00",
  "errorCode": "SOURCE_READ_FAILED",
  "errorMessage": "无法读取指定数据表",
  "files": null
}
```

COMPLETED：

```json
{
  "agentStatus": "COMPLETED",
  "occurredAt": "2026-07-20T10:35:00+08:00",
  "errorCode": null,
  "errorMessage": null,
  "files": [
    {
      "parseElement": "BUSINESS_OBJECT",
      "filename": "business_objects.csv",
      "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv",
      "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv"
    }
  ]
}
```

`COMPLETED` 时 `files` 必须非空，每项必须包含：

- `parseElement`
- `filename`
- `objectKey`
- `previewUrl`

Agent 工作台状态约定：

- 用户真正发起 Agent 执行前回调一次 `RUNNING`；仅打开页面、恢复历史会话或读取任务信息不代表执行开始。
- 执行以不可恢复错误结束时回调 `FAILED`，并使用 `AGENT_EXECUTION_FAILED` 作为通用错误码。
- 结果上传至对象存储后，Agent 校验全部 `expectedFiles` 都已上传，且本地文件内容仍与已上传文件一致；校验通过即自动发送 `COMPLETED`。结果不完整时保持 `RUNNING`，可继续上传。

### 4.3 分层建模计划与 artifact 依赖

建模任务的执行身份由以下四个字段共同决定，Agent 不得跨身份复用输入、结果或上游引用：

```text
repositoryId + taskCode + modelVersion + inputFingerprint
```

建模计划通过 execution-context 的 `modelingPlan` 返回，包含以下固定 artifact 图：

```text
termArtifact                 （独立）
logicalModelArtifact         （候选属性 → 逻辑实体 → 正式业务属性 → 实体关系）
        ↓ 校验通过
businessObjectArtifact       （实体族 → 候选主实体 → R1–R5 → CONFIRMED/CANDIDATE/REJECTED）
        ↓ 已完成业务对象
ruleArtifact                 （RULE）
metricArtifact               （METRIC）
```

依赖约束：

- `TERM` 可以单独执行，不依赖其他 artifact；
- `BUSINESS_ATTRIBUTE` 必须先有 `LOGICAL_ENTITY`，`ENTITY_RELATION` 必须先有逻辑实体和正式业务属性；
- `BUSINESS_OBJECT` 必须在逻辑模型校验通过后执行；
- `RULE`、`METRIC` 必须引用已完成的 `businessObjectArtifact`，不能从物理输入直接生成；
- 同一任务请求多层时按上述顺序执行；跨任务使用上游结果时，必须在 context 中提供状态为 `COMPLETED/CONFIRMED/PASSED` 的 artifact 引用；
- 缺少依赖时 Agent 在真正执行前回调 `FAILED`，错误码为 `MODELING_DEPENDENCY_BLOCKED`，不会生成或上传下游结果。

## 5. 消歧整合接口

### 5.1 获取执行上下文

```http
GET /intelligent/integration/tasks/{taskCode}/execution-context
X-Ontology-Repository-Id: 1
```

响应 `data` 示例：

```json
{
  "taskCode": "MI123456789",
  "modelName": "采购域标准模型",
  "sourceMode": "MODELING_TASKS",
  "sourceModels": {
    "mode": "MODELING_TASKS",
    "items": [
      {"taskCode": "RM123456789"},
      {"taskCode": "RM123456790"}
    ]
  },
  "checkTypes": ["CONSISTENCY"],
  "validationRules": {},
  "integrationStrategy": {
    "semanticSimilarityThreshold": 0.85
  },
  "prompt": "同义实体优先合并",
  "outputPrefix": "ontology/1/integration-tasks/MI123456789/agent-output",
  "expectedFiles": [
    "business_objects.csv",
    "logical_entities.csv",
    "business_attributes.csv",
    "entity_relations.csv",
    "integration_report.csv",
    "merged_elements.csv",
    "pending_elements.csv",
    "conflict_elements.csv",
    "missing_elements.csv"
  ]
}
```

当前响应不包含 `repositoryId`，但这不影响后端唯一定位任务：本次 context 请求已经通过 `X-Ontology-Repository-Id + taskCode` 完成了隔离查询。Agent 必须在调用前持有任务所属的 `repositoryId`，并用于本次及后续请求头和结果文件路径。

### 5.2 状态回调

```http
POST /intelligent/integration/tasks/{taskCode}/callback
X-Ontology-Repository-Id: 1
Content-Type: application/json
```

```json
{
  "agentStatus": "COMPLETED",
  "occurredAt": "2026-07-20T11:00:00+08:00",
  "errorCode": null,
  "errorMessage": null
}
```

整合回调不传 `files`。`COMPLETED` 时，Ontology 后端按 `outputPrefix` 和当前 `expectedFiles` 读取并导入结果；如果上下文包含 `business_rules.csv`，它也属于本次强制结果文件，不能只生成前三列的建模模板格式。

Agent 成功时还需上传：

```text
ontology/{repositoryId}/integration-tasks/{taskCode}/agent-output/ok.csv
```

`ok.csv` 是整合完成标记，不放入 `expectedFiles` 列表。Agent 必须先生成并验证全部 `expectedFiles`，最后再上传 `ok.csv`；未上传 `ok.csv` 或任一结果文件校验失败时，用户无法在工作台确认 `COMPLETED` 回调。

## 6. 本体库信息接口

### 6.1 查询本体库列表

```http
GET /system/manager/ontology-repository?page=1&size=100&name=开发联调
```

Query 参数：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `page` | int | 否 | `1` | 页码，从 1 开始 |
| `size` | int | 否 | `10` | 每页条数，最大 100 |
| `name` | string | 否 | 无 | 按本体库名称模糊查询 |

不传 `name` 时分页列出全部本体库。界面下拉框可以使用 `size=100`；如果响应中的 `total` 大于当前已获取数量，需要继续请求下一页。

响应 `data`：

```json
{
  "items": [
    {
      "id": 1,
      "name": "开发联调本体库",
      "description": "开发联调使用",
      "namespaceCode": "dev_integration",
      "cdcTopicPrefix": "ontology_dev_integration",
      "arcadedbMetaDatabase": "ontology_dev_integration_all_meta",
      "arcadedbKnowledgeDatabase": "ontology_dev_integration_all_knowledge",
      "dorisDatabase": "ontology_dev_integration",
      "version": 5,
      "createdAt": "2026-07-01T10:00:00+08:00",
      "updatedAt": "2026-07-20T10:00:00+08:00",
      "createdBy": "admin",
      "updatedBy": "admin"
    }
  ],
  "total": 4,
  "page": 1,
  "size": 100
}
```

### 6.2 按 ID 获取本体库

```http
GET /system/manager/ontology-repository/{repositoryId}
```

响应 `data`：

```json
{
  "id": 1,
  "name": "采购域本体库",
  "description": "采购领域标准本体",
  "namespaceCode": "purchase",
  "cdcTopicPrefix": "purchase",
  "arcadedbMetaDatabase": "ontology_purchase_meta",
  "arcadedbKnowledgeDatabase": "ontology_purchase_knowledge",
  "dorisDatabase": "ontology_purchase",
  "version": 5,
  "createdAt": "2026-07-01T10:00:00+08:00",
  "updatedAt": "2026-07-20T10:00:00+08:00",
  "createdBy": "admin",
  "updatedBy": "admin"
}
```

Agent 只调用上述两个查询接口，不调用同一 Controller 下的新增、修改和删除接口。这两个路径被本体库拦截器排除，因此不要求 `X-Ontology-Repository-Id`；详情接口以路径中的 `repositoryId` 查询。
