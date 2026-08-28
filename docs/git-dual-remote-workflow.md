# Git 双远端镜像工作流

## 远端映射

| Remote | Repository | Target branch | Purpose |
| --- | --- | --- | --- |
| origin | tianzj890107/ontology-agent | 20260727 | 主协作仓库 |
| personal | zhenzhan0408/ontology-agent | main | 个人私有镜像与版本归档 |

## 完成标准

```
HEAD == origin/20260727 == personal/main
```

## 日常流程

1. 修改
2. 测试
3. `git diff --check`
4. `git commit`
5. `python scripts/push_dual_remotes.py`
6. 验证两个远端 hash 与本地 HEAD 一致
7. 没有部署授权时结束

## 首次设置

```bash
git remote add personal git@github.com:zhenzhan0408/ontology-agent.git
```

个人仓库必须是 GitHub Private 仓库；初始化时不添加 README/.gitignore/License，不创建 fork、不启用 Pages 或部署流程。

## 安全规则

- `personal` 必须是 Private；
- `personal/main` 不允许独立提交，只允许与 `origin` 开发分支保存同一个 commit；
- 禁止 force push（含 `--force-with-lease`）；
- 不自动 merge 或 rebase；
- 不自动推 tag；
- push 不代表部署；
- 双远端失败处理：
  - `origin` 成功、`personal` 失败：报告部分成功，保留已有 `origin` push，修复权限或网络后以相同 HEAD 重试，不生成补偿 commit；
  - 个人远端或原远端出现独有提交：停止处理并报告，不覆盖。
- 完成前先运行 `python scripts/push_dual_remotes.py --check` 检查配置与三个 hash。

## 正式版本

只有用户明确要求创建正式版本时，才执行：

```bash
git push origin vX.Y.Z
git push personal vX.Y.Z
```

GitHub Release 是否创建由用户在当前任务中明确要求；不要把真实访问 token、SSH 私钥或凭据写入文档。
