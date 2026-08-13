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
- 目录：`/home/zhangzhen/ontology/ontology-agent`
- 分支：`20260727`
- 端口：`47313`

```bash
ssh company-server
cd /home/zhangzhen/ontology/ontology-agent
bash scripts/deploy_server.sh
```

脚本执行 `git pull --ff-only`、Python 契约测试、依赖同步、服务重启和 HTTP 健康检查。若服务器目录尚无 Git 元数据，只在首次迁移时执行：

```bash
cd /home/zhangzhen/ontology/ontology-agent
git init
git remote add origin https://github.com/tianzj890107/ontology-agent.git
git fetch origin 20260727
git update-ref refs/heads/20260727 refs/remotes/origin/20260727
git symbolic-ref HEAD refs/heads/20260727
git restore --source=origin/20260727 --staged --worktree .
bash scripts/deploy_server.sh
```

初始化与更新都保留 Git 忽略的服务器配置和运行数据。部署前不得删除 `.env`、`.venv` 或 `open-claude/sandbox/`。
