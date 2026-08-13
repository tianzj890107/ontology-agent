# 本体元数据查询API-WIP

# 获取指标树

### 按指标中文名筛选（对齐旧 `indicatorZhName`）

请求（mock）

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Indicator",
        "label": "指标",
        "properties": [
          { "name": "code", "label": "指标编码" },
          { "name": "label", "label": "指标名称" },
          { "name": "indicatorType", "label": "指标类型" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "type": "Indicator",
      "property": "label",
      "operator": {
        "code": "LIKE",
        "type": "STRING"
      },
      "value": "%采购金额%"
    },
    "sorts": [
      { "type": "Indicator", "property": "code", "order": "ASC" }
    ],
    "pagination": { "pageNum": 1, "pageSize": 10 }
  }
}
```

需要同时匹配多个属性时，可将 `filters` 改为 `AND`：

```json
"filters": {
  "logic": "AND",
  "children": [
    {
      "type": "Indicator",
      "property": "label",
      "operator": {
        "code": "LIKE",
        "type": "STRING"
      },
      "value": "%采购金额%"
    },
    {
      "type": "Indicator",
      "property": "indicatorType",
      "operator": {
        "code": "EQ",
        "type": "STRING"
      },
      "value": "原子指标"
    }
  ]
}
```

响应（mock）

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
          "label": "指标名称",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "indicatorType",
          "label": "指标类型",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "M0001",
          "label": "采购金额",
          "indicatorType": "原子指标"
        },
        {
          "code": "M0004",
          "label": "同比采购金额增长率",
          "indicatorType": "复合指标"
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
    "resultType": "TREE",
    "result": [
      {
        "type": "LogicalEntity",
        "code": "LE_PO_HEADER",
        "label": "采购订单头",
        "IndicatorIsCalculatedFromLE": [
          {
            "type": "Indicator",
            "code": "M0001",
            "label": "采购金额",
            "indicatorType": "原子指标"
          },
          {
            "type": "Indicator",
            "code": "M0002",
            "label": "采购订单数",
            "indicatorType": "原子指标"
          },
          {
            "type": "Indicator",
            "code": "M0004",
            "label": "同比采购金额增长率",
            "indicatorType": "复合指标"
          }
        ]
      },
      {
        "type": "LogicalEntity",
        "code": "LE_PO_LINE",
        "label": "采购订单行",
        "IndicatorIsCalculatedFromLE": [
          {
            "type": "Indicator",
            "code": "M0010",
            "label": "采购数量",
            "indicatorType": "原子指标"
          },
          {
            "type": "Indicator",
            "code": "M0011",
            "label": "到货周期",
            "indicatorType": "原子指标"
          }
        ]
      },
      {
        "type": "LogicalEntity",
        "code": "LE_GRN",
        "label": "收货单",
        "IndicatorIsCalculatedFromLE": [
          {
            "type": "Indicator",
            "code": "M0020",
            "label": "收货金额",
            "indicatorType": "原子指标"
          }
        ]
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 10
    }
  }
}

```

# 获取维度树

### 按维度中文名筛选（对齐旧 `dimensionZhName`）

