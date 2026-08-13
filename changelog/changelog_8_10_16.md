# 20260810–20260816 分支变更记录

> 本文档记录 `20260727` 分支在 2026-08-10 至 2026-08-16 的变更。

## 维护规则

- 每次功能修改后，在本周记录中追加用户可见变化和主要文件。
- 服务器目录：`/home/zhangzhen/ontology/ontology-agent`；分支：`20260727`；Agent 端口：`47313`。
- 本周结束后，将本文件归档为对应日期范围，并新建下一周的变更记录。

## 2026-08-10

### 1. 文件目录箭头垂直对齐

- 文件目录折叠和展开箭头改用统一尺寸的 SVG 图标，固定在目录标题行中垂直居中。
- 折叠与展开状态的箭头保持同一位置，不再受文字基线影响产生上下偏移。
- 已完成前端构建和 12 项契约测试，最新静态产物已部署到服务器。
- 主要文件：`frontend/src/main.jsx`、`frontend/src/styles.css`、`frontend/dist/`、`tests/test_frontend_contract.py`。

### 2. 本体元模型与输出模板切换到版本 3

- 建模任务固定参考文件切换为 `本体元模型3.xlsx`、`本体元模型模板3.xlsx`。
- 逻辑实体和业务属性结果按模板 3 输出，所有布尔字段统一使用 `Y/N`；每个业务对象只能有一个 `是否主逻辑实体=Y`，`是否唯一`按业务上的唯一标识判断。
- 当前暂不生成维度输出，`是否层级编码`、`是否层级名称`统一填 `N`；逻辑实体映射和业务属性映射仅作为参考输入，不进入结果文件。
- 实体关系结果严格按模板 3 的 16 列输出，不生成模板外的关系分类编码等字段。
- 服务端增加布尔字段和主逻辑实体唯一性的上传前校验；已完成知识文件生成、21 项全量测试和前端生产构建，并已同步部署。
- 主要文件：`scripts/build_agent_knowledge.py`、`open-claude/oc_codex_server.py`、`agent_knowledge/`、`rules/本体元模型3.xlsx`、`rules/本体元模型模板3.xlsx`、`tests/test_ontology_knowledge.py`。

## 2026-08-11

### 3. 本体任务继续执行与任务复用逻辑修复

- 本体平台任务模式隐藏“+ 新会话”，后端对同一 `repositoryId + taskCode + user` 做幂等复用，始终在原任务会话上继续操作。
- 已确认完成的任务重新输入执行指令或上传新结果时，会先删除旧结果对象、回写 `RUNNING`，再继续当前任务，不再被错误拦截。
- 失败任务不再显示“完成”按钮，仍可在原会话中重新执行；成功任务的历史会话和文件面板支持继续上传与建模。
- 已补充任务复用、旧结果清理和状态恢复回归校验；完成 21 项后端/前端契约测试和前端生产构建。
- 主要文件：`open-claude/oc_codex_server.py`、`frontend/src/main.jsx`、`frontend/dist/`、`tests/test_frontend_contract.py`、`tests/test_ontology_knowledge.py`。

### 4. 旧 ontology 工作区与会话数据迁移

- 将旧目录 `/home/wugefei/ontology/ontology-agent` 中的本体工作区、任务输入输出、任务状态文件、`bi_agent` 和兼容包完整合并到 `/home/zhangzhen/ontology/ontology-agent`。
- 迁移 35 条任务记录、27 条可回放会话及对应 transcript；8 条旧任务本身没有历史日志或 transcript，确认不是迁移遗漏。
- 保留当前修复后的代码和重新创建的 `.venv`，不复用旧虚拟环境；旧 macOS `._*` 元数据和未被新构建引用的历史前端静态产物不迁移。
- 已保留迁移前备份：`/home/zhangzhen/ontology/.backup-before-history-migration-20260811`；服务器测试 21 项通过，服务健康检查返回 200。
