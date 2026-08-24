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
