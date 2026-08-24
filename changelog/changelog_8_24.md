# 20260824 变更记录

> 本文档记录 `20260727` 分支在 2026-08-24 的变更。

## 维护规则

- 每次功能修改后，在本记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`；独立建模服务端口：`47314`。
- 部署基线：所有功能改动以同一 commit 部署 47313/47314（部署前确认无活跃任务），两服务 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`。
- 本周周报已基于 `changelog_8_17_21.md` 与日报规范生成并输出（文本，未落文件）。

## 2026-08-24

### 1. Git 部署线路问题处理（本地推送 / 服务器拉取）

- 本地 git push 直连 `github.com` 失败（SSH 解析/路由需走 `127.0.0.1:7890` 代理，直连超时）；改用 GitHub SSH-over-443（`ssh.github.com:443`）+ `nc -X connect -x 127.0.0.1:7890` 代理成功推送，无需修改 remote。
- 服务器 `git fetch` 受 `https_proxy=http://172.16.10.34:7890` 影响 TLS 握手失败；绕过代理直连后 fetch/merge 正常，服务器 HEAD 与 `origin/20260727` 同步为 `413c221`。
- 两服务运行代码不受影响（本次仅 changelog/运维动作），`/health` 保持 200。
- 主要文件：`changelog/changelog_8_24.md`。

### 2. 两个服务统一更新团队模型目录

- 47313 工作台与 47314 独立建模服务共用的团队模型目录由 8 个扩展为 24 个已验证可完成对话的模型，排除网关未路由或上游鉴权失败的 `mimo-v2-pro`、`mimo-v2-flash`、`claude-opus-4-8`、`test`。
- 两个服务的默认模型统一为 `qwen3.8-27b`；未显式配置、配置过期或无效时优先回退到该模型，仅当自定义目录不包含它时才回退到目录首项。
- 同步本地运行配置与 `.env.example`，真实团队密钥仍只保留在未提交的 `.env`；补充 24 模型数量、失败模型排除和默认模型回归测试。
- 验证：`python -m unittest tests.test_team_config` 通过（3 项）；隔离加载确认 47313/47314 均返回 24 个模型且默认 `qwen3.8-27b`；`git diff --check` 通过。完整 `tests.test_standalone_modeling_server` 因既有用例触发真实后台任务、清理阶段等待执行线程而中止，未计为通过。
- 已部署提交 `8a70629`：服务器 19 项部署相关测试通过，47313/47314 重启后健康检查均为 200，两个模型接口均返回默认 `qwen3.8-27b`、24 个模型且不含上述 4 个失败模型。依赖同步曾因服务器访问 PyPI 的 TLS 故障失败，本次无依赖变化，最终使用已通过测试的现有共享 venv 启动。
- 主要文件：`open-claude/open_claude/config.py`、`.env.example`、`open-claude/README.md`、`tests/test_team_config.py`、本地 `.env`。

### 3. 建模暂停提示改为可折叠详情

- 47314 运行被门禁/安全阀暂停时，思维链末尾的暂停节点正式输出只保留【建模已暂停】、当前产物说明与继续运行指引；暂停原因和未通过的门禁校验项收进“暂停详情（点击展开）”折叠区，默认隐藏、点击展开。
- 前端 `AssistantText` 新增 `:::details` 折叠块渲染（复用现有迷你 Markdown 解析，内部段落/列表/表格均可正常渲染），新增 `.assistant-details` 折叠区样式；`frontend/dist` 已随构建更新。
- 验证：`npm run build`（vite 构建通过）；`.venv/bin/python -m unittest tests.test_frontend_contract` 通过（8 项）；服务器 `git pull --ff-only` 后两服务已重启至 `12100b1`，47313/47314 的 `/`、`/health` 均 200，启动日志均含 `provider transport timeouts: connect=5s read=600s write=600s pool=600s`，两服务实际返回的新 bundle 均含“暂停详情”折叠标记。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`changelog/changelog_8_24.md`。

### 4. 独立建模默认模型固定为 qwen3.8-27b

