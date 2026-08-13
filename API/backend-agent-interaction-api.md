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
- `SUCCEED`：拒绝再次获取 context。为兼容历史平台数据，Agent 读取状态时仍将 `SUCCESS`、`COMPLETED` 等旧成功状态按已完成处理，但新回调统一发送 `SUCCEED`。

数据库连接密码兼容平台的 `ConnectionConfigCrypto` 加密格式：`Base64(12 字节 IV || AES-GCM 密文+16 字节 Tag)`，密钥为部署配置 `ontology.crypto.secret` 解码后的 32 字节 AES-256 密钥。Agent 只在服务器配置了该密钥时解密，解密后的密码仅写入当前任务的受保护 `mission-input/.db_connection.json`，不会进入对话上下文。

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
| `BUSINESS_OBJECT_RELATION` | `business_object_relations.csv`（兼容 `business_object_relationships.csv`、`object_relations.csv`） |
| `STATUS` | `statuses.csv`（兼容 `status.csv`、`business_object_statuses.csv`） |
| `EVENT` | `events.csv`（兼容 `event.csv`、`business_events.csv`） |
| `RULE` | `business_rules.csv` |
| `TERM` | `business_terms.csv`（兼容 `terms.csv`） |
| `METRIC` | `metrics.csv`（兼容 `indicator.csv`） |
| `ACTIVITY` | `activities.csv` |
| `ACTIVITY_FLOW` | `activity_flows.csv`（兼容 `activity_flow.csv`） |

文档任务还会将 DOCX、PPTX、PDF 原文件下载至当前任务的 `mission-input/`，并生成同目录的文档 bundle：`manifest.json` 记录章节/页和表格，`content.md` 保存完整文本，`tables/*.csv` 保存可识别表格。Agent 必须先读取 manifest，再完整读取全部正文、章节/页和表格；输出文件严格受 `parseElements` 和 `expectedFiles` 约束：`parseElements` 是唯一的识别范围，`expectedFiles` 只指定具体文件名和上传白名单，不能反向增加识别要素。每一种已选择结果都可以独立生成和上传，不因其他类型 CSV 尚未生成而阻塞。

所有本体建模任务会自动在 `mission-input/` 放入四份固定参考文件：`Ontology平台模型编码规范v0.0.1.xlsx`、`本体元模型v0.0.1.xlsx`、`本体元模型模板v0.0.1.xlsx` 和 `本体元模型模板v0.0.1（含样例数据）.xlsx`。未带 `v0.0.1` 的历史文件不再作为新任务固定输入。`business_attributes.csv` 使用十六列表头，新增 `数据长度`、`数据精度`；无法取得或不适用时留空，不得猜测。`logical_entities.csv` 的 `是否主逻辑实体` 和业务属性布尔字段统一使用 `Y/N`；每个业务对象必须且只能有一个 `是否主逻辑实体=Y`。`是否唯一`表示业务上的唯一标识；复合业务唯一标识不得拆成多个单字段唯一。当前未实现维度输出时 `是否层级编码` 和 `是否层级名称` 全部填 `N`。同一逻辑实体同时存在 `XXX编码`（逻辑主键）和 `XXX名称` 时，`XXX名称` 的 `是否页面显示` 填 `Y`，其他业务属性填 `N`。模板的“逻辑实体映射”和“业务属性映射”仅作为参考输入，不进入结果文件清单。业务规则正式表头统一使用 `规则编码,规则名称,规则描述,触发条件,判断或结果,处置动作`；规则编码严格遵守编码规范中的 `R` + 7 位流水码，例如 `R0000001`。状态和事件暂未在编码规范中定义新编码前缀：已有稳定编码时沿用，无来源时标记待确认，不得自定格式。

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

SUCCEED：

