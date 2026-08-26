# 20260826 变更记录

> 本文档记录 `20260727` 分支在 2026-08-26 的变更。

## 维护规则

- 每次功能修改后，在本记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。
- 当日记录按功能最终状态组织：合并同一功能的中间修改、修订过时描述，只保留最终用户可见行为、重要内部契约、主要文件和验证结果。
- 历史 changelog（`changelog_8_25.md` 及更早）不再修改；昨日遗留未完成项如需延续，在今日记录中注明。

## 2026-08-26

### 1. 本体可视化改为径向分层多轨道环形布局

- 布局：以画布中心为圆心，由内向外为业务对象（第一层）→ 逻辑实体（第二层）→ 业务属性（第三层，默认隐藏）；每层是环形区域，节点过多时按扇区/角度自动增加多条相邻轨道；业务对象各占独立扇区，扇区角度与后代节点数量成正比（不平均、不写死）。
- 新增 `frontend/src/ontologyRadialLayout.js` 纯函数模块：`normalizeOntologyData`、`computeSectorWeights`（扇区权重）、`computeTrackCapacity`（单轨容量，含最小安全间距）、`computeTrackCount`（轨道数量）、`computeRingRadius`（轨道半径）、`computeNodeAngle`（节点角度）、`polarToCartesian`（极坐标转笛卡尔）、`layoutOntologyRadial`（生成最终 ECharts nodes/links）。
- 半径与画布：每层半径按上一层最大节点尺寸、当前层最大尺寸、节点数量、画布尺寸与最小安全间距动态计算；放不下时扩大内部画布（滚动/缩放/平移），外圈预留节点半径与悬浮放大空间，不裁切气泡；不通过缩小气泡硬塞。
- 连线只保留真实关系：业务对象→逻辑实体、逻辑实体→业务属性；移除隐藏技术根 `ontology:unassigned-entities`/`virtualGroup`；无业务对象时逻辑实体作为最内层；无逻辑实体时不生成图；无属性时只绘制已有层级。
- 交互：保留全局“展开业务属性/隐藏业务属性”按钮，切换后重建完整环形布局；触控板双指滑动平移（wheel→graphRoam）、捏合缩放（ctrlKey 放行给 ECharts roam）、拖拽平移（`roam:true`）；ResizeObserver 在窗口/全屏变化后重算；不允许点击折叠；悬浮仅轻微放大（scale 1.12，focus none）。
- 样式沿用：业务对象蓝、逻辑实体绿、业务属性灰、横向椭圆、白色居中截断标签、浅灰连线、扇区间明显间隔。
- 测试：新增 `frontend/tests/ontologyRadialLayout.test.mjs`（`node --test` 15 项：扇区权重、轨道容量/数量、半径、极坐标、无对象时实体最内层、属性默认隐藏、只生成真实 links、属性多轨道不重叠、边界不裁切、画布扩大）；`tests/test_frontend_contract.py` 本体可视化契约更新为径向布局断言（Graph/layout none、无 Tree、无隐藏技术根、纯函数存在、多轨道、安全间距、无点击折叠、双指平移、捏合缩放、ResizeObserver）。
- 验证：全量 `pytest tests/` 512 passed, 13 skipped, 344 subtests passed；node 测试 15/15；`npm run build` 成功（新 bundle `index-CpekmpJY.js`/`index-I8FPupji.css`，echarts 按需 chunk `index-CzJ1nSGZ.js`；仅存既有大 chunk 警告）；`git diff --check` 通过。
- 主要文件：`frontend/src/ontologyRadialLayout.js`（新增）、`frontend/src/main.jsx`、`frontend/tests/ontologyRadialLayout.test.mjs`（新增）、`tests/test_frontend_contract.py`、`frontend/dist/`。
