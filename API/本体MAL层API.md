# 本体MAL层API

# 访问方式

| 方式 | Base URL 示例 | 鉴权 |
| --- | --- | --- |
| 直连服务 | `http://<host>:<port>` | 无鉴权，需请求头 `X-Ontology-Repository-Id: <本体库 ID>` |
| 统一网关 | `http://pdt-dev.eimos.com/api/gateway2/ontology/xxxx` | 需请求头 `X-App-Id: <应用 ID>;`<br>需请求头`X-Ontology-Repository-Id: <本体库 ID>` |

应用id : ApTH1EHKdRk58WhDQB

直连访问地址：http://172.16.5.181:30834

**本体库 Header：**

| Header | 说明 |
| --- | --- |
| `X-Ontology-Repository-Id` | 本体库 ID（Long），告知服务操作哪个本体库；后端按此隔离分区数据 |

示例：

```http
X-Ontology-Repository-Id: 1
```

# 接口响应通用说明

所有接口响应均使用统一包装体 ：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | int | 业务状态码 |
| `msg` | string \| null | 错误描述，成功时为 `null` |
| `data` | object \| null | 业务载荷 |

# 接口列表

## 元数据检索

### 意图确认

**接口描述**：根据对象元数据英文名在候选本体类型中确认其真实类型，并返回该元数据的全部属性信息。

**请求方法：** `POST`

**请求路径：** `/agent/ontology/ensureOntologyObject`

**Content-Type：** `application/json`

**请求参数**

| 参数 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `name` | string | 是 | 元数据英文名，如 `prHeader`、`prHeaderId` |
| `candidateTypes` | string\[\] | 是 | 候选本体类型名列表，按顺序优先匹配, 不能为空数组 |

`candidateTypes` 取值为本体对象英文名，例如：`BusinessObject`、`LogicalEntity`、`BusinessAttribute`、`Term`、`Dimension`、`Indicator`、`TableNode`、`Column`

**请求示例**

```http
POST /agent/ontology/ensureOntologyObject
Content-Type: application/json
{
  "name": "prHeader",
  "candidateTypes": ["BusinessObject", "LogicalEntity", "TableNode", "BusinessAttribute"]
}

```

**返回参数**（`data` 字段）

| 参数 | 类型 | 含义 |
| --- | --- | --- |
| `found` | boolean | 是否在候选类型中命中 |
| `objectInfo` | object \| null | 匹配成功时有值 |

**响应示例**

命中：

```json
{
  "code": 200,
  "msg": null,
  "data": {
    "found": true,
    "objectInfo": {
      "typeName": "LogicalEntity",
      "properties": {
        "code": "LE000001",
        "label": "采购需求头",
        "name": "prHeader",
        "description": "是指一份采购需求申请单的摘要和控制信息，用于汇总一份完整的物资或服务申请，并驱动后续的审批、寻源和采购流程。主要属性包括：需求单号、申请人、申请部门、需求日期、需求状态、采购类型等。",
        "typeName": "LogicalEntity"
      }
    }
  }
}

```

未命中：

```json
{
  "code": 200,
  "msg": null,
  "data": {
    "found": false,
    "objectInfo": null
  }
}

```

参数非法（示例）：

```json
{
  "code": 400,
  "msg": "name 与 candidateTypes 不能为空",
  "data": null
}

```

### 关联实体查询

**接口说明：**从指定本体对象出发，按顶点跳数查询关联对象列表

**请求方法：** `GET`

**请求路径：**`/agent/ontology/findRelatedObjects`

**请求参数**

| 参数 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `type` | string | 是 | 起点对象类型，如 `BusinessObject` |
| `code` | string | 是 | 起点对象编码，如 `BO0004` |
| `depth` | int | 是 | 图遍历深度，必须 >= 1（表示顶点跳数） |

**请求示例**

```http
GET /agent/ontology/findRelatedObjects?type=BusinessObject&code=BO0004&depth=2
```

**返回参数**（`data` 字段）

| 参数 | 类型 | 含义 |
| --- | --- | --- |
| `objects` | array | 关联实体列表（按 `typeName:code` 去重） |

**响应示例**

```plaintext
{
  "code": 200,
  "msg": null,
  "data": {
    "objects": [
      {
        "typeName": "Term",
        "properties": {
          "code": "T000006",
          "label": "采购需求",
          "name": "Purchase Request",
          "description": "采购需求是采购执行的来源和依据，是对确定性采购对象的结构化描述，支撑供应资源准备及采购订单生成，包含需求组织、需求日期、商品规格、需求数量等信息。",
          "alias": "采购单",
          "abbreviation": "PR",
          "typeName": "Term"
        }
      },
      {
        "typeName": "LogicalEntity",
        "properties": {
          "code": "LE000001",
          "label": "采购需求头",
          "name": "prHeader",
          "description": "是指一份采购需求申请单的摘要和控制信息，用于汇总一份完整的物资或服务申请，并驱动后续的审批、寻源和采购流程。主要属性包括：需求单号、申请人、申请部门、需求日期、需求状态、采购类型等。",
          "typeName": "LogicalEntity"
        }
      }
    ]
  }
}
```

### 自定义SQL 查询

**接口说明：**在 ArcadeDB 本体图谱上执行**只读**查询脚本，支持 Gremlin / Cypher / SQL 查询

**请求方法：** `POST`

**请求路径：**`/agent/ontology/scriptQuery`

**请求参数**

| 参数 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `language` | string | 是 | 查询语言；大小写不敏感 |
| `script` | string | 是 | 查询脚本 |
| `paramsList` | array<array<any>> | 否 | 与语句对应的参数列表 |

> `paramsList` 可省略，仅当脚本含占位符时才传入

**请求示例**

```http
POST /agent/ontology/scriptQuery
Content-Type: application/json

{
  "language": "sql",
  "script": "SELECT code, name, label FROM BusinessObject LIMIT 5"
}

```
```http
POST /agent/ontology/scriptQuery
Content-Type: application/json

{
  "language": "opencypher",
  "script": "MATCH (bo:BusinessObject {code: 'BO0004'})-[r]->(le:LogicalEntity) RETURN bo.code AS boCode, le.code AS leCode, le.name AS leName LIMIT 20"
}

```
```http
POST /agent/ontology/scriptQuery
Content-Type: application/json

{
  "language": "gremlin",
  "script": "g.V().hasLabel('BusinessObject').has('code', 'BO0004').out().limit(20)"
}

```
```http
{
  "language": "opencypher",
  "script": "MATCH (s:LogicalEntity)-[r:LEAssociateLE]->(t:LogicalEntity) WHERE s.code IN $codes AND t.code IN $codes RETURN s.code AS s_code, s.name AS s_name, r.relationAttributeMapping AS mapping, t.code AS t_code, t.name AS t_name",
  "paramsList": [
    ["codes", ["LE000001", "LE000002", "LE000010", "LE000011"]]
  ]
}
```