请求（mock）

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Dimension",
        "label": "维度",
        "properties": [
          { "name": "code", "label": "维度编码" },
          { "name": "label", "label": "维度名称" },
          { "name": "type", "label": "维度类型" },
          { "name": "value", "label": "维度值类型及结构" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "type": "Dimension",
      "property": "label",
      "operator": {
        "code": "LIKE",
        "type": "STRING"
      },
      "value": "%供应商%"
    },
    "sorts": [
      { "type": "Dimension", "property": "code", "order": "ASC" }
    ],
    "pagination": { "pageNum": 1, "pageSize": 10 }
  }
}
```

响应（mock）

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
          "label": "维度编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "维度名称",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "type",
          "label": "维度类型",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "value",
          "label": "维度值类型及结构",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "D003",
          "label": "行政区划",
          "type": "时间维度",
          "value":{
             "type": "DATA",
             "struct": "tree"
          }
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
    "resultType": "TREE",
    "result": [
      {
        "type": "DimensionType",
        "code": "时间维度",
        "label": "时间维度",
        "Dimension": [
          {
            "code": "D001",
            "label": "年度",
            "type": "时间维度",
            "value": {
              "type": "时间类型",
              "struct": "TABLE"
            }
          }
        ]
      },
      {
        "type": "DimensionType",
        "code": "普通维度",
        "label": "普通维度",
        "Dimension": [
          {
            "code": "D002",
            "label": "采购订单类型",
            "type": "普通维度",
            "value": {
              "type": "字符类型",
              "struct": "TABLE"
            }
          },
          {
            "code": "D004",
            "label": "产品价值分类",
            "type": "普通维度",
            "value": {
              "type": "字符类型",
              "struct": "TABLE"
            }
          }
        ]
      },
      {
        "type": "DimensionType",
        "code": "层级维度",
        "label": "层级维度",
        "Dimension": [
          {
            "code": "D003",
            "label": "行政区划",
            "type": "层级维度",
            "value": {
              "type": "字符类型",
              "struct": "TREE"
            }
          }
        ]
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 10
    }
  }
}

```

# 获取指标关联的维度列表

**请求（mock）**

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Dimension",
        "label": "维度",
        "properties": [
          { "name": "code", "label": "维度编码" },
          { "name": "label", "label": "维度名称" },
          { "name": "type", "label": "维度类型" },
          { "name": "value", "label": "维度值类型及结构" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "logic": "AND",
      "children": [
        {
          "type": "Indicator",
          "property": "code",
          "operator": {
            "code": "EQ",
            "type": "STRING"
          },
          "value": "M0001"
        },
        {
          "type": "IndicatorIsDrilledByDimension",
          "sourceType": "Indicator",
          "targetType": "Dimension"
        }
      ]
    },
    "sorts": [
      {
        "type": "Dimension",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

多指标关联维度：IN（并集）示例：

```markdown
  "filters": {
      "logic": "AND",
      "children": [
        {
          "type": "Indicator",
          "property": "code",
          "operator": { "code": "IN", "type": "STRING" },
          "value": ["M0001", "M0004"]
        },
        {
          "type": "IndicatorIsDrilledByDimension",
          "sourceType": "Indicator",
          "targetType": "Dimension"
        }
      ]
    }
```

多指标关联维度：INTERSECT（交集）示例：

```markdown
 "filters": {
      "logic": "AND",
      "children": [
        {
          "type": "Indicator",
          "property": "code",
          "operator": { "code": "INTERSECT", "type": "STRING" },
          "value": ["M0001", "M0004"]
        },
        {
          "type": "IndicatorIsDrilledByDimension",
          "sourceType": "Indicator",
          "targetType": "Dimension"
        }
      ]
    }
```

**响应（mock）**

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
          "label": "维度编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "维度名称",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "type",
          "label": "维度类型",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "value",
          "label": "维度值类型及结构",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "D001",
          "label": "采购订单创建时间维度",
          "type": "time",
          "value": {
            "type": "DATE",
            "struct": "tree"
          }
        },
        {
          "code": "D002",
          "label": "供应商维度",
          "type": "reference",
          "value": {
            "type": "STRING",
            "struct": "TABLE"
          }
        },
        {
          "code": "D003",
          "label": "物料维度",
          "type": "common",
          "value": {
            "type": "STRING",
            "struct": "TABLE"
          }
        },
        {
          "code": "D005",
          "label": "品类维度",
          "type": "hierarchy",
          "value": {
            "type": "STRING",
            "struct": "tree"
          }
        }
      ]
    },
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