- 修复 47314 打开历史 run 时用该 run 的历史模型（如 `qwen3.7-plus`）覆盖当前选择的问题；现在任何人刷新浏览器或重新进入页面，模型都固定取服务端默认 `qwen3.8-27b`，不再恢复 run 的历史模型，仅用户在当前会话显式选择才会改变。
- 前端移除打开 run、缓存命中、run 创建后的 `setStandaloneModel(run.model)` 恢复逻辑，组合框展示不再回退到 `run.model`。
- 验证：`npm run build`（vite 构建通过）；`.venv/bin/python -m unittest tests.test_frontend_contract` 通过（8 项）；`git diff --check` 通过；已部署 47313/47314 至 `a7fb0b0`，两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，`/api/modeling-models` 默认返回 `qwen3.8-27b`（24 个模型），线上实际返回的新 bundle 已不含 run 模型恢复逻辑。
- 主要文件：`frontend/src/main.jsx`、`frontend/dist/`、`changelog/changelog_8_24.md`。

### 5. 续跑用户输入显示为用户气泡

- 修复 47314 续跑时用户输入不显示气泡的问题：服务端 `execute` 收到显式 `prompt` 时，先把用户文本作为 `user` 事件写入 run 日志（位于 `run_queued` 之前），并保留原始 `run.prompt` 不再被续跑文本覆盖；前端事件流因此按“原始提示气泡 → 历史事件 → 续跑用户气泡 → run_queued/run_started/…”顺序渲染，刷新后仍保留。
- 补充两条回归测试：续跑显式文本时写入单个 `user` 事件且原始 prompt 不变、事件顺序为 `user → run_queued`；无显式文本（如“继续运行”按钮）时不写入 `user` 事件。测试中先停并 join 调度线程，避免调度器 CLAIM 入队 run 触发真实后台任务。
- 验证：新增 2 项与相关续跑/表数量问答共 5 项测试连续 3 轮通过；`py_compile`、`tests.test_frontend_contract`（8 项）、`git diff --check` 均通过。
- 部署：已部署 47313/47314 至 `55cd46d`（与第 6 条同批）。部署前确认无活跃任务；服务器直连 `github.com` 超时，改用本地 bundle+scp 传输提交；服务器访问 PyPI TLS 故障导致 pip 构建隔离失败，改为 `--no-build-isolation --no-deps` 离线安装本地 wheel、`--no-index` 装齐 requirements 并更新依赖指纹 stamp 后重跑部署；47313 经 `scripts/deploy_server.sh`（16 项部署相关测试通过），47314 经 `scripts/run_standalone_modeling.sh` 重启，两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行。
- 主要文件：`open-claude/standalone_modeling_server.py`、`tests/test_standalone_modeling_server.py`、`changelog/changelog_8_24.md`。

### 6. 默认模型改回 Qwen/Qwen3-80B-AWQ

- 47313 工作台与 47314 独立建模服务默认模型由当日早前统一的 `qwen3.8-27b` 改回 `Qwen/Qwen3-80B-AWQ`（第 2/4 条曾为 27b，现按需求改回）：`config.py` 内置默认改回 80B，内置团队目录末尾显式保留 `qwen3.8-27b` 条目（避免与 80B 去重导致目录变 23 个）；`.env.example` 与本地、服务器 `.env` 同步为 `TEAM_MODEL=Qwen/Qwen3-80B-AWQ`。
- README 默认模型说明与团队配置回归测试同步更新；目录仍为 24 个模型，未显式配置、配置过期或无效时优先回退到 80B，仅当自定义目录不含它时才回退到目录首项。
- 验证：`tests.test_team_config` + `tests.test_frontend_contract` 共 11 项本地通过；已部署 47313/47314 至 `55cd46d`（与第 5 条同批），两服务 `/`、`/health` 均 200，启动日志均含 transport timeouts 行，`/api/meta`（47313）与 `/api/modeling-models`（47314，带 `X-Modeling-API-Key`）均返回默认 `Qwen/Qwen3-80B-AWQ`、24 个模型。
- 主要文件：`open-claude/open_claude/config.py`、`.env.example`、`open-claude/README.md`、`tests/test_team_config.py`、本地与服务器 `.env`、`changelog/changelog_8_24.md`。
