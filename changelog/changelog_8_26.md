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
- 预览标题栏：筛选、全屏和关闭三个 32px 图标按钮对齐到同一水平基线，并统一相邻按钮的视觉间距。
- 文件兼容：47313/47314 均从当前 task/run 文件快照读取五层产物并保持沙盒隔离；指标优先使用正式 `metrics.csv`，兼容 `indicators.csv`、`indicator.csv`、`atomic_indicators.csv`、`composite_indicators.csv`，规则兼容 `business_rules.csv` / `rules.csv`。指标仅在来源业务对象、逻辑实体或业务属性能按编码/名称解析时生成真实连线；当前规则正式表没有归属字段，只显示规则节点，不虚构关系。
- 布局：`frontend/src/ontologyRadialLayout.js` 改为由 `ONTOLOGY_LAYER_DEFINITIONS` 驱动的配置化五层布局。每个语义层全局共享轨道，同时按业务对象建立方向扇区：业务对象及其逻辑实体、属性保持在同一方向，各扇区在每条轨道轮流取节点，避免不同业务对象分别独占内外轨；扇区按节点量平方根加权，数据多的位置获得更宽空间但仍自然更密集，不再强制全圆平均分布。每生成更外轨道都按实际半径重新计算容量，并通过实际椭圆包围盒碰撞检查自动扩圈。
- fit 与边界：先生成完整、无重叠的自然坐标，再根据当前 viewport 统一等比 fit；两个不可见、无连线、无交互的边界锚点固定 ECharts Graph 的自然坐标边界，避免首尾节点中心被二次映射到画布边缘。少量轨道保持完整铺满；轨道很多时应用 0.65 可读显示比例下限，避免节点与文字缩成不可读尺寸，超出区域可用既有平移查看。每次确认筛选或 ResizeObserver 检测到尺寸变化时重置视图。
- 缩放与漫游：节点启用 `nodeScaleRatio: 1`，初始节点尺寸、字号和线宽使用同一 fit 比例；缩小时文字与节点同步缩小，放大时文字同步增长但在 1.8 倍封顶。保留普通双指横向/纵向滑动画布平移、触控板捏合缩放、按住拖动平移；悬浮仅放大当前节点，不淡化其他节点，也没有节点折叠交互。
- 验证：Node 布局测试 13 项通过，覆盖五层配置、外圈容量递增、业务对象扇区密度加权、父子方向一致、跨扇区逐轨轮转、宽节点与多实体属性无重叠、实际边界锚点、fit 与字号缩放；相关 Python 测试 20 项通过；`npm run build` 成功，标题栏微调后的 bundle 为 `index-CW6dV3WA.js` / `index-Cr6Tpgtr.css`（仅有既有大 chunk 警告）；`git diff --check` 通过。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/ontologyRadialLayout.js`、`frontend/src/styles.css`、`frontend/tests/ontologyRadialLayout.test.mjs`、`tests/test_frontend_contract.py`、`frontend/dist/`。
- 部署：五层筛选的前一版功能提交 `1079d26` 已推送并发布，线上 JS/CSS 为 `index-C4TeUgpv.js` / `index-DY8plCOl.css`；本次方向扇区与可读比例优化仅完成本地修改、测试和生产构建，尚未部署、提交或推送。