**返回参数**（`data` 字段）

成功时 `data` 结构如下：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `statementCount` | int | 成功执行的语句条数 |
| `results` | array<OntologyScriptStatementResult> | 每条语句的查询结果，顺序与请求中语句顺序一致 |

`**OntologyScriptStatementResult**`**：**

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `rowCount` | int | 当前语句返回的行数 |
| `rows` | array<object> | 结果行列表；每行为列名到值的键值对（`Map<String, Object>`） |

**响应示例**

```json
{
  "success": true,
  "code": 200,
  "msg": null,
  "data": {
    "statementCount": 1,
    "results": [
      {
        "rowCount": 1,
        "rows": [
          {
            "code": ["BO0004"],
            "name": ["PurchaseRequest"],
            "label": ["采购需求"]
          }
        ]
      }
    ]
  }
}

```

### 分页查询本体列表

#### 基本信息

**接口说明**：分页查询本体库列表

**请求方法**：`GET`

**相对路径**：/system/manager/ontology-repository

**Content-Type**：`application/json`

#### 请求参数

| 参数 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `page` | int | 否 | `1` | 页码，从 1 开始 |
| `size` | int | 否 | `10` | 每页条数，最大 100 |
| `name` | string | 否 | 无 | 按本体库名称模糊查询 |

请求示例

```http
GET /system/manager/ontology-repository?page=1&size=100&name=开发联调

```

#### 返回参数（`data` 字段）

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

### 获取本体库信息

#### 基本信息

**接口说明**：获取指定本体库的全部信息

**请求方法**：`GET`

**相对路径**：/system/manager/ontology-repository/{repositoryId}

**Content-Type**：`application/json`

请求示例

GET /system/manager/ontology-repository/1

#### 返回参数（`data` 字段）

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

### 本体元数据查询

#### 基本信息

**接口说明**：`analysisConfig` 只声明**需要返回**的点类型、边类型及其属性；凡不进入结果、仅用于收窄过滤范围的对象与关联关系，由上游在 `commonConfig.filters` 的 `children` 中显式列举（属性条件与关联边一并列出）。返回结果形态由接口内部实现自动推断。

**请求方法**：`POST`

**相对路径**：`api/v1/analysis/meta/query`

**Content-Type**：`application/json`

#### 请求参数

| 参数层级 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| `analysisConfig` | Object | 是 | 查询配置。定义本次查询涉及的本体类型、关系以及需要返回的点属性和边属性。 |
| `analysisConfig.vertex` | Array | 是 | 本体点声明列表，至少包含一个本体点。 |
| `analysisConfig.vertex[].type` | String | 是 | 本体点类型，如 `Indicator`、`BusinessAttribute`、`LogicalEntity`。 |
| `analysisConfig.vertex[].label` | String | 否 | 本体点的前端展示名称，如“指标”。 |
| `analysisConfig.vertex[].properties` | Array | 否 | 需要返回的点属性列表。未传或为空数组时，返回该点的默认业务属性。 |
| `analysisConfig.vertex[].properties[].name` | String | 是 | ArcadeDB 中真实的点属性名，如 `code`、`name`。 |
| `analysisConfig.vertex[].properties[].label` | String | 否 | 点属性的前端展示名称，如“指标编码”。 |
| `analysisConfig.link` | Array | 否 | 关系声明列表。只查询单个本体点时可以不传。 |
| `analysisConfig.link[].type` | String | 是 | 关系边类型，如 `IndicatorCalculateToIndicator`、`IndicatorIsDrilledByDimension`。 |
| `analysisConfig.link[].label` | String | 否 | 关系边的前端展示名称，如“计算来源”。 |
| `analysisConfig.link[].sourceType` | String | 否 | 起点的 Type。 |
| `analysisConfig.link[].targetType` | String | 否 | 终点的 Type。 |
| `analysisConfig.link[].properties` | Array | 否 | 需要返回的边属性列表。未传或为空数组时，返回该边的默认属性。 |
| `analysisConfig.link[].properties[].name` | String | 是 | ArcadeDB 中真实的边属性名，如 `attrMappings`。 |
| `analysisConfig.link[].properties[].label` | String | 否 | 边属性的前端展示名称，如“计算表达式”。 |
| `commonConfig` | Object | 是 | 通用查询配置。统一定义过滤、排序和分页。 |
| `commonConfig.filters` | Object | 否 | 过滤条件。单条件可直接传条件节点；多条件可传逻辑节点。 |
| `commonConfig.filters.logic` | String | 逻辑节点必填 | 逻辑连接符，可选 `AND`、`OR`。 |
| `commonConfig.filters.children` | Array | 逻辑节点必填 | 子条件列表；每个子节点可以继续是逻辑节点或条件节点。 |
| `commonConfig.filters.type` | String | 条件节点必填 | 查询对象类型。 |
| `commonConfig.filters.property` | String | 条件节点必填 | 被过滤对象上的真实属性名。 |
| `commonConfig.filters.operator` | Object | 条件节点必填 | 比较操作对象，包含 `code` 与 `type`。 |
| `commonConfig.filters.operator.code` | String | 是 | 操作符编码，如 `EQ`、`LIKE`、`IN`、`BETWEEN`。 |
| `commonConfig.filters.operator.type` | String | 是 | 过滤字段值类型，如 `STRING`、`NUMBER`、`DATE`、`BOOLEAN`。 |
| `commonConfig.filters.value` | Any | 视操作符而定 | 过滤值 |
| `commonConfig.sorts` | Array | 否 | 排序规则列表。多个排序项按数组顺序确定优先级。 |
| `commonConfig.sorts[].type` | String | 是 | 排序对象类型。 |
| `commonConfig.sorts[].property` | String | 是 | 排序对象上的真实属性名。 |
| `commonConfig.sorts[].order` | String | 是 | 排序方向，可选 `ASC`、`DESC`。 |
| `commonConfig.pagination` | Object | 是 | 分页配置。 |
| `commonConfig.pagination.pageNum` | Integer | 是 | 当前页码，从 `1` 开始。 |
| `commonConfig.pagination.pageSize` | Integer | 是 | 每页数据条数，必须大于 `0`；最大值由服务端限制。 |

