# Git 双远端镜像工作流

## 远端映射

| Remote | Repository | Target branch | Purpose |
| --- | --- | --- | --- |
| origin | tianzj890107/ontology-agent | 20260727 | 主协作仓库 |
| personal | zhenzhang0408/ontology-agent | main | 个人私有镜像与版本归档 |

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
git remote add personal git@github.com:zhenzhang0408/ontology-agent.git
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

## GitHub Release 双仓库发布

GitHub Release 是独立于 push、tag 和服务器部署的授权动作。用户在当前任务明确授权创建某版本 Release 时，必须同时在两个 GitHub 仓库发布同一个版本：

| Repo | Repository | Release tag |
| --- | --- | --- |
| origin | tianzj890107/ontology-agent | vX.Y.Z |
| personal | zhenzhang0408/ontology-agent | vX.Y.Z |

规则：

- 两个 Release 必须绑定同名、同一个 immutable annotated tag（两个仓库的 tag object hash 与 peeled commit 完全一致）；
- 两个 Release 的标题、正文、draft、prerelease 状态必须一致；
- 幂等执行：已存在且符合要求的 Release 复用并验收，不重复创建；一个存在、另一个缺失时只创建缺失的那个；
- 任一仓库失败：报告部分成功，保留已成功 Release，不删除、不重建，修复权限或网络后只重试缺失仓库；
- 禁止为了补齐 Release 移动 tag、重新打 tag、`git push --tags` 或 force push；
- 禁止只发布一个仓库后宣称双发布完成；
- GitHub Release 不触发服务器部署；没有额外部署授权时，Release 完成后任务结束；
- `v0.1.1` 未定版前不得创建 `v0.1.1` tag 或 Release。
