# 0011 全量检查与 GitHub 交付记录

用户授权：全量检查当前版本，修复后推送 GitHub。检查在隔离工作树 `/tmp/wm-release-check-GSn3J5/tree/` 中进行；真实 MySQL 均由测试启动器建立独立 `wm_test_*` 数据库。未迁移用户现有库、重置账号、停止用户进程或覆盖运行实例前端。

## 检查中修复

1. **对局封禁在途竞态**：真实 MySQL 并发复现了 HTTP 身份验证后、写入前封禁，答题仍返回 200 的问题。现在创建/加入/离开/开始/取消/答题/结束均在用户锁内检查操作者仍为活动账号；成员操作按升序锁参与者及操作者，避免 actor-first 与其他对局结算倒置。答题/结算复用已有升序用户排他锁，不取消已封禁其他参与者的历史答案/合法结算。已完成 UUID 的原回执仍是过去结果重放，不会新计分。
   - 新增 8 项并发回归（7 类 HTTP 命令及 Socket 答题），确认封禁提交先于用户锁时，答案、局状态、余额、来源、事件及新回执均不写入。
   - 既有跨局 FK/结算锁顺序探针改在新的最早用户锁处观测，并明确断言 `[1,2,3]` 顺序，不放宽超时或删掉竞争验证。
2. **本地启动 SIGINT**：后台/nohup 父进程可能传下忽略 SIGINT 的状态；启动器现显式注册 SIGINT，确保与 SIGTERM 一样经过所属进程清理。原先启动烟测的 Ctrl+C 阶段确实超时，修复后两轮启动/重启通过。
3. **测试迁移兼容**：答案转换的合成旧局明确声明旧 Perf 模式和 NULL 倍率；SQL 插入改用显式旧字段列名，保留新原始增量未知。0008 索引往返测试固定 0007/0008、使用冻结的旧结构合成记录，而不是用当前业务 API 运行旧 schema；继续逐表精确核对会话、限流、答案、流水、回执及 NULL/额外历史不变。当前应用在这两个旧版本上均 readiness 503。
4. **测试协议/权限断言**：补最新 head、倍率/管理能力字段及明确等级；浏览器按一位 Perf 和管理员本人可编辑有限资料断言。伪造 owner/type 的词典创建现在明确断言 400，未取消权限拒绝测试。
5. 仅在严格隔离合成库的性能探针中清理本探针新建词典的审计子行；业务代码没有删除审计或直接改余额的捷径。运行辅助脚本的诊断不再指向精简仓库未交付的文档。

## 证据与口径

日志保留在 `/tmp/wm-release-check-GSn3J5/logs/`，不公开上传 Cookie/测试凭据/trace。

- `full-initial.log`：首轮 941 通过、21 失败、29 夹具错误。外层等待在 600 秒超时，但子测试随后完成；核对进程归属后仅停止本轮遗留的合成 MySQL，没有按历史 PID 停业务服务。
- `backend-fixes.log`：97 通过、2 失败，随后修复旧显式列名和残留 head 断言。
- `game-race-reproduction.log`：封禁竞态复现失败（实际返回 200，预期 403）；`game-race-fixed.log`：8 项通过。
- `full-final.log`：998 通过、1 失败，原因是旧锁顺序探针等待了已被前置排他锁挡住的 FK 阶段；`lock-order-fixed.log` 单项修复通过。
- `full-confirmed.log` / `.status`：最后完整重跑退出码 **0**，**999 项后端通过（675 unit + 324 真实 MySQL）、210 项前端测试通过**；全前端 ESLint/Prettier/类型及构建通过。没有跳过 MySQL，不把前面失败的日志冒充成功。
- `browser-mock-final.log`：14 项构建产物 + 模拟 API 的 Chromium 测试通过。
- `browser-real-final.log`：6 个 pytest 编排 / 7 个真实 MySQL Chromium 场景通过，涵盖自然到期、真实限流、HTTP/Socket 对局及丢确认重试、账号会话撤销和词典/CSV 权限。
- `startup-final.log`：1 个独立生命周期编排通过，包含两次启动、一次应用/数据库重启、原 Cookie/UUID 回执、数据一致及 SIGTERM/Ctrl+C 清理。
- `performance-smoke.log`：1 项烟测通过，34 个列表场景、每场景 1 次预热/1 次测量及合成写探针；原始摘要、SQL/计划、环境和样本为 `list-smoke.json`。这不是稳定性能比较、p95/p99 或生产 SLA。
- `export-build.log`、`export-python-install.log`：精简副本干净 npm 安装/类型/构建、独立仅运行依赖 Python 环境及 pip check；不等于 CVE 全面审计。
- `export-runtime-smoke.log`：在精简副本、独立运行环境和真实临时 MySQL 中验证空库迁移、MASTER/登录/CSRF、倍率归属/冻结、HTTP+Socket 评分和原 UUID 回执、事件链、等级修改/撤会话、只读审计及前端 shell。
- 最后只读 Ruff lint/格式检查覆盖 119 个 Python 文件；更新脚本诊断文案后另有 22 项启动器/隔离工具单元回归通过。

## 最终回执及公开范围修正

已提交 [PR #3](https://github.com/WordMachine/Word2Machine/pull/3)，状态 OPEN，未自动合并，默认分支未改动。

- 初次提交 `ec1c1b6edeb20c0cad9ae2597d5f2da1b2537782` 曾包含本机启动辅助工具。
- 用户随后明确要求不提交本地相关/不通用内容。后续提交 **`069fc73d20af1b2d7a74f2531c5ad86f5db1ffc8`** 已从 PR 当前版本移除 `.sh`、`scripts/local_dev.py`、`scripts/with_test_mysql.py`、`.python-version`，清理公开 README 和 PR 说明。当前公开树 **125 文件**；本地工作区的辅助工具保留，未来不得再次导出。
- `portable-build.log` 与 `portable-runtime-smoke.log`：移除后的独立精简副本构建、真实 MySQL/仅运行依赖冒烟通过。运行源码没有引用已删工具。
- 未 force push 或改写已推送历史，因此初次提交仍在 PR 历史中；不能宣称这些文件从未上传。此次移除不涉及真实凭据或数据（原本就未上传）。

## GitHub 边界（最初交付记录，当前范围以上述修正为准）

独立 clone：`/tmp/wm-release-check-GSn3J5/repo`，基于 `d238a1d2012114ada5fec8245afd0ed5637eddc4`；目标 `WordMachine/Word2Machine`，分支 `upload/admin-rating-multipliers`。提交/PR 以最后成功回执记录为准，未通过最终检查前不推送。

白名单 130 文件：运行/构建/迁移源码、配置示例、清单/锁、启动脚本和独立精简 README。排除完整 docs/PLAN/tests/CI、真实配置/数据库/报告/日志/缓存/venv/node_modules/产物。已有 0001–0008 与远端逐字节相同；新增 0009–0011，未改写历史迁移。检查白名单及 SHA256，并做窄范围凭据模式检查，不能称为形式化的无秘密证明；README 原署名保留。

不直接改默认分支、不自动合并、不 force push；精简仓库没有托管 CI 验证结果。本轮仅本机单进程 Chromium/合成数据库正确性验证，不代替真实旧库恢复演练、生产并发容量、多浏览器或跨 worker 撤销方案验收。实际数据库升级、MASTER 初始化及部署仍须另行授权。