```json
{
  "agentStatus": "SUCCEED",
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

`SUCCEED` 时 `files` 必须非空，每项必须包含：

- `parseElement`
- `filename`
- `objectKey`
- `previewUrl`

Agent 工作台状态约定：

- 用户真正发起 Agent 执行前回调一次 `RUNNING`；仅打开页面、恢复历史会话或读取任务信息不代表执行开始。
- 执行以不可恢复错误结束时回调 `FAILED`，并使用 `AGENT_EXECUTION_FAILED` 作为通用错误码。
- 结果上传至对象存储后仍保持 `RUNNING`。用户在工作台检查、修改并重新上传后，主动点击“完成”才发送 `SUCCEED`；点击“修改”会回调 `RUNNING` 以恢复编辑。
- 用户确认 `SUCCEED` 前，Agent 会校验全部 `expectedFiles` 都已上传，且本地文件内容仍与已上传版本一致。
- 点击“修改”时，工作台会先删除当前任务已上传的旧结果对象（整合任务至少包括 `ok.csv`），再回调 `RUNNING`，避免旧完成标记继续生效。
- 对象存储 `outputPrefix` 只采用服务端最新 execution-context 中的值；浏览器不负责提供可信前缀。即使兼容客户端仍传 `prefix`，也必须与服务端值完全一致，否则拒绝上传。
- 结果上传、任务执行和“完成/修改”共用同一任务状态锁。Agent 正在执行或状态正在切换时拒绝上传，避免上传快照和本地文件继续变化。
- 已完成任务必须先点击“修改”才能替换输入或重新执行；普通提问、致谢和结果评价只作为聊天，不会删除旧结果或自动把任务恢复为 `RUNNING`。
- 用户替换或新增任务输入后，之前的中间态和已上传结果记录立即失效，必须基于新输入重新执行并上传全部结果；内容完全相同的重复上传保持幂等。
- 建模成功回调除校验 `objectKey`、本地 SHA-256 外，还校验每个文件具备非空 `previewUrl`，避免平台收到不可预览的完成结果。

### 4.3 建模计划、任务中间态与独立导出

建模任务的执行身份由以下四个字段共同决定，Agent 不得跨身份复用输入、结果或上游引用：

```text
repositoryId + taskCode + modelVersion + inputFingerprint
```

建模计划通过 execution-context 的 `modelingPlan` 返回，使用以下 artifact 对任务内分析结果进行分类和追踪：

```text
termArtifact             （术语分析）
logicalModelArtifact     （候选属性、逻辑实体、业务属性、实体关系）
businessObjectArtifact   （实体族、候选主实体、R1–R5 结论）
ruleArtifact             （规则分析）
metricArtifact           （指标分析）
```

执行与导出约束：

- `parseElements` 是唯一的识别范围；`expectedFiles` 只约束文件名和上传白名单。
- execution-context 中两者必须双向一致：`expectedFiles` 不得包含未选择要素的文件，每个可输出的已选择要素也必须有对应文件；契约不一致时在执行和上传前直接返回配置错误，不删除已有结果。
- 每一种已选择结果文件均可独立导出和上传；例如只请求 `BUSINESS_OBJECT`、`RULE` 或 `METRIC` 时，不要求先上传逻辑模型或业务对象 CSV。
- 同一任务请求多个类型时，Agent 可以复用任务目录 `mission-work/modeling_state.json` 中的结构化资产盘点、候选结果、证据和校验信息。
- `mission-work/modeling_state.json` 是任务内部中间态，不上传、不进入完成回调，也不能作为额外正式输出。
- 中间态绑定当前输入指纹；数据库表、文档对象或其他嵌套输入描述发生变化时，旧状态仅归档审计，不再参与本轮生成。
- 正式结果只写入 `mission-output/`，只生成 `parseElements` 已选择且 `expectedFiles` 允许的文件；不得额外生成未选择类型的 CSV。
- artifact 的 `dependsOn`、执行顺序和跨任务引用用于描述分析血缘与质量检查，不作为正式结果文件之间的上传阻断条件。

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
  "agentStatus": "SUCCEED",
  "occurredAt": "2026-07-20T11:00:00+08:00",
  "errorCode": null,
  "errorMessage": null
}
```

整合回调不传 `files`。用户确认完成并发送 `SUCCEED` 后，Ontology 后端按 `outputPrefix` 和当前 `expectedFiles` 读取并导入结果；如果上下文包含 `business_rules.csv`，它也属于本次结果文件，必须使用当前六列表头，不能只生成前三列的旧模板格式。

Agent 成功时还需上传：

```text
ontology/{repositoryId}/integration-tasks/{taskCode}/agent-output/ok.csv
```

`ok.csv` 是整合完成标记，不放入 `expectedFiles` 列表。Agent 必须先生成并验证全部 `expectedFiles`，最后再上传 `ok.csv`；上传完成后任务仍保持 `RUNNING`，未上传 `ok.csv` 或任一结果文件校验失败时，用户无法在工作台确认并发送 `SUCCEED`。用户点击“修改”时，Agent 会删除已上传的旧结果（至少包括 `ok.csv`）并回调 `RUNNING`。

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