过滤操作符说明：

| operator.code | 支持的 operator.type 枚举值 | value要求 | 说明 |
| --- | --- | --- | --- |
| `EQ` | `STRING`、`NUMBER`、`DATE`、`DATETIME`、`BOOLEAN` | 单值 | 等于 |
| `NE` | `STRING`、`NUMBER`、`DATE`、`DATETIME`、`BOOLEAN` | 单值 | 不等于 |
| `GT` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 大于 |
| `GTE` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 大于等于 |
| `LT` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 小于 |
| `LTE` | `NUMBER`、`DATE`、`DATETIME` | 单值 | 小于等于 |
| `LIKE` | `STRING` | 单值 | 模糊匹配 |
| `IN` | `STRING`、`NUMBER`、`DATE`、`DATETIME`、`BOOLEAN` | 非空数组 | 包含于指定集合 |
| `BETWEEN` | `NUMBER`、`DATE`、`DATETIME` | 长度为 2 的数组 | 闭区间查询 |

按 `operator.type`（字段值类型）反查可用 `operator.code`（便于前端按字段类型渲染操作符下拉）：

| operator.type | 支持的 operator.code | 说明 |
| --- | --- | --- |
| `STRING` | `EQ`、`NE`、`LIKE`、`IN` | 等于 / 不等于 / 包含（模糊） / 属于 |
| `NUMBER` | `EQ`、`NE`、`GT`、`GTE`、`LT`、`LTE`、`IN`、`BETWEEN` | 等于 / 不等于 / 大于 / 大于等于 / 小于 / 小于等于 / 属于 / 范围 |
| `DATE`（不含时分秒） | `EQ`、`NE`、`GT`、`GTE`、`LT`、`LTE`、`IN`、`BETWEEN` | 等于 / 不等于 / 大于 / 大于等于 / 小于 / 小于等于 / 属于 / 范围 |
| `BOOLEAN` | `EQ`、`NE`、`IN` | 等于 / 不等于 / 属于 |

**请求示例**

只查询指标，不查询任何关系边。返回指标的编码、名称和标签，并按照指标编码升序分页查询。

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Indicator",
        "label": "指标",
        "properties": [
          { "name": "code", "label": "指标编码" },
          { "name": "name", "label": "指标名称" },
          { "name": "label", "label": "指标标签" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "type": "Indicator",
      "property": "status",
      "operator": {
        "code": "EQ",
        "type": "STRING"
      },
      "value": "ACTIVE"
    },
    "sorts": [
      {
        "type": "Indicator",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 10
    }
  }
}
```

查询指标、指标使用的业务属性，同时演示点属性过滤混合嵌套查询

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Indicator",
        "label": "指标",
        "properties": [
          { "name": "code", "label": "指标编码" },
          { "name": "name", "label": "指标名称" }
        ]
      },
      {
        "type": "BusinessAttribute",
        "label": "业务属性",
        "properties": [
          { "name": "code", "label": "属性编码" },
          { "name": "name", "label": "属性名称" }
        ]
      }
    ],
    "link": [
      {
        "type": "IndicatorIsCalculatedFromATT",
        "label": "由业务属性计算",
        "sourceType": "Indicator",
        "targetType": "BusinessAttribute",
        "properties": []
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "type": "Indicator",
      "property": "code",
      "operator": {
        "code": "EQ",
        "type": "STRING"
      },
      "value": "M0001"
    },
    "pagination": {
      "pageNum": 1,
      "pageSize": 10
    }
  }
}
```

#### 返回参数（`data` 字段）

| 参数层级 | 类型 | 含义与说明 |
| --- | --- | --- |
| `code` | Integer | 业务状态码，成功为 `200` |
| `msg` | String/null | 响应信息，成功时为 `success` |
| `data` | Object/null | 核心业务数据，失败且无结果时可以为 `null` |
| `├─ resultType` | String | 结果类型标识，用于前端判断如何渲染 `result` 中的数据，可选值：`TABLE`、`GRAPH`、`TREE` |
| `├─ result` | Object/Array | 查询结果 |
| `│　├─ 当 resultType = TABLE 时` | Object | 扁平表格结果，包含列定义和数据行 |
| `│　│　├─ columns` | Array | 列定义（表头元数据）描述返回结果中包含哪些点属性和边属性。 |
| `│　│　│　├─ identifierCode` | String | 列唯一标识，对应 `rows` 中的动态 Key，如 `code`、`name`、`label` |
| `│　│　│　├─ label` | String | 字段展示名称 |
| `│　│　│　└─ type` | String | 字段类型 |
| `│　│　└─ rows` | Array | 当前页的数据行列表，每行代表一条完整匹配结果 |
| `│　│　　　├─ [动态Key]` | Any | 具体字段值。Key 必须与 `columns.identifierCode` 一致。 |
| `│　└─ 当 resultType = GRAPH 时` | Object | 图结构结果 |
| `│　　　├─ vertices` | Array | 本体点列表，同一个点在当前结果中只返回一次。 |
| `│　　　│　├─ id` | String | 点唯一标识，使用 ArcadeDB RID，如 `#10:1`。 |
| `│　　　│　├─ type` | String | 本体点类型，对应请求中的 `vertex.type`。 |
| `│　　　│　├─ properties` | Object | 点属性对象，只包含请求中 `vertex.properties` 声明的属性。 |
| `│　　　│　│　└─ [动态属性]` | Any | 点属性。Key 对应 `vertex.properties[].name`。 |
| `│　　　└─ links` | Array | 关系边列表，同一条边在当前结果中只返回一次。 |
| `│　　　　　├─ id` | String | 边唯一标识，使用 ArcadeDB RID，如 `#20:1`。 |
| `│　　　　　├─ relation` | String | 关系边类型，对应请求中的 `link.type`。 |
| `│　　　　　├─ source` | String | 起点 RID，引用 `vertices.id`。 |
| `│　　　　　├─ target` | String | 终点 RID，引用 `vertices.id`。 |
| `│　　　　　└─ properties` | Object | 边属性对象，只包含请求中 `link.properties` 声明的属性。未声明返回字段时返回空对象。 |
| `│　　　　　　　└─ [动态边属性]` | Any | 边属性。Key 对应 `link.properties[].name`。 |
| `└─ pagination` | Object | 分页信息。 |
| `├─ pageNum` | Integer | 当前页码。 |
| `└─ pageSize` | Integer | 每页目标结果数量。 |

