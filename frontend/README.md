# Ontology Agent Workbench

`frontend/` 是 Agent 工作台的 React + Vite 前端，使用 Ant Design 和 Ant Design X。后端仍由 `open-claude/oc_codex_server.py` 提供 API 与 SSE；生产页面由服务端读取 `frontend/dist`。

## 本地开发

```bash
npm install
npm run dev
```

Vite 开发服务器只负责前端热更新；完整任务接口请启动仓库的 Python 服务，并按需要配置 Vite proxy 或直接执行生产构建：

```bash
npm run build
source ../.venv/bin/activate
python ../open-claude/oc_codex_server.py --host 127.0.0.1 --port 47313
```

构建产物 `dist/` 会随版本提交，保证没有 Node 环境的 Python 服务也能直接提供新页面。服务端只提供 `dist/index.html` 和 Vite 生成的 `/assets/*`；如果构建产物缺失，服务会明确返回构建错误，不会回退到旧的静态页面。