**请求（mock）**

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Indicator",
        "label": "指标",
        "properties": [
          { "name": "code", "label": "指标编码" },
          { "name": "label", "label": "指标名称" },
          { "name": "indicatorType", "label": "指标类型" }
        ]
      },
      {
        "type": "Dimension",
        "label": "维度",
        "properties": [
          { "name": "code", "label": "维度编码" },
          { "name": "label", "label": "维度名称" },
          { "name": "type", "label": "维度类型" },
          { "name": "value", "label": "维度值类型及结构" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "logic": "AND",
      "children": [
        {
          "type": "Indicator",
          "property": "code",
          "operator": {
            "code": "EQ",
            "type": "STRING"
          },
          "value": "M0001"
        },
        {
          "type": "IndicatorIsDrilledByDimension",
          "sourceType": "Indicator",
          "targetType": "Dimension"
        }
      ]
    },
    "sorts": [
      {
        "type": "Dimension",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

**响应（mock）**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "TREE",
    "result": {
      "columns": [
        {
          "identifierCode": "code",
          "label": "编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "名称",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "M0001",
          "label": "采购金额",
          "indicatorType": "原子指标",
          "IndicatorIsDrilledByDimension": [
            {
              "code": "D001",
              "label": "采购订单创建时间维度",
              "type": "time",
              "value": {
                "type": "DATE",
                "struct": "tree"
              }
            },
            {
              "code": "D002",
              "label": "供应商维度",
              "type": "reference",
              "value": {
                "type": "STRING",
                "struct": "TABLE"
              }
            },
            {
              "code": "D003",
              "label": "物料维度",
              "type": "common",
              "value": {
                "type": "STRING",
                "struct": "TABLE"
              }
            },
            {
              "code": "D005",
              "label": "品类维度",
              "type": "hierarchy",
              "value": {
                "type": "STRING",
                "struct": "tree"
              }
            }
          ]
        }
      ]
    },
    "pagination": null
  }
}

```

**请求（mock）**

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Indicator",
        "label": "指标",
        "properties": [
          { "name": "code", "label": "指标编码" },
          { "name": "label", "label": "指标名称" },
          { "name": "indicatorType", "label": "指标类型" }
        ]
      },
      {
        "type": "Dimension",
        "label": "维度",
        "properties": [
          { "name": "code", "label": "维度编码" },
          { "name": "label", "label": "维度名称" },
          { "name": "type", "label": "维度类型" },
          { "name": "value", "label": "维度值类型及结构" }
        ]
      }
    ],
    "link": [
      {
        "type": "IndicatorIsDrilledByDimension",
        "label": "被维度钻取",
        "sourceType": "Indicator",
        "targetType": "Dimension",

        "properties": [ ]

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
    "sorts": [
      {
        "type": "Dimension",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

**响应（mock）**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "GRAPH",
    "result": {
      "vertices": [
        {
          "id": "#39:0",
          "type": "Indicator",
          "properties": {
            "code": "M0001",
            "label": "采购金额",
            "indicatorType": "原子指标"
          }
        },
        {
          "id": "#30:0",
          "type": "Dimension",
          "properties": {
            "code": "D001",
            "label": "采购订单创建时间维度",
            "type": "time",
            "value": {
              "type": "DATE",
              "struct": "tree"
            }
          }
        },
        {
          "id": "#30:1",
          "type": "Dimension",
          "properties": {
            "code": "D002",
            "label": "供应商维度",
            "type": "reference",
            "value": {
              "type": "STRING",
              "struct": "TABLE"
            }
          }
        },
        {
          "id": "#30:2",
          "type": "Dimension",
          "properties": {
            "code": "D003",
            "label": "物料维度",
            "type": "common",
            "value": {
              "type": "STRING",
              "struct": "TABLE"
            }
          }
        },
        {
          "id": "#30:4",
          "type": "Dimension",
          "properties": {
            "code": "D005",
            "label": "品类维度",
            "type": "hierarchy",
            "value": {
              "type": "STRING",
              "struct": "tree"
            }
          }
        }
      ],
      "links": [
        {
          "id": "#38:4",
          "relation": "IndicatorIsDrilledByDimension",
          "source": "#39:0",
          "target": "#30:0",
          "properties": {}
        },
        {
          "id": "#38:5",
          "relation": "IndicatorIsDrilledByDimension",
          "source": "#39:0",
          "target": "#30:1",
          "properties": {}
        },
        {
          "id": "#38:6",
          "relation": "IndicatorIsDrilledByDimension",
          "source": "#39:0",
          "target": "#30:2",
          "properties": {}
        },
        {
          "id": "#38:3",
          "relation": "IndicatorIsDrilledByDimension",
          "source": "#39:0",
          "target": "#30:4",
          "properties": {}
        }
      ]
    },
    "pagination": null
  }
}

```

# 获取修饰词

请求（mock）

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "Modifier",
        "label": "修饰词",
        "properties": [
          { "name": "code", "label": "修饰词编码" },
          { "name": "label", "label": "修饰词名称" }        ]
      }
    ]
  },
  "commonConfig": {
    "sorts": [
      { "type": "Modifier", "property": "code", "order": "ASC" }
    ],
    "pagination": { "pageNum": 1, "pageSize": 10 }
  }
}

