# 2026-08-19 变更记录

- 创建今日独立变更记录；从本文件创建后，今天后续完成的代码、配置、测试和部署变更统一按最终结果追加记录。

- 修复 v0.0.1 逻辑实体主标记生成与校验：未归属业务对象、CANDIDATE/REJECTED 或非 CONFIRMED 业务对象的实体保留实体记录但强制 `mainflag=N`，不再通过 exporter 临时改值。
- 修复 `V0001_DUPLICATE_FORMAL_NAME` 的作用域：业务属性名称按“逻辑实体编码 + 属性名称”判重；同实体重复为 ERROR，跨实体同名允许，定义明显不同仅 WARNING；未引入属性自动改名或实体前缀。
- 新增状态级、正式 CSV 级和生成逻辑回归测试；本次未部署。
- 将单次建模默认门禁修复次数从 3 次调整为 10 次；仍保留“相同门禁错误且没有新证据立即 BLOCKED”的安全阀。本次未部署。
- 修复 Business Object R1–R5 证据归类：UNKNOWN 不再作为有充分证据时的默认状态；增加正向证据、明确反证、证据冲突、0 行实例化结构和静态有限值域的确定性判断，并补充回归测试。本次未部署。
- 修复本体建模门禁严重度：证据不足、UNKNOWN、未确认归属、技术物理键缺少逻辑键证据、指标聚合语义未确认等改为 WARNING；WARNING 不触发阶段失败、最终导出阻断或 Agent 重试。确认关系缺少支持证据、非法结构、冲突关系和审计/CSV schema 错误继续保持 ERROR。
- 新增输入资产处理覆盖校验：要求每个输入资产都有 MODELED、EXCLUDED、TECHNICAL、REJECTED 或 UNKNOWN 等处理决策；未处理资产才是 coverage ERROR，不要求所有资产都进入正式本体。新增相关门禁与最终 gate 回归测试，本次未部署。
- 新增 DeepSeek 思考模式可恢复错误自动重试：模型网关返回 “reasoning_content … must be passed back” 类 400 时，OpenAI 兼容适配器自动以原请求重试一次、再以去除 reasoning 的出站历史重试一次，成功后任务自动继续执行并在审计中记录 `provider_retry` 事件，不再直接标记 FAILED；重试仍失败时才进入失败状态。涉及 `open_claude/openai_compat.py` 与 `oc_codex_server.py`，并补充适配器与任务层回归测试。已部署两个服务（commit `e083041`，web 47313 与 standalone 47314 均已重启，健康检查 200，部署前确认两服务无活跃任务）。
- 独立建模服务(47314)取消 `READY_FOR_EXPORT` 中间状态：语义校验通过后 run 直接进入 `SUCCEEDED`，不再停在"待导出"等待状态（前端仅提供下载、无导出按钮）。同步更新状态机、`run_ready` 事件判定、standalone 前端状态展示/已完成提示、API 文档与相关回归测试，并重新构建 `frontend/dist`。已部署两个服务（commit `5142ffc`，web 47313 与 standalone 47314 均已重启，健康检查 200，部署前确认两服务无活跃任务）。
