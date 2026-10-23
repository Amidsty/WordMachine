# 人工调整 Rating（2B / 0012）

此批在 2A 比赛事件链之上加入人工调分。入口：**管理 → 用户管理 → 调整 Rating / 流水**。这是本地源码交付，不代表已推送、已迁移现有实例或已生产部署。

## 使用与权限

- Lv.4/5 可调整自己或严格下级的活动账号；不比较双方 Rating 高低。不能调整同级的其他账号、上级或封禁账号。
- 输入的是**新的绝对 Rating**，不是增减量。范围为有符号 INT：−2147483648…2147483647；相同数值拒绝，不产生空调整。
- 必须填写 1–500 字原因，审查当前余额和事件头，并在独立确认步骤输入**操作者本人当前密码**。
- 目标正在进行任何对局时拒绝调分，包括旧 JSON 参赛模式；等待局不阻止调分，后续开局使用已提交余额。
- 调分不修改旧 Perf、比赛结果、比赛次数、旧 JSON，不撤销会话，也不调用比赛 Rating 公式。
- 只有有权调整该账号的管理员可通过此入口查看统一流水及人工原因。公开比赛历史不插入伪造的人工 game_id。
- 最近 50 条统一事件按账户序号倒序显示；读取仍验证完整账户链，升级前历史不补造成新事件。

## API

`GET /api/admin/user/<id>/rating` 返回审查视图：

- `user_id`、`rating`
- `rating_event_id`：正 BIGINT 的十进制**字符串**，无事件时为 null；不通过 JS Number 转换
- `running_game`
- `events`：最近 50 条，含 kind（game/manual）、序号、before/delta/after、时间；比赛含 game_id，人工含 actor_id/reason

`POST /api/admin/user/<id>/rating` 仅接受：

```json
{
  "request_id": "12345678-1234-4234-8234-123456789abc",
  "expected_rating": 1500,
  "expected_event_id": null,
  "new_rating": 1700,
  "reason": "经审核的调整原因",
  "current_password": "操作者本人当前密码"
}
```

UUID 只是格式示例，不可照抄复用。新意图用安全随机 UUIDv4；原请求重试保留相同 UUID、操作者、目标、新余额、规范化原因和审查版本。身份始终取会话，不接受 actor_id 等额外字段。

响应包含 request_id、user_id、rating_before/delta/rating_after、字符串 rating_event_id。余额版本变化（即使数值后来又回到原值）返回 `stale_rating` / 409，必须重新审查；进行中返回 `rating_game_running` / 409。权限、密码和 CSRF 失败不写调分数据。

## 幂等、密码和确认丢失

- `(actor_id, request_id)` 唯一预留；指纹绑定规范化业务意图和目标。换业务载荷返回 `request_id_conflict` / 409。
- 密码不写入指纹、请求回执、来源记录或审计，也不放 localStorage。重试可以重新输入本人当前密码，不改变业务意图。
- 每次提交（包括成功回执重放）都在用户锁内复验当前权限、双方状态及本人密码；已经失权者不能凭旧 UUID 绕过权限。
- 成功重放返回原回执，不追加流水、不重新调整余额；原回执显示的是当次结果，不保证仍是当前余额。
- 前端不自动重发。10 秒未确认停止等待，不代表数据库回滚；原意图留在当前弹窗，可手动重试。关闭/刷新会失去本页重试信息，须先核对状态。
- 放弃原请求并重新审查不撤销已提交的操作。只有再次填写、审查并确认，才发送新意图。
- 独立 MySQL 限流桶：每操作者默认 10 次/300 秒（`WM_RATING_ADJUST_LIMIT`、`WM_AUTH_LIMIT_WINDOW`），来源 IP 另用 `WM_LOGIN_IP_LIMIT` 阈值（默认 30），桶与登录分开。失败及重试也计数；限流在独立事务提交，不因密码失败回滚，返回 429 / Retry-After。

## 数据与锁协议

新增 `rating_adjustment_request` 与 `manual_rating`。`rating_event` 新增可空 manual_rating_id，game_rating_id 改为可空；CHECK 保证 game/legacy-v1 和 manual/manual-v1 各有且只有对应来源。人工来源有目标/操作者/请求/最近比赛来源 FK、算术和等级/原因 CHECK，事件通过复合 FK 绑定同一用户的人工来源。

一次调分的请求预留、人工来源、事件、余额/事件头、admin_audit 与回执**同事务提交**；失败整体回滚。manual 来源保存 actor_level、before/delta/after、原因和时间；delta 为 BIGINT，支持 INT 两端相减。

锁序：**请求预留 → actor/target 升序用户排他锁 → 当前权限/密码/审查版本 → 非锁定运行中对局读取 → 完整链核对 → 写入**。

