# 20260826 变更记录

> 本文档记录 `20260727` 分支在 2026-08-26 的变更。

## 维护规则

- 每次功能修改后，在本记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。
- 当日记录按功能最终状态组织：合并同一功能的中间修改、修订过时描述，只保留最终用户可见行为、重要内部契约、主要文件和验证结果。
- 历史 changelog（`changelog_8_25.md` 及更早）不再修改；昨日遗留未完成项如需延续，在今日记录中注明。

## 2026-08-26

### 1. 本体可视化五层筛选与径向共享轨道布局

- 图层筛选：移除画布上方“展开/隐藏业务属性”按钮，在预览卡片右上角的全屏与关闭按钮左侧新增漏斗图标；弹层固定提供业务对象、逻辑实体、业务属性、指标、业务规则五项 Checkbox，当前工作区缺少或没有有效数据的图层置灰。默认应用业务对象与逻辑实体；筛选使用 `draftLayers` / `appliedLayers` 两阶段状态，勾选只修改草稿，点击“确认”才重建一次图，取消、关闭弹层或点外部不会改变当前图。
- 文件兼容：47313/47314 均从当前 task/run 文件快照读取五层产物并保持沙盒隔离；指标优先使用正式 `metrics.csv`，兼容 `indicators.csv`、`indicator.csv`、`atomic_indicators.csv`、`composite_indicators.csv`，规则兼容 `business_rules.csv` / `rules.csv`。指标仅在来源业务对象、逻辑实体或业务属性能按编码/名称解析时生成真实连线；当前规则正式表没有归属字段，只显示规则节点，不虚构关系。
- 布局：`frontend/src/ontologyRadialLayout.js` 改为由 `ONTOLOGY_LAYER_DEFINITIONS` 驱动的配置化五层布局。每个语义层全局共享轨道，同一属性圈可同时容纳不同逻辑实体的属性；每生成更外轨道都按实际半径重新计算更大的周长容量，径向初始间距使用节点高度，并通过实际椭圆包围盒碰撞检查逐步扩圈，业务对象内圈容量不足也自动使用共享后续轨道。
- fit 与边界：先生成完整、无重叠的自然坐标，再根据当前 viewport 统一等比 fit；两个不可见、无连线、无交互的边界锚点固定 ECharts Graph 的自然坐标边界，避免首尾节点中心被二次映射到画布边缘。每次确认筛选或 ResizeObserver 检测到尺寸变化时重置视图并重新铺满画布。
- 缩放与漫游：节点启用 `nodeScaleRatio: 1`，初始节点尺寸、字号和线宽使用同一 fit 比例；缩小时文字与节点同步缩小，放大时文字同步增长但在 1.8 倍封顶。保留普通双指横向/纵向滑动画布平移、触控板捏合缩放、按住拖动平移；悬浮仅放大当前节点，不淡化其他节点，也没有节点折叠交互。
- 验证：Node 布局测试 11 项通过，覆盖五层配置、外圈容量递增、6 个 220px 宽业务对象多轨无重叠、3 个逻辑实体各 40 个属性共享轨道、实际边界锚点、fit 与字号缩放；接近实际规模的 4 个业务对象、24 个实体、644 个属性压力用例共 672 节点，约 9ms 完成、无重叠，属性 12 条共享轨道容量由 22 递增到 90。相关 Python 测试 20 项通过；`npm run build` 成功（bundle `index-C4TeUgpv.js` / `index-DY8plCOl.css`，仅有既有大 chunk 警告）；`git diff --check` 通过。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/ontologyRadialLayout.js`、`frontend/src/styles.css`、`frontend/tests/ontologyRadialLayout.test.mjs`、`tests/test_frontend_contract.py`、`frontend/dist/`。
- 部署：功能提交 `1079d26` 已推送并发布；部署前两套任务存储均无活动或排队任务，47313 pid `3679820`、47314 pid `3681321`。服务器发布门禁 20 项通过，线上 JS/CSS 为 `index-C4TeUgpv.js` / `index-DY8plCOl.css`，两服务健康检查通过。
