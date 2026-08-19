# ontology-agent 部署说明

生产发布固定使用 GitHub `20260727` 分支：本地完成验证和前端构建后提交并推送，服务器只从该分支快进拉取，再重启 47313 服务。

## 本地发布

```bash
cd /path/to/ontology-agent
python3 -m unittest tests.test_ontology_knowledge tests.test_frontend_contract
cd frontend && npm run build && cd ..
git add -A
git commit -m "本次发布说明"
git push origin 20260727
```

`frontend/dist/` 必须随提交发布，服务器不依赖 Node.js 现场构建。`.env`、`.venv`、`open-claude/sandbox/` 和会话数据不得提交。

## 服务器部署

当前服务器约定：

- SSH：`company-server`（当前解析为 `zhangzhen@172.16.10.34`）
- 目录：`/home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent`
- 分支：`20260727`
- 端口：`47313`

```bash
ssh company-server
cd /home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent
bash scripts/deploy_server.sh
```

脚本执行 `git pull --ff-only`、Python 契约测试、依赖同步、服务重启和 HTTP 健康检查。若服务器目录尚无 Git 元数据，只在首次迁移时执行：

```bash
cd /home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent
git init
git remote add origin https://github.com/tianzj890107/ontology-agent.git
git fetch origin 20260727
git update-ref refs/heads/20260727 refs/remotes/origin/20260727
git symbolic-ref HEAD refs/heads/20260727
git restore --source=origin/20260727 --staged --worktree .
bash scripts/deploy_server.sh
```

## 独立通用建模服务

独立服务使用新端口 `47314`，与现有工作台 `47313` 并行，使用独立的
`open-claude/sandbox/standalone-modeling-runs/` 运行根目录，不读取或修改现有
`sandbox/<project>/tasks/` 任务状态。服务器上使用：

```bash
cd /home/data/zhangzhen_home/zhangzhen/ontology/ontology-agent
nohup bash scripts/run_standalone_modeling.sh > ontology-agent-47314.log 2>&1 &
```

脚本会首次生成权限为 `600` 的 `.standalone-modeling-api-key`，并将独立服务绑定到
`0.0.0.0:47314`。`/health` 为公开健康检查，其余接口使用
`X-Modeling-API-Key`。API 说明见
[`API/standalone-modeling-api.md`](API/standalone-modeling-api.md)。

独立服务停止或重启不会停止 47313；47313 的部署仍只使用
`scripts/deploy_server.sh`。

初始化与更新都保留 Git 忽略的服务器配置和运行数据。部署前不得删除 `.env`、`.venv` 或 `open-claude/sandbox/`。

47313 和 47314 共用仓库根目录的 `.venv`。`scripts/ensure_agent_venv.sh` 在服务启动/部署时一次性创建并安装依赖，随后 Sandbox 以只读方式挂载该环境并将其放入 `PATH`；单个 Agent run 不得创建新的 venv 或执行 pip 安装，任务目录只保存本任务文件。
