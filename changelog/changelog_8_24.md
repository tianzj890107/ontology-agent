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

### 3. 建模暂停提示改为可折叠详情（按要求未部署）

- 47314 运行被门禁/安全阀暂停时，思维链末尾的暂停节点正式输出只保留【建模已暂停】、当前产物说明与继续运行指引；暂停原因和未通过的门禁校验项收进“暂停详情（点击展开）”折叠区，默认隐藏、点击展开。
- 前端 `AssistantText` 新增 `:::details` 折叠块渲染（复用现有迷你 Markdown 解析，内部段落/列表/表格均可正常渲染），新增 `.assistant-details` 折叠区样式；`frontend/dist` 已随构建更新。
- 验证：`npm run build`（vite 构建通过）；`.venv/bin/python -m unittest tests.test_frontend_contract` 通过（8 项）；`git diff --check` 通过。按要求本次未部署 47313/47314。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`changelog/changelog_8_24.md`。