```

响应（mock）

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
          "label": "修饰词编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "修饰词名称",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "this_quarter",
          "label": "本季"
        },
        {
          "code": "this_year",
          "label": "本年"
        },
        {
          "code": "today",
          "label": "本日"
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

# 获取逻辑实体关联的业务属性

同一业务场景下，上游按需要返回的点 / 边调整 `analysisConfig`，服务端据此推断 `TABLE` / `TREE` / `GRAPH`

**按逻辑实体编码过滤（TABLE：只返回业务属性）**

`analysisConfig` 仅声明 BusinessAttribute。LogicalEntity 与关联边 `LEContainATT` 不进入结果，由上游在 `filters.children` 中与属性条件一并列举。单返回点、无返回边 → `resultType=TABLE`。

请求(mock)

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "BusinessAttribute",
        "label": "业务属性",
        "properties": [
          { "name": "code", "label": "属性编码" },
          { "name": "name", "label": "属性名称" },
          { "name": "label", "label": "属性标签" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "logic": "AND",
      "children": [
        {
          "type": "LogicalEntity",
          "property": "code",
          "operator": {
            "code": "EQ",
            "type": "STRING"
          },
          "value": "LE000001"
        },
        {
          "type": "LEContainATT",
          "sourceType": "LogicalEntity",
          "targetType": "BusinessAttribute"
        }
      ]
    },
    "sorts": [
      {
        "type": "BusinessAttribute",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

响应（mock）

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
          "label": "属性编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "name",
          "label": "属性名称",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "属性标签",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "ATT_ORDER_ID",
          "name": "orderId",
          "label": "订单号"
        },
        {
          "code": "ATT_ORDER_AMT",
          "name": "orderAmount",
          "label": "订单金额"
        },
        {
          "code": "ATT_ORDER_STATUS",
          "name": "orderStatus",
          "label": "订单状态"
        }
      ]
    },
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

**返回逻辑实体及其业务属性树（TREE）**

`analysisConfig`：只声明要返回的点（LogicalEntity、BusinessAttribute），不要声明 `link`

`filters`：属性条件与关联边一并列举（如 `LogicalEntity.code` + `LEContainATT`）

请求（mock）

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "LogicalEntity",
        "label": "逻辑实体",
        "properties": [
          { "name": "code", "label": "逻辑实体编码" },
          { "name": "name", "label": "逻辑实体名称" },
          { "name": "label", "label": "逻辑实体标签" }
        ]
      },
      {
        "type": "BusinessAttribute",
        "label": "业务属性",
        "properties": [
          { "name": "code", "label": "属性编码" },
          { "name": "name", "label": "属性名称" },
          { "name": "label", "label": "属性标签" }
        ]
      }
    ]
  },
  "commonConfig": {
    "filters": {
      "logic": "AND",
      "children": [
        {
          "type": "LogicalEntity",
          "property": "code",
          "operator": {
            "code": "EQ",
            "type": "STRING"
          },
          "value": "LE000001"
        },
        {
          "type": "LEContainATT",
          "sourceType": "LogicalEntity",
          "targetType": "BusinessAttribute"
        }
      ]
    },
    "sorts": [
      {
        "type": "BusinessAttribute",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

响应（mock）

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "TREE",
    "result": {
      "columns": [
        {
          "identifierCode": "code",
          "label": "编码",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "name",
          "label": "名称",
          "type": "PROPERTY"
        },
        {
          "identifierCode": "label",
          "label": "标签",
          "type": "PROPERTY"
        }
      ],
      "rows": [
        {
          "code": "LE000001",
          "name": "SalesOrder",
          "label": "销售订单",
          "LEContainATT": [
            {
              "code": "ATT_ORDER_ID",
              "name": "orderId",
              "label": "订单号"
            },
            {
              "code": "ATT_ORDER_AMT",
              "name": "orderAmount",
              "label": "订单金额"
            },
            {
              "code": "ATT_ORDER_STATUS",
              "name": "orderStatus",
              "label": "订单状态"
            }
          ]
        }
      ]
    },
    "pagination": null
  }
}

```