**返回示例**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "TABLE",
    "result": {
      "columns": [
        {
          "identifierCode": "code",
          "label": "指标编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "指标标签",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "M0001",
          "label": "采购金额"
        },
        {
          "code": "M00011",
          "label": "到货周期"
        }
      ]
    },
    "pagination": {
      "pageNum": 1,
      "pageSize": 10
    }
  }
}
```
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "GRAPH",
    "result": {
      "vertices": [
        {
          "id": "#10:1",
          "type": "Indicator",
          "properties": {
            "code": "M0001",
            "name": "xxx",
            "label": "销售总金额"
          }
        }
      ],
      "edges": []
    },
    "pagination": {
      "pageNum": 1,
      "pageSize": 10
    }
  }
}
```

#### 更多场景

更多本体元数据分析场景请参阅：[《本体元数据查询API-WIP》](https://alidocs.dingtalk.com/i/nodes/a9E05BDRVQ0jarzPFDyNQ56RW63zgkYA)

### 获取智能建模任务上下文信息

#### 基本信息

**接口说明**： 按 `taskCode` 获取智能建模任务的执行上下文，包括解析要素、期望输出文件、数据源或文档来源信息。首次在 `PENDING`/`FAILED` 状态获取后任务进入 `RUNNING`；`RUNNING` 下重复获取幂等返回；`SUCCESS` 拒绝再次获取。历史 `SUCCEED`、`COMPLETED` 状态按已完成兼容读取，新回调统一使用 `SUCCESS`。

**请求方法**：`GET`

**相对路径**：`/intelligent/modeling/tasks/{taskCode}/execution-context`

**Content-Type**：`application/json`

#### 请求参数

| 参数 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| taskCode | String | 是 | 路径参数。智能建模任务编码，如 RM123456789。 |
| X-Ontology-Repository-Id | Long | 是 | 请求头。任务所属本体库 ID |

**请求示例**

GET /intelligent/modeling/tasks/RM123456789/execution-context

#### 返回参数（`data` 字段）

| 参数层级 | 类型 | 含义与说明 |
| --- | --- | --- |
| repositoryId | Long | 本体库 ID |
| taskCode | String | 任务编码 |
| taskName | String | 任务名称 |
| modelName | String | 模型名称 |
| taskType | String | 任务类型。可选值：DATA\_SOURCE\_MODELING（数据源建模）、DOCUMENT\_MODELING（文档建模） |
| prompt | String | 用户补充提示词 |
| parseElements | Array<String> | 解析要素列表，如 business\_object、logical\_entity |
| expectedFiles | Array<String> | 期望产出的 CSV 文件名及上传白名单，仅包含 `parseElements` 对应文件。建模任务不使用 `ok.csv`；`ok.csv` 仅用于消歧整合任务。 |
| outputPrefix | String | Agent 输出目录前缀，如 ontology/1/modeling-tasks/RM123456789/agent-output |
| database | Object/null | 数据库建模上下文；文档建模时为 null |
| database.databaseSourceId | Long | 数据库来源 ID |
| database.dbType | String | 数据库类型，如 POSTGRESQL |
| database.host | String | 主机 |
| database.port | Integer | 端口 |
| database.database | String | 数据库名 |
| database.username | String | 用户名 |
| database.password | String | 数据库密码；可为历史明文，也可为 `ConnectionConfigCrypto` 生成的 `Base64(12 字节 IV || AES-GCM 密文+16 字节 Tag)`。加密凭据必须配置 32 字节 AES-256 密钥 `ontology.crypto.secret`；缺 key、错误 key 或 Tag 校验失败均直接拒绝连接，不得把密文当明文密码传递。 |
| database.sourceSchema | String | 源 Schema |
| database.selectedTables | Array<String> | 选中的表 |
| document | Object/null | 文档建模上下文；数据源建模时为 null |
| document.fileSourceId | Long | 文件来源 ID |
| document.fileType | String | 文件类型，如 PDF |
| document.objectKey | String | 对象存储 objectKey |

解析要素与输出文件对应关系：

| parseElement | 输出文件 |
| --- | --- |
| business\_object | business\_objects.csv |
| logical\_entity | logical\_entities.csv |
| business\_attribute | business\_attributes.csv |
| entity\_relation | entity\_relations.csv |
| business\_object\_relation | business\_object\_relations.csv（兼容 business\_object\_relationships.csv、object\_relations.csv） |
| status | statuses.csv（兼容 status.csv、business\_object\_statuses.csv） |
| event | events.csv（兼容 event.csv、business\_events.csv） |
| rule | business\_rules.csv |
| term | business\_terms.csv（兼容 terms.csv） |
| metric | metrics.csv（兼容 indicator.csv） |
| activity | activities.csv |
| activity\_flow | activity\_flows.csv（兼容 activity\_flow.csv） |

`parseElements` 是唯一的识别范围，`expectedFiles` 只指定具体文件名和上传白名单，不能反向增加识别要素。每一种已选择结果均可独立生成和上传，不因其他类型 CSV 尚未生成而阻塞。任务内可复用的结构化分析写入 `mission-work/modeling_state.json`；该文件不上传，也不进入成功回调。

**返回示例**

```json
{
  "success": true,
  "code": 200,
  "msg": null,
  "data": {
    "repositoryId": 1,
    "taskCode": "RM123456789",
    "taskName": "采购库智能建模",
    "modelName": "采购域模型",
    "taskType": "DATA_SOURCE_MODELING",
    "prompt": "优先识别采购订单与供应商",
    "parseElements": [
      "business_object",
      "logical_entity",
      "business_attribute"
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
      "password": "crypted-password",
      "sourceSchema": "public",
      "selectedTables": ["purchase_order", "supplier"]
    },
    "document": null
  }
}

```

### 智能建模任务状态回调

#### 基本信息

**接口说明**： 回传建模任务执行状态。用户确认完成时发送 `SUCCESS`，并携带结果文件清单；`FAILED` 时应填写错误码与错误信息。结果上传本身不会自动发送成功回调，上传后任务继续保持 `RUNNING`。

**请求方法**：`POST`

**相对路径**：`/intelligent/modeling/tasks/{taskCode}/callback`

**Content-Type**：`application/json`

#### 请求参数

| 参数层级 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| taskCode | String | 是 | 路径参数。智能建模任务编码。 |
| X-Ontology-Repository-Id | Long | 是 | 请求头。任务所属本体库 ID。 |
| agentStatus | String | 是 | Agent 状态。新回调可选值：RUNNING、SUCCESS、FAILED。历史 SUCCEED、COMPLETED 仅用于兼容读取。 |
| occurredAt | String | 是 | 事件发生时间，ISO-8601 带时区 |
| errorCode | String | FAILED 时建议填 | 失败错误码，如 SOURCE\_READ\_FAILED |
| errorMessage | String | FAILED 时建议填 | 失败信息 |
| files | Array | SUCCESS 时必填 | 结果文件清单；RUNNING/FAILED 时可为空或 null |
| files\[\].parseElement | String | 是 | 解析要素，如 business\_object |
| files\[\].filename | String | 是 | 文件名，如 business\_objects.csv |
| files\[\].objectKey | String | 是 | 对象存储 objectKey |
| files\[\].previewUrl | String | 是 | FileServer 预览地址 |

**请求示例**

```json
{
  "agentStatus": "RUNNING",
  "occurredAt": "2026-07-20T10:30:00+08:00",
  "errorCode": null,
  "errorMessage": null,
  "files": null
}

```
```json
{
  "agentStatus": "SUCCESS",
  "occurredAt": "2026-07-20T10:35:00+08:00",
  "errorCode": null,
  "errorMessage": null,
  "files": [
    {
      "parseElement": "business_object",
      "filename": "business_objects.csv",
      "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/business_objects.csv",
      "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/business\_objects.csv"
    },
    {
      "parseElement": "logical_entity",
      "filename": "logical_entities.csv",
      "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/logical_entities.csv",
      "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/logical\_entities.csv"
    },
    {
      "parseElement": "business_attribute",
      "filename": "business_attributes.csv",
      "objectKey": "ontology/1/modeling-tasks/RM123456789/agent-output/business_attributes.csv",
      "previewUrl": "https://files.example.com/file/preview/static/ontology/1/modeling-tasks/RM123456789/agent-output/business\_attributes.csv"
    }
  ]
}

```

工作台上传全部 `expectedFiles` 后仍保持 `RUNNING`。用户检查结果并点击“完成”时，Agent 再次校验上传完整性、本地文件哈希及非空 `previewUrl`，校验通过后发送 `SUCCESS`。已完成任务点击“修改”时，Agent 删除当前任务已上传的旧结果并发送 `RUNNING`，随后允许重新生成和上传。对象存储前缀始终取本接口返回的可信 `outputPrefix`，不信任浏览器自行拼接的前缀；执行、结果上传和完成/修改状态切换互斥。新增或替换任务输入会使旧中间态及上传记录失效，必须重新执行并上传全部结果。

`parseElements` 与 `expectedFiles` 必须双向一致：不得返回未选择解析要素对应的文件，也不得为可输出的已选择要素漏配文件。Agent 在执行或上传前发现契约不一致时会直接拒绝本轮操作，且不会清理已完成任务的旧结果。已完成任务的普通提问、致谢和评价不触发重新执行；变更输入或重新生成前必须先点击“修改”。

#### 返回参数（`data` 字段）

无业务数据，成功时 `data` 为 null

**返回示例**

```json
{
  "success": true,
  "code": 200,
  "msg": null,
  "data": null
}

```

### 获取智能消歧整合任务上下文信息

#### 基本信息

**接口说明**： 按 `taskCode` 获取消歧整合任务的执行上下文，包括源模型、校验类型、整合策略、期望输出文件等。

**请求方法**：`GET`

**相对路径**：`/intelligent/integration/tasks/{taskCode}/execution-context`

**Content-Type**：`application/json`

#### 请求参数

| 参数 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| taskCode | String | 是 | 路径参数。消歧整合任务编码，如 MI123456789。 |
| X-Ontology-Repository-Id | Long | 是 | 请求头。任务所属本体库 ID。 |

**请求示例**

GET /intelligent/integration/tasks/RM123456789/execution-context

#### 返回参数（`data` 字段）

| 参数层级 | 类型 | 含义与说明 |
| --- | --- | --- |
| taskCode | String | 任务编码 |
| modelName | String | 模型名称 |
| sourceMode | String | 来源模式，如 MODELING\_TASKS |
| sourceModels | Object | 待整合源模型。结构随 sourceMode 变化 |
| sourceModels.mode | String | 来源模式，与 sourceMode 一致 |
| sourceModels.items | Array | 源模型条目列表 |
| sourceModels.items\[\].taskCode | String | 源建模任务编码（mode=MODELING\_TASKS 时） |
| checkTypes | Array<String> | 校验类型，如 CONSISTENCY |
| validationRules | Object | 校验规则 |
| integrationStrategy | Object | 整合策略 |
| integrationStrategy.semanticSimilarityThreshold | Number | 语义相似度阈值，如 0.85 |
| prompt | String | 用户补充提示词 |
| outputPrefix | String | Agent 输出目录前缀 |
| expectedFiles | Array<String> | 期望产出的文件名列表 |

**返回示例**

```json
{
  "success": true,
  "code": 200,
  "msg": null,
  "data": {
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
}

```

### 智能消歧整合任务状态回调

#### 基本信息

**接口说明**： 回传消歧整合任务执行状态。用户确认完成时发送 `SUCCESS`；`FAILED` 时应填写错误码与错误信息。整合回调不携带 `files`，Ontology 后端按 `outputPrefix`、`expectedFiles` 和完成标记 `ok.csv` 读取结果。

**请求方法**：`POST`

**相对路径**：`/intelligent/integration/tasks/{taskCode}/callback`

**Content-Type**：`application/json`

#### 请求参数

| 参数层级 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| taskCode | String | 是 | 路径参数。消歧整合任务编码。 |
| X-Ontology-Repository-Id | Long | 是 | 请求头。任务所属本体库 ID。 |
| agentStatus | String | 是 | Agent 状态。新回调可选值：RUNNING、SUCCESS、FAILED。历史 SUCCEED、COMPLETED 仅用于兼容读取。 |
| occurredAt | String | 是 | 事件发生时间，ISO-8601 带时区 |
| errorCode | String | FAILED 时建议填 | 失败错误码 |
| errorMessage | String | FAILED 时建议填 | 失败信息 |

**请求示例**

```json
{
  "agentStatus": "SUCCESS",
  "occurredAt": "2026-07-20T11:00:00+08:00",
  "errorCode": null,
  "errorMessage": null
}
```

整合任务必须先上传全部 `expectedFiles` 和额外完成标记 `ok.csv`，上传后仍保持 `RUNNING`；用户点击“完成”后才发送 `SUCCESS`。用户点击“修改”时，Agent 删除旧结果（至少包括 `ok.csv`）并发送 `RUNNING`。上传对象前缀只采用 execution-context 的可信 `outputPrefix`；执行、上传和状态切换互斥，输入发生变化后旧上传记录失效并要求全量重传。

#### 返回参数（`data` 字段）

无业务数据，成功时 `data` 为 null

**返回示例**

```json

{
  "success": true,
  "code": 200,
  "msg": null,
  "data": null
}
```

## 业务数据

### Doris数据查询-SQL脚本

**接口说明：**执行select 查询接口，返回查询结果集

**请求方法：** `POST`

**路径：** `/agent/doris/query`

**Content-Type：** `application/json`

**请求参数**

| 参数 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| `sql` | string | 是 | 待执行的 SQL 语句，仅允许单条 `SELECT` |

SQL 约束：

*   必须以 `SELECT` 开头（不区分大小写）

*   不允许多条语句（不能包含 `;` 分隔的多条 SQL）

*   末尾分号会自动去除


**Doris 命名约定**

| 概念 | 规则 | 示例 |
| --- | --- | --- |
| 库名（schema） | `{sourceName}_{sourceSchema}` | `ontology_demo_scm_po` |
| 表名（查询用） | `LogicalEntity.name` | `PoAllocationRelation` |
| 列名 | `BusinessAttribute.name` | `allocationRelationId` |

**请求示例**

```http
POST /agent/doris/query
Content-Type: application/json

{
  "sql": "SELECT allocationRelationId, unitCode, deleteFlag FROM `ontology_demo_scm_po`.`PoAllocationRelation` LIMIT 10"
}

```

**返回参数**（`data` 字段）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `rows` | array | 结果 |
| `rowCount` | int | 返回结果数 |

**响应示例**

```json
{
  "code": 200,
  "msg": null,
  "data": {
    "rows": [
      {
        "allocationRelationId": 1830513348099637200,
        "unitCode": "1000",
        "deleteFlag": "N"
      }
    ],
    "rowCount": 1
  }
}

```

### 指标维度计算

#### 基本信息

**接口说明：**指标多维维度分析接口，返回指标结果集

**请求方法：** `POST`

**相对路径：** `api/v1/analysis/data/query`

**Content-Type：** `application/json`

#### 请求参数

| 参数层级 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| `analysisConfig` | Object | 是 | 分析配置。定义当前查询需要展示的指标和维度。 |
| ├─ `indicators` | Array | 是 | 指标列表。定义需要聚合计算的度量字段。 |
| ├─ `identifierCode` | String | 是 | 指标唯一标识编码（如 `M0001`）。 |
| ├─ `alias` | String | 否 | 指标别名，用于前端展示（如 `销售总金额`）。 |
| ├─ `valueConfig` | Object | 否 | **值处理与格式化配置**。统一处理字段的数据预处理逻辑及前端展示样式。 |
| └─ `numericScale` | Integer | 否 | 数值精度，保留的小数位数（如 `2`）。 |
| └─ `dimensions` | Array | 是 | 维度列表。定义数据分组的字段（明细模式下通常为空）。 |
| ├─ `identifierCode` | String | 是 | 维度唯一标识编码（如 `order_date`）。 |
| └─ `alias` | String | 否 | 维度别名，用于前端展示（如 `下单时间`）。 |
| `commonConfig` | Object | 是 | 通用查询配置。包含过滤、排序、分页等全局设置。 |
| ├─ `filters` | Array | 否 | 过滤条件列表。支持树形嵌套逻辑组合。 |
| ├─ `identifierCode` | String | 条件必填 | 字段标识。仅当该节点为具体条件时必填，逻辑节点无需此字段。 |
| ├─ `operator` | Object | 条件必填 | 比较操作对象，包含 code 与 type; <br>code 是操作符编码如 EQ、LIKE、IN、BETWEEN; <br>type 是过滤字段值类型，如 STRING、NUMBER、DATE、BOOLEAN |
| ├─ `valueType` | String | 否 | 值类型标识。`ABSOLUTE`（绝对值，默认）、`MODIFIER`（修饰词/动态相对值）。 |
| ├─ `value` | Any | 条件必填 | 过滤值。根据 `valueType` 支持多种类型：<br>• 绝对值：字符串或数组<br>• 简单修饰词：字符串（如 `TODAY`）<br>• 动态修饰词：对象（如 `{modifierCode: "RECENT_N_DAYS", params: {days: 7}}`） |
| ├─ `logic` | String | 条件必填 | 逻辑连接符。仅当该节点为逻辑组合节点时必填，可选 `AND`、`OR`。 |
| └─ `children` | Array | 条件必填 | 子过滤条件列表。仅当该节点为逻辑组合节点时必填，支持无限递归嵌套。 |
| ├─ `sorts` | Array | 否 | 排序规则列表。 |
| ├─ `identifierCode` | String | 是 | 排序字段的唯一标识编码（可以是指标或维度编码）。 |
| └─ `order` | String | 是 | 排序方向。可选值：`ASC`（升序）、`DESC`（降序）。 |
| └─ `pagination` | Object | 是 | 分页配置。 |
| ├─ `pageNum` | Integer | 是 | 当前页码，从 1 开始。 |
| └─ `pageSize` | Integer | 是 | 每页数据条数。 |

**示例**

```json
{
    "analysisConfig": {
        "indicators": [
            {
                "identifierCode": "M0001",
                "alias": "销售总金额",
                "valueConfig": {
                    "numericScale": 2
                }
            }
        ],
        "dimensions": [
            {
                "identifierCode": "order_date",
                "alias": "下单时间"
            },
            {
                "identifierCode": "region",
                "alias": "地区"
            },
            {
                "identifierCode": "category",
                "alias": "类别"
            }
        ]
    },
    "commonConfig": {
        "filters": {
            "logic": "AND",
            "children": [
                {
                    "identifierCode": "order_date",
                    "operator": {
                       "code": "BETWEEN",
                       "type": "DATA"
                     },
                    "valueType": "ABSOLUTE",
                    "value": [
                        "2026-01-01",
                        "2026-06-17"
                    ]
                },
                {
                    "logic": "AND",
                    "children": [
                        {
                            "logic": "OR",
                            "children": [
                                {
                                    "identifierCode": "category",
                                     "operator": {
                                        "code": "EQ",
                                        "type": "STRING"
                                     },
                                    "valueType": "ABSOLUTE",
                                    "value": "1"
                                },
                                {
                                    "identifierCode": "region",
                                     "operator": {
                                        "code": "EQ",
                                        "type": "STRING"
                                     },
                                    "valueType": "ABSOLUTE",
                                    "value": "ShangHai"
                                }
                            ]
                        },
                        {
                            "identifierCode": "M0001",
                            "operator": {
                               "code": "GT",
                               "type": "NUMBER"
                            },
                            "valueType": "ABSOLUTE",
                            "value": 1000
                        }
                    ]
                }
            ]
        },
        "sorts": [
            {
                "identifierCode": "M0001",
                "order": "DESC"
            }
        ],
        "pagination": {
            "pageNum": 1,
            "pageSize": 20
        }
    }
}
```

#### 返回参数（`data` 字段）

| 参数层级 | 类型 | 含义与说明 |
| --- | --- | --- |
| `data` | Object | 核心业务数据。包含查询结果的元数据、数据行及分页信息。 |
| ├─ `resultType` | String | 结果类型标识。用于前端判断如何渲染 `result` 中的数据。<br>值：`TABLE`（扁平表格）。 |
| ├─ `result` | Object | 结果数据载体（多态）。根据 `resultType` 的不同，包含不同的数据结构。 |
| ├─ `columns` | Array | 指标或维度（表头元数据）。描述返回结果中包含哪些字段及其类型。 |
| ├─ `identifierCode` | String | 指标或维度实例数据唯一标识（对应 `rows` 中的 key，如 `region`）。 |
| ├─ `label` | String | 指标或维度展示名称（用于前端表头渲染，如 `区域`）。 |
| └─ `type` | String | 指标或维度类型。可选值：`DIMENSION`（维度）、`METRIC`（指标/度量）。 |
| ├─ `rows` | Array<Map<`Key`,`Value`\>> | 数据行列表。包含具体的查询结果数据。 |
| ├─ `[Key]` | Any | 对应 `columns` 中的 `identifierCode`。 |
| ├─ `[value]` | Any | 对应的`identifierCode`关联的Value Object |
| ├─ value | Any | 具体值。 |
| └─ `render` | Object | 单元格渲染配置（选填）。用于后端下发动态样式或交互规则。 |
| ├─ unit | String | 金额value的单位 |
| └─ `frontColor` | String | 字体颜色配置（如 `#FF0000`）。 |
| └─ `pagination` | Object | 分页信息。 |
| ├─ `total` | Integer | 满足当前查询条件的总记录数。 |
| ├─ `pageNum` | Integer | 当前页码。 |
| └─ `pageSize` | Integer | 每页数据条数。 |

**示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "resultType": "TABLE",
        "result": {
            "columns": [
                {
                    "identifierCode": "region",
                    "label": "区域",
                    "type": "DIMENSION"
                },
                {
                    "identifierCode": "category",
                    "label": "类别",
                    "type": "DIMENSION"
                },
                {
                    "identifierCode": "total_sales",
                    "label": "总销售额",
                    "type": "METRIC"
                }
            ],
            "rows": [
                "region": {
                        "value": "华东"
                    },
                "category": {
                    "value": "数码"
                },
                "total_sales": {
                    "value": 150,
                    "render": {
                        "unit": "万元",
                        "frontColor": "#FF0000"
                    }
                }
            ]
        },
        "pagination": {
            "total": 2,
            "pageNum": 1,
            "pageSize": 20
        }
    }
}
```

#### 更多场景

更多指标计算场景请参阅：[《指标维度计算API-WIP》](https://alidocs.dingtalk.com/i/nodes/R1zknDm0WRbNmEZ0I0v92j3zWBQEx5rG)

### 本体实例计算

#### 基本信息

**接口说明：**指标多维维度分析接口，返回指标结果集

**请求方法：** `POST`

**相对路径：** `api/v1/analysis/data/query`

**Content-Type：** `application/json`

#### 请求参数

| 参数层级 | 类型 | 必填 | 含义与说明 |
| --- | --- | --- | --- |
| `analysisConfig` | Object | 是 | 分析配置。定义明细查询需要返回的字段（业务对象）。 |
| ├─ `vertex` | Array | 是 | 业务对象字段列表。定义明细数据中需要展示的具体列。 |
| ├─ `identifierCode` | String | 是 | 本体元数据唯一标识；如：逻辑实体编码。（如 `LE000006`）。 |
| ├─ properties | Array | 否 |  |
| ├─ `alias` | String | 否 | 字段别名，用于前端表头展示（如 `采购订单类型`）。 |
| ├─ `identifierCode` | String | 是 | 字段/属性的唯一标识编码（如 `AT0000212`）。 |
| ├─ `valueConfig` | Object | 否 | 值处理与格式化配置。统一处理字段的数据预处理逻辑及前端展示样式。 |
| ├─ `function` | String | 否 | 预处理/聚合函数。定义对原始数据的处理逻辑，如 `distinct`（去重）、`sum`（求和）等。未传则返回原始值。 |
| └─ `numericScale` | Integer | 否 | 数值精度。定义格式化后保留的小数位数（如 `2`）。 |
| ├─ `link` | Array | 否 | 默认查ER关系，暂时不支持其他关系 |
| `commonConfig` | Object | 是 | 通用查询配置。包含过滤、排序、分页等全局设置。 |
| ├─ `filters` | Object | 否 | 过滤条件（根节点）。注意：此处为树形结构的根节点对象，非数组。 |
| ├─ `logic` | String | 是 | 根节点的逻辑连接符。可选值：`AND`、`OR`。 |
| └─ `children` | Array | 是 | 子过滤条件列表。支持递归嵌套。 |
| ├─ `identifierCode` | String | 条件必填 | 过滤字段的唯一标识编码。 |
| ├─ `operator` | Object | 条件必填 | 比较操作对象 |
| ├─ `valueType` | String | 否 | 值类型标识。`ABSOLUTE`（绝对值，默认）、`MODIFIER`（修饰词）。 |
| └─ `value` | Any | 条件必填 | 过滤值。根据 `valueType` 和操作符传入对应的值。 |
| ├─ `sorts` | Array | 否 | 排序规则列表。 |
| ├─ `identifierCode` | String | 是 | 排序字段的唯一标识编码。 |
| └─ `order` | String | 是 | 排序方向。可选值：`ASC`（升序）、`DESC`（降序）。 |
| └─ `pagination` | Object | 是 | 分页配置。 |
| ├─ `pageNum` | Integer | 是 | 当前页码，从 1 开始。 |
| └─ `pageSize` | Integer | 是 | 每页数据条数。 |

**示例**

```json
{
    "analysisConfig": {
        "vertex": [
            {
                "identifierCode": "LE000006",
                "properties": [
                    {
                        "alias": "采购订单类型",
                        "identifierCode": "AT0000212"
                    }
                ]
            },
            {
                "identifierCode": "LE000007",
                "properties": [
                    {
                        "alias": "数量",
                        "identifierCode": "AT0000271",
                        "valueConfig": {
                            "function": "sum"
                        }
                    }
                ]
            }
        ],
        "link": []
    },
    "commonConfig": {
        "filters": {
            "logic": "AND",
            "children": [
                {
                    "identifierCode": "AT0000212",
                    "operator": {
                      "code": "EQ",
                      "type": "STRING"
                    },
                    "valueType": "ABSOLUTE",
                    "value": "STANDARD_PURCHASE_ORDER"
                },
                {
                    "identifierCode": "AT0000271",
                    "operator": {
                      "code": "GT",
                      "type": "NUMBER"
                    },
                    "valueType": "ABSOLUTE",
                    "value": 50
                }
            ]
        },
        "sorts": [
            {
                "identifierCode": "AT0000212",
                "order": "DESC"
            }
        ],
        "pagination": {
            "pageNum": 1,
            "pageSize": 20
        }
    }
}
```

#### 返回参数（`**data**` 字段）

| 参数层级 | 类型 | 含义与说明 |
| --- | --- | --- |
| `data` | Object | 核心业务数据。包含查询结果的元数据及动态的结果载体。 |
| ├─ `resultType` | String | 结果类型标识。用于前端判断如何渲染 `result` 中的数据。<br>可选值：`TABLE`（扁平表格）、`TREE`（树形结构）。 |
| ├─ `result` | Object | 结果数据载体（多态）。根据 `resultType` 的不同，包含不同的数据结构。 |
| ├─ `columns` | Array | 本体元数据列表。同时兼容表格表头和树形节点配置。 |
| ├─ `identifierCode` | String | 本体元数据(如：属性/维度)唯一标识（对应 `rows` 中的 key ）。 |
| ├─ `label` | String | 本体元数据的展示名称。 |
| └─ `type` | String | 本体元数据类型。如 `ATTRIBUTE`（普通属性）、`DIMENSION`（维度）。 |
| ├─ 当 `**resultType**` **=** `**TABLE**` 时： |  |  |
| ├─ `rows` | Array<Map<`Key`,`Value`\>> | 本体元数据的实例数据行列表 |
| ├─ `[Key]` | Any | 对应 `columns` 中的 `identifierCode`。 |
| ├─ `[Value]` | Any | 对应的`identifierCode`关联的Value Object |
| ├─ value | Any | 具体值。如：性别维度值男、女 |
| ├─ `render` | Object | 单元格渲染配置（选填）。用于后端下发动态样式或交互规则。 |
| └─ `frontColor` | String | 字体颜色配置（如 `#FF0000`）。 |
| ├─ **当** `**resultType**` **=** `**TREE**` **时：** |  |  |
| ├─ `rows` | Array<Map<`Key`,`Value`\>> | 本体元数据的实例数据树形节点列表。`Value`支持无限层级嵌套。 |
| ├─ `[Key]` | Any | 对应 `columns` 中的 `identifierCode`。 |
| ├─ `[Value]` | Any | 对应的`identifierCode`关联的Value Object |
| ├─ `identifierNumber` | Any | 本体元数据的实例数据节点编号或唯一标识。 |
| ├─ `value` | Any | 本体元数据的实例数据节点的展示文本。 |
| ├─ `render` | Object | 单元格渲染配置（选填）。用于后端下发动态样式或交互规则。 |
| └─ `frontColor` | String | 字体颜色配置（如 `#FF0000`）。 |
| └─ `children` | Array<`[Value]`\> | 子节点列表。结构同 `[Value]`，支持递归嵌套。 |
| └─ `pagination` | Object | 分页信息（仅 `TABLE` 模式下生效）。 |
| ├─ `total` | Integer | 满足当前查询条件的总记录数。 |
| ├─ `pageNum` | Integer | 当前页码。 |
| └─ `pageSize` | Integer | 每页数据条数。 |

