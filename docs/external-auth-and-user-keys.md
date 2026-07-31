# 外部登录态与用户级模型 Key

Agent 不负责账号登录。外部本体平台登录后，应在打开 `/mission` 或 `/merge` 时携带：

```http
Authorization: Bearer <平台签发的 HS256 JWT>
```

服务器设置同一份 `ONTOLOGY_JWT_SECRET` 后，会从 JWT 的 `sub`（也兼容 `user_id`、`uid`）得到用户 ID。首次成功访问时，Agent 写入签名的 HttpOnly Cookie，浏览器后续同源请求可直接沿用登录态。

如果平台已经由反向代理完成 JWT 校验，也可以设置 `ONTOLOGY_TRUST_PROXY_AUTH=true`，由代理传递：

```http
X-User-Id: <平台用户 ID>
```

这时 Agent 不保存 JWT 原文，只保存用户 ID。没有有效身份的 API 请求返回 HTTP 401。

## 用户 Key

- `POST /api/apikey` 只写当前用户自己的 Provider Key。
- Key 保存在服务器 `~/.claude/ontology-agent-user-keys.json`，文件权限为 600。
- 任务执行时按任务归属用户解析 Key，并显式传给模型客户端。
- 当 `LLM_PROVIDER=team` 时，团队网关的 `TEAM_API_KEY` 是所有已认证用户的共享默认 Key；用户自己的同 Provider Key 仍优先于共享 Key。
- 其他 Provider 的 `.env` 默认 Key 仍只允许管理员身份使用，普通用户需要配置自己的 Key。
- `POST /api/admin/apikey` 只有 `ONTOLOGY_ADMIN_USER_IDS` 中的用户可调用，用于维护服务器默认 Key。
- 普通用户没有个人 Key 且当前不是团队网关时，模型调用会在发出请求前被拒绝。

## 用户模型和额度

模型选择保存在 `~/.claude/ontology-agent-user-settings.json`，任务和历史会话按用户隔离。调用次数、Token 和估算费用保存在 `~/.claude/ontology-agent-user-usage.json`，默认团队测试上限较高，不在普通页面展示，可通过 `.env` 调整。

真实 JWT Secret、Provider Key 不应提交到 Git；只放服务器 `.env` 或受控配置中。
