# 2026-08-21 变更记录

- 创建今日独立变更记录；从本文件创建后，今天后续完成的代码、配置、测试和部署变更统一按最终结果追加记录。

- 切换 47313/47314 两个服务的默认大模型：DeepSeek V4 Flash（`direct-deepseek-v4-flash`）→ Qwen3 80B AWQ（`Qwen/Qwen3-80B-AWQ`）：
  - 根因/背景：此前两个服务默认模型均为 `direct-deepseek-v4-flash`（`.env` 中 `TEAM_MODEL` 决定 `DEFAULT_MODEL`，provider 为 team 网关）；`Qwen/Qwen3-80B-AWQ` 已在 `TEAM_MODELS` 候选列表中但非默认。
  - 变更：仅配置改动，不涉及代码。本地与服务器 `.env` 的 `TEAM_MODEL` 均改为 `Qwen/Qwen3-80B-AWQ`（服务器改前备份 `.env.bak-20260821-092855`；`.env` 属 gitignored，不入库）；47313 与 47314 分别重启加载新默认值。
  - 验证：服务器侧 `get_model()` 返回 `Qwen/Qwen3-80B-AWQ`（provider=team），可用模型列表不变（deepseek-v4-flash/pro、qwen3.7-plus、glm-5.1、kimi-k2.6、glm-5.2、glm-5-turbo 等仍可手动选择）；47313 `/api/model` 与 47314 `/api/modeling-models`（带 X-Modeling-API-Key）均返回默认 `Qwen/Qwen3-80B-AWQ`；两个服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s` 且无新增 traceback；真实网关冒烟：`Qwen/Qwen3-80B-AWQ` 首轮产出 tool_calls、次轮回传后 end_turn，无 400。部署前确认两服务无活跃任务（47313 working=0，47314 active=0/queued=0）。

- 修复“前端默认模型仍不是 Qwen”的用户级偏好残留（服务器配置，不入库）：
  - 根因：浏览器用户 `local:Zzp-tQUyaM8YNUhRs0msfli-` 在 `~/.claude/ontology-agent-user-settings.json` 中保存了旧偏好 `qwen-vl-ocr-latest`（OCR 模型）。`/api/meta` 的 `model` 由 `user_model(user_id)` 决定，该偏好会在命中 `configured_models()` 时覆盖服务端默认；此前该 id 曾位于 Qwen 视觉模型列表，导致 47313 前端显示 OCR 模型而非 Qwen 默认。
  - 变更：将该用户偏好原子改写为 `Qwen/Qwen3-80B-AWQ`（python 原子写，保留文件权限；`user_model()` 实时读取，无需重启服务）。
  - 验证：服务器 `user_model(local:Zzp-tQUyaM8YNUhRs0msfli-)` 与无偏好用户均返回 `Qwen/Qwen3-80B-AWQ`；带该用户 cookie 请求 47313 `/api/meta` 返回 `model=Qwen/Qwen3-80B-AWQ`、`provider=team`；47314 `/api/modeling-models` 同样返回 Qwen。前端模型选择器按 `/api/meta.model` 展示，刷新页面即生效。
- 服务器部署线路核查（无代码变更）：
  - SSH `company-server`、git remote（`github.com/tianzj890107/ontology-agent.git`，分支 `20260727`）与 `git fetch` 均正常；`scripts/deploy_server.sh`、`scripts/run_standalone_modeling.sh` 无需修改。
  - 47313 `/`、`/health` 与 47314 `/`、`/health` 全部返回 200；两个服务启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。
  - 服务器存在 root 用户残留进程 `python3 -`（PID 2204477，父 2204441，已运行约 9 天，CPU 99.9%），为死循环占用，与本次部署无关；zhangzhen 无 sudo 权限，需管理员核实后 `kill 2204477`。

- 修复建模正式 CSV 门禁过松：确定性格式/结构问题未按 STRUCTURAL_BLOCKER 阻断（已部署 47313/47314，commit `4e5e57b`）：
  - 根因：旧门禁把一部分确定性格式问题（缺少关系基数、M:N 未拆分、主实体数量错误等）归入可自动降级的 FORMAL_ELIGIBILITY，导致非法正式记录可能随 PASSED 结果交付；上传入口只做语法检查，与 finalize 校验规则分散硬编码，两处行为不一致。
  - 变更：新增集中式逐行字段契约注册表 `open_claude/modeling_csv_contract.py`（`CSVContract` + `CONTRACTS`，覆盖 25 个文件名含全部别名）：统一声明必填字段、Y/N 布尔、枚举、非负整数、编码格式、文件内唯一、中文/英文名称职责分离、JSON 数组与相似度范围、条件结构规则（主逻辑实体数量、主终态蕴含终态、页面显示规则）与跨文件引用；上传入口（`oc_codex_server.validate_modeling_csv`/`validate_integration_csv`）与最终语义门禁（`modeling_rule_registry.validate_formal_rows`）共用同一 `validate_row_contract`，消除规则漂移；`semantic_checks` 参数保留但不再切换确定性格式规则。门禁层次恢复：上传入口只做确定性格式/逐行字段契约，不做 R1-R5/证据充分性/资格语义；证据不足、定义质量（与名称相同的弱定义）、指标/规则语义继续保持 WARNING，不再升级为结构阻断。
  - STRUCTURAL_BLOCKER 边界：`V0001_FORMAL_*`/`V0001_MAIN_FLAG_*`（含缺失基数、M:N 未拆分、主实体数量、无业务对象主标志、编码重复、必填缺失）全部恢复阻断；`_FORMAL_ELIGIBILITY_CODES` 收窄为仅 `UNSUPPORTED_CONFIRMED_RELATION`、`TRANSFORMATION_EVIDENCE_GATE`、`UNSUPPORTED_STATUS_UPGRADE`、`RELATION_DECISION_MISSING_FROM_FORMAL_OUTPUT` 四个真实资格降级。
  - 正式输出资格：finalize 新增 `_formal_eligibility_issues`，状态决策为 CANDIDATE/UNRESOLVED/REJECTED 的实体/属性行若仍出现在正式 CSV，报 `FORMAL_OUTPUT_INELIGIBLE_ROW` 阻断；正式关系 CSV 中无决策/无证据/非 CONFIRMED 的关系行同样阻断；新增 `_formal_cross_file_issues` 在全部请求文件就绪后执行跨文件引用存在性检查（源文件未请求时跳过，避免误报），覆盖 business_objects/logical_entities/business_attributes/entity_relations(+别名)/business_object_relations(+别名)/statuses(+别名)。
  - 各文件契约要点：business_objects 编码/名称/定义必填、定义完全为空为格式错误阻断（弱定义仅 WARNING）；logical_entities 六必填+业务对象编码与名称不得只填一边+每个正式业务对象有且仅有一个主逻辑实体；business_attributes 名称中英混杂阻断、英文名须符合英文标识格式、数据长度/精度非负整数、数据类型枚举；entity_relations 关系分类/基数枚举、源目标实体引用存在、关联属性编码须能在对应实体找到；business_object_relations 类型/基数枚举、源目标业务对象引用存在；statuses 主终态=Y 蕴含终态=Y、状态编码业务对象内唯一；events 编码唯一、中英文名称职责分离；business_rules 编码 R+7 位数字唯一、证据充分性仍 WARNING；terms/metrics 核心必填与格式阻断、语义质量仍 WARNING；整合报告类 CSV 补充必填/枚举/JSON 数组/相似度 0~1。
  - 测试：新增 `tests/test_modeling_csv_contract.py`（23 个参数化回归用例，覆盖每种正式 CSV 每个必填字段置空/纯空格失败、名称中英混杂失败、英文列通过、非法 Y/N/枚举/整数/编码失败、跨文件引用不存在失败、FORMAL_ELIGIBILITY 不能掩盖非法正式记录、语义问题仍 WARNING、上传与 finalize 结论一致、47313/47314 共用同一契约链）；更新 `tests/test_v0001_rule_registry.py`、`tests/test_gate_action_normalization.py`（空定义阻断/弱定义警告拆分）、`tests/test_modeling_reliability.py`（关系行无资格改为 FORMAL_OUTPUT_INELIGIBLE_ROW）。完整测试集 `.venv/bin/python -m unittest discover -s tests`：335 OK（skipped=3）；`py_compile` 8 个涉及文件通过；`git diff --check` 通过。
  - 部署：commit `4e5e57b` 推送 origin `20260727` 后部署到两个服务（部署前确认无活跃任务：47313 working=0，47314 runs 为空）。47313 用 `scripts/deploy_server.sh`（pull 后跑 16 项冒烟测试+py_compile，重启 pid 1068774）；47314 停旧进程后以 `run_standalone_modeling.sh` 重启（pid 1069752）。两服务 `/` 均 200，47313 `/health` 200；服务器 `git rev-parse HEAD=4e5e57b`；两个启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。

- Agent 前端错误展示友好化：思维链/输出中的错误不再显示红色感叹号，统一转为灰色提示（已部署 47313/47314，commit `9456fa1`）：
  - 范围：只改 agent 相关展示；页面级原生错误（网络断开、401 登录失效、接口请求失败等 `Alert type="error"`/`messageApi.error`）保持原样。
  - 变更（`frontend/src/main.jsx` + `frontend/src/styles.css`，重新构建 `frontend/dist`）：`error`/`is_error` 事件的思维链图标由红色 `!` 改为灰色 `ℹ`，标题由 `error` 改为 `提示`，描述转为 `提示：{原因}`；`done` 事件 `status=error` 显示为 `本轮执行结束 · 未完成（可继续执行）`；任务列表 error 红点、思维链 error 图标样式由 `#b91c1c` 红改为灰色（`#64748b`/`#e2e8f0`、`#94a3b8`）；47314 run 状态 FAILED 的红色 Tag 改为灰色。后端事件协议（`type=error`、`is_error`、平台 FAILED 回写与审计）保持不变，仅前端呈现层转化。
  - 验证：`npm run build` 成功；产物中无 `#b91c1c` 红色残留，灰色样式与提示文案已进入 `frontend/dist`。
  - 部署：`58ad07c`+`9456fa1` 推送后部署两服务（部署前无活跃任务：47313 working=0、47314 runs 空）；部署脚本服务器端测试曾因旧断言失败（断言红色 `!` 图标），已同步更新 `tests/test_frontend_contract.py` 为新灰色实现后通过（16 OK）；47313 经 `deploy_server.sh` 重启（pid 1795225），47314 重启（pid 1795966）；两服务 `/` 均 200，47313 `/health` 200；服务器 `git rev-parse HEAD=9456fa1`，`frontend/dist` 已含新产物（`index-CnzYGS2x.js`/`index-btbEKNUv.css`，含灰色 error 样式与提示文案），47314 日志含 timeout 配置。