**示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "resultType": "TABLE",
        "result": {
            "columns": [
                {
                    "identifierCode": "AT0000212",
                    "label": "采购订单类型",
                    "type": "ATTRIBUTE"
                },
                {
                    "identifierCode": "AT0000271",
                    "label": "数量",
                    "type": "ATTRIBUTE"
                }
            ],
            "rows": [
                {
                    "AT0000212": "STANDARD_PURCHASE_ORDER",
                    "AT0000271": {
                       "value": 150
                    }
                },
                {
                    "AT0000212": "STANDARD_PURCHASE_ORDER",
                    "AT0000271": {
                        "value": 85,
                        "render": {
                            "frontColor": "#FF0000"
                        }
                    }
                },
                {
                    "AT0000212": "STANDARD_PURCHASE_ORDER",
                    "AT0000271": {
                       "value": 210
                    }
                }
            ]
        },
        "pagination": {
            "total": 3,
            "pageNum": 1,
            "pageSize": 20
        }
    }
}
```
```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "resultType": "Table",
        "result": {
            "columns": [
                {
                    "identifierCode": "D00000982",
                    "label": "性别",
                    "type": "DIMENSION"
                }
            ],
            "rows": [
                {
                    "D00000982": [
                      {
                        "identifierNumber": "1",
                        "value": "男"
                      },
                       {
                        "identifierNumber": "1",
                        "value": "女"
                      }
                    ]
                }
            ]
        },
        "pagination": null
    }
}
```
```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "resultType": "TREE",
        "result": {
            "columns": [
                {
                    "identifierCode": "D00000981",
                    "label": "组织架构",
                    "type": "DIMENSION"
                }
            ],
            "rows": [
                {
                    "D00000981": {
                      "identifierNumber": "1001",
                      "value": "华东大区",
                      "children": [
                          {
                              "identifierNumber": "1001-01",
                              "value": "上海分公司",
                              "children": []
                          }
                      ]
                    }
                }
            ]
        },
        "pagination": null
    }
}
```

#### 更多场景

更多本体实例计算场景请参阅：[《本体实例计算API-WIP》](https://alidocs.dingtalk.com/i/nodes/gvNG4YZ7JnYN9R1yuNqyQgQOV2LD0oRE?utm_scene=team_space)
