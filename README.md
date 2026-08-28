# 硕磐智能建模

当前版本：`v0.1.0`

## 项目简介

硕磐智能建模是面向本体建模与语义资产治理的 Agent 工作台，提供任务式智能建模、独立建模、建模结果校验、文件管理和本体可视化能力。

## 核心能力

- 数据库建模、文档建模、自然语言建模；
- 业务对象、逻辑实体、业务属性、实体关系识别；
- 业务规则、业务术语、指标、动作识别；
- 文件、CSV、Excel 和本体结果预览；
- 关系聚类可视化（Sigma/ForceAtlas2）与语义环形可视化（ECharts）；
- 任务/run 历史、事件记录、执行恢复；
- input/work/output 工作区隔离；
- 建模结果语义校验、决策审计和规范化上传门禁。

## 服务组成

| 服务 | 默认端口 | 作用 |
| --- | --- | --- |
| 任务式 Agent 工作台 | 47313 | 平台任务、对话执行、结果回写与文件管理 |
| 独立建模服务 | 47314 | 不依赖平台任务的独立本体建模 |

两个服务的产品名称均为 **硕磐智能建模**，产品显示版本均为 **v0.1.0**。

## 技术架构

- Python 后端（Agent 执行、API 服务、独立建模服务）；
- React + Ant Design + Vite 前端工作台；
- SQLite 本地任务状态，Redis 可选协调后端；
- OpenAI-compatible / Anthropic 模型适配；
- 本地任务工作区与 CSV/XLSX 建模产物；
- MinIO 对象存储作为结果上传回写集成能力。

## 项目结构

```
ontology-agent/
├── open-claude/       # Agent、API 和独立建模服务
├── frontend/          # React 工作台
├── agent_knowledge/   # 建模知识与生成内容
├── rules/             # 规则与模板源文件
├── tests/             # Python 测试
├── API/               # API 文档
├── docs/              # 项目、版本与归档文档
│   ├── versions/          # 正式版本说明
│   ├── changelog/         # 每日工程记录
│   └── eimosp-foundation-fileserver.md  # Eimosp 文件服务归档参考
└── scripts/           # 本地构建和运维脚本
```

## 本地开发

后端依赖：

```bash
cd open-claude
pip install -e .
```

前端：

```bash
cd frontend
npm install
npm run dev
```

本地启动服务（用于联调，不执行服务器部署）：

```bash
# 任务式 Agent 工作台（47313）
.venv/bin/python open-claude/oc_codex_server.py

# 独立建模服务（47314）
bash scripts/run_standalone_modeling.sh
```

本地 README 不把服务器部署脚本作为普通开发启动命令；部署仅由人工在用户明确授权后执行。

## 配置说明

参考 `.env.example` 配置主要类别：

- 模型提供方与 API Key；
- 服务端口；
- 数据目录；
- Redis/协调后端；
- 数据库数据源配置。

禁止提交真实密钥；`.env`、`.venv`、`open-claude/sandbox/` 和会话数据不得提交。

## 测试与构建

```bash
.venv/bin/python -m pytest -q
```

```bash
cd frontend
node --test 'tests/*.test.mjs'
npm run build
```

知识构建（仅规则源文件修改时运行）：

```bash
python scripts/build_agent_knowledge.py
```

## API 文档

- [独立建模 API](./API/standalone-modeling-api.md)
- [后端与 Agent 交互 API](./API/backend-agent-interaction-api.md)
- [本体元数据查询 API](./API/本体元数据查询API-WIP.md)
- [本体实例计算 API](./API/本体实例计算API-WIP.md)

## 版本历史

当前版本：[`v0.1.0`](./docs/versions/v0.1.0.md)

- [查看全部正式版本](./docs/versions/README.md)

## Git 协作

本项目使用双远端镜像工作流：

- 主协作分支：`origin/20260727`
- 个人私有镜像：`personal/main`

详细说明见：[Git 双远端镜像工作流](./docs/git-dual-remote-workflow.md)

## 工程记录

- [每日开发记录](./docs/changelog/README.md)

## 安全说明

- 不提交真实密钥；
- 任务和 run 数据应与发布代码隔离；
- 删除运行数据必须遵守 AGENTS.md 的文件与数据删除安全规则；
- 默认工作流完成本地验证、commit、push 后结束；
- 部署必须由用户在当前任务中明确授权，Agent 不得自行部署。

## 许可证

Open Claude 子项目许可证见 `open-claude/LICENSE`；仓库其他部分的许可范围请联系项目维护者确认。