**返回逻辑实体与业务属性图（GRAPH）**

需要同时返回逻辑实体、业务属性及关系边时，在 `analysisConfig` 中声明这两个返回点与返回边 `LEContainATT`。有 `analysisConfig.link` 且连通 → `resultType=GRAPH`

**请求（mock）**

```json
{
  "analysisConfig": {
    "vertex": [
      {
        "type": "LogicalEntity",
        "label": "逻辑实体",
        "properties": [
          { "name": "code", "label": "逻辑实体编码" },
          { "name": "name", "label": "逻辑实体名称" },
          { "name": "label", "label": "逻辑实体标签" }
        ]
      },
      {
        "type": "BusinessAttribute",
        "label": "业务属性",
        "properties": [
          { "name": "code", "label": "属性编码" },
          { "name": "name", "label": "属性名称" },
          { "name": "label", "label": "属性标签" }
        ]
      }
    ],
    "link": [
      {
        "type": "LEContainATT",
        "label": "实体包含属性",
        "sourceType": "LogicalEntity",
        "targetType": "BusinessAttribute",

        "properties": [ ]

      }
    ]
  },
  "commonConfig": {
    "filters": {
      "type": "LogicalEntity",
      "property": "code",
      "operator": {
        "code": "EQ",
        "type": "STRING"
      },
      "value": "LE000001"
    },
    "sorts": [
      {
        "type": "BusinessAttribute",
        "property": "code",
        "order": "ASC"
      }
    ],
    "pagination": {
      "pageNum": 1,
      "pageSize": 20
    }
  }
}

```

**响应（mock）**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "resultType": "GRAPH",
    "result": {
      "vertices": [
        {
          "id": "#13:1",
          "type": "LogicalEntity",
          "properties": {
            "code": "LE000001",
            "name": "SalesOrder",
            "label": "销售订单"
          }
        },
        {
          "id": "#14:1",
          "type": "BusinessAttribute",
          "properties": {
            "code": "ATT_ORDER_ID",
            "name": "orderId",
            "label": "订单号"
          }
        },
        {
          "id": "#14:2",
          "type": "BusinessAttribute",
          "properties": {
            "code": "ATT_ORDER_AMT",
            "name": "orderAmount",
            "label": "订单金额"
          }
        },
        {
          "id": "#14:3",
          "type": "BusinessAttribute",
          "properties": {
            "code": "ATT_ORDER_STATUS",
            "name": "orderStatus",
            "label": "订单状态"
          }
        }
      ],
      "links": [
        {
          "id": "#21:1",
          "relation": "LEContainATT",
          "source": "#13:1",
          "target": "#14:1",
          "properties": {}
        },
        {
          "id": "#21:2",
          "relation": "LEContainATT",
          "source": "#13:1",
          "target": "#14:2",
          "properties": {}
        },
        {
          "id": "#21:3",
          "relation": "LEContainATT",
          "source": "#13:1",
          "target": "#14:3",
          "properties": {}
        }
      ]
    },
    "pagination": null
  }
}

```