- 请求预留无 actor FK，避免在正式升序锁之前取得用户共享锁。
- 首次 MVCC 一致性读必须在用户锁之后，不能提前建立旧快照。
- 开局、答题、结束/结算也先取得相关用户排他锁。先开局则调分看到 RUNNING 并拒绝；先调分则开局等待后使用新余额；结算先提交则旧审查版本失效。
- 调分不取得 game 行锁，避免 user→game 与既有 game→user 锁序形成死锁。
- 运行中参赛记录损坏时拒绝而不猜测；当前会批量检查运行中对局，包括旧 JSON。尚未作生产规模/容量验收。
- `rating_ledger_id` 始终只投影最近比赛来源，人工事件不改它。历史不能再把“最近比赛结束余额”误当当前账户余额；人工事件在统一链中衔接差额，比赛历史仍按原来源读取。
- 完整历史/审查/只读审计检查所有人工来源覆盖，包括 NULL 事件头和孤立来源；结算热路径保留头及直接关联的主键当前读，不扫描全部历史。
- 应用只追加来源/事件，但不宣称抵御拥有数据库写权限者同时伪造全部事实、指针和审计。

## 迁移与当前本机边界

新增唯一 head：`0012_manual_rating`，不改写已交付的 0001–0011。预先拒绝部分/自定义结构、冲突约束及不符合要求的依赖表；DDL 等待限于本连接最多 30 秒。旧事件各字段、旧余额、比赛来源和历史保持原值，新人工来源列为 NULL，不回填人工事件。

对明确授权、停止旧写入者、已备份并在隔离副本演练过的数据库，使用迁移账号执行：

```bash
python -m alembic upgrade 0012_manual_rating
```

MySQL DDL 隐式提交；失败先检查实际结构，不能盲目重跑、stamp head 或自动 downgrade。恢复需经过验证的备份及匹配应用；新旧代码不可同时写同一个库。其他连接配置见 [DATABASE.md](../DATABASE.md)。

**本批没有升级或清空用户本机数据库。** 已知本机实例仍为先前授权重建的 0011；新代码要求 0012，未升级时 readiness 为 503，普通启动不会迁移。不要用 `--init-local`、删库或重置 MASTER 解决版本差；本机实例升级须另行授权备份和保留数据迁移。

## 验证范围

测试使用新建、自动清理的合成 MySQL 库；不连接用户持久实例。覆盖完整等级矩阵、本人/下级、输入边界、当前密码/CSRF/限流、审查版本 ABA、重复/不同意图并发、审计失败回滚、SQL CHECK/FK/RESTRICT、既有数据迁移、部分结构拒绝、NULL 头孤立来源、人工/比赛交错链与旧比赛历史。

真实并发覆盖开局和结算分别先后取得用户锁，以及请求认证之后的降权、封禁、改密和目标提权；确认丢失用提交后丢弃响应验证，不把“请求未送达”冒充丢回执。

前端覆盖独立确认、整数输入、文本转义、重复点击、保留原请求、超时不自动重发、重新审查与跨账号迟到响应。另有实际 Flask/MySQL/Chromium 的调分、错密、提交后丢回执/原 UUID 重试及独立 SQL 核对。

### 本批最终结果

- 全量单元测试 **758 项通过**：`/tmp/wm-manual-unit-final.log`。
- 相关真实 MySQL **104 项单轮通过**（人工调分、事件链、原结算、管理员等级、封禁竞态）：`/tmp/wm-manual-mysql-confirmed.log`。随后补强待改动列的原类型/FK 预检，并扩展 0011 迁移验证；**6 项迁移复跑通过**（保留数据的两个分支，以及同名表、原来源类型/FK、约束冲突拒绝）：`/tmp/wm-manual-migration-final.log`。与前一轮有重叠，不累加冒充单轮结果。
- 全量前端 **223 项 / 18 文件通过**：`/tmp/wm-manual-frontend-final.log`；类型检查、ESLint、Prettier 和构建通过，构建日志 `/tmp/wm-manual-frontend-build.log`。
- **2 项真实 MySQL/Chromium 场景**（新增调分、既有管理员会话撤销）通过；与当时 2 项保留数据迁移分支合跑日志共 4 pytest：`/tmp/wm-manual-browser-final.log`，不能说成 4 个浏览器场景。
- **3 项模拟 API 管理浏览器回归**通过：`/tmp/wm-manual-browser-mock.log`；它们不代替真实 MySQL 授权/事务证明。
- **124 个 Python 文件**只读 Ruff lint/格式检查通过：`/tmp/wm-manual-static-final.log`。

初轮问题包括 MySQL SET 表达式类型不符合 lock_wait_timeout 要求（改为读取后绑定整数，发生在任何新 DDL 前），以及旧 head/能力/游标队列/按钮数量断言、TypeScript 字面量类型和浏览器多 alert 定位。已修复并复跑；未放宽权限/事务或删去竞态验证。初轮日志 `/tmp/wm-manual-mysql-first.log`、`/tmp/wm-manual-unit-first.log`、`/tmp/wm-manual-unit-all.log`、`/tmp/wm-manual-frontend-all-initial.log`、`/tmp/wm-manual-browser.log` 保留。

这不是新版本全量 MySQL/全浏览器/启动生命周期/生产容量验收，也没有托管 CI、GitHub 上传或用户持久库升级结果。
