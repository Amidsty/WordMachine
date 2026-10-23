# 数据库从 0011 升级到 0012

本文仅说明：

```text
0011_dictionary_multipliers → 0012_manual_rating
```

升级目标是加入人工 Rating 调整所需的数据库结构，**保留全部现有账号、密码、会话、词典、单词、对局、Rating 和历史记录**。不是清空重建，不需要重新创建 MASTER。

本文不包含真实凭据或开发者本机路径。命令中的数据库名、账号、地址和备份路径都是示例，必须核对后替换。已经是 0012 的实例无需重复执行升级。

## 1. 本次升级改变什么

迁移源码：`migrations/versions/0012_manual_rating.py`。

| 对象 | 变化 |
| --- | --- |
| `rating_adjustment_request` | 新增表，保存人工调分的请求指纹与成功回执 |
| `manual_rating` | 新增表，保存操作者、目标、原因、调整前后余额及差额等来源事实 |
| `rating_event.manual_rating_id` | 新增可空列；所有旧事件此列均为 NULL |
| `rating_event.game_rating_id` | 原 BIGINT 列允许 NULL，以支持没有比赛来源的人工事件 |
| `rating_event` 的约束 | 增加人工来源唯一约束与同用户复合外键；来源 CHECK 区分比赛与人工事件 |
| `alembic_version` | 更新为 `0012_manual_rating` |

以下内容**不会**由迁移改变：

- 网站账号的用户名、密码哈希、管理员等级、封禁状态。
- 数据库连接账号、密码、权限及应用密钥。
- 现有会话记录；迁移不主动撤销会话，但停机期间自然到期的会话不会被延长。
- 当前 Rating、原事件字段、比赛评分来源、Perf、倍率快照、旧 JSON 和其他业务数据。

迁移本身不会生成任何人工调分记录。新增两张表应为空；只有升级后经过授权的调分操作才会写入它们。

## 2. 升级前条件

- MySQL **8.0.16+ / InnoDB**；不支持 MariaDB、SQLite 或离线 SQL 生成。
- 使用包含完整迁移链和 0012 功能的匹配代码，已安装 Python 依赖。
- 目标库当前版本必须是 `0011_dictionary_multipliers`，且没有残留的 0012 部分结构。
- 已明确授权本次升级，已安排维护窗口，并停止所有应用写入者，包括旧进程、后台任务和其他 worker。
- 已完成可恢复备份，并在独立副本上验证恢复与升级。
- 使用专用迁移账号；正常运行账号仍只保留业务库的 SELECT、INSERT、UPDATE、DELETE 权限。

**不要在生产/业务库上试错，也不要让旧代码与新代码同时写同一个库。**

## 3. 确认连接目标和原版本

连接参数来自 `WM_DB_HOST`、`WM_DB_PORT`、`WM_DB_NAME`、`WM_DB_USER`、`WM_DB_PASSWORD`。应用和 Alembic 不会自动加载 `.env`；完整说明见 [DATABASE.md](DATABASE.md)。

先用 MySQL 客户端连接，密码使用交互提示，不写在命令行中：

```bash
mysql --host=127.0.0.1 --port=3306 --user=wm_migrate --password wordmachine
```

执行只读检查：

```sql
SELECT DATABASE(), CURRENT_USER(), VERSION(), @@hostname, @@port;
SELECT version_num FROM alembic_version;
SHOW TABLES;
SHOW CREATE TABLE rating_event;
```

确认连接的是**预期实例和数据库**。版本处理规则：

- `0011_dictionary_multipliers`：继续审查本次升级。
- `0012_manual_rating`：不要重复升级；转到验收部分。
- 其他版本、没有版本表、版本表多行：停止，先审查实际迁移路径，不手工修改版本号。

0011 下不应已有 `manual_rating`、`rating_adjustment_request` 或 `rating_event.manual_rating_id`。若已有其中一部分，可能是先前 DDL 中断或自定义结构，**不能直接重跑或把它当作成功升级**。

可在项目目录检查本地源码迁移链：

```bash
python -m alembic heads
```

本功能批次的 head 为 `0012_manual_rating`。执行时仍明确指定 0012，不使用 `upgrade head` 顺带执行未来未审查的迁移。

## 4. 备份并验证恢复

### 必须保留的内容

1. 业务库的全部结构和数据，包括会话、审计、命令回执与所有历史表，不能只备份 `user` 表。
2. 原应用的匹配源码版本和依赖清单。
3. 原配置、稳定应用密钥和必要数据库账号/权限信息，私下妥善保存。

备份包含账号数据、会话令牌摘要、密码哈希，配置备份可能包含明文连接密码。必须放在受限目录，不提交 GitHub、不发送到聊天或公开日志。

### 备份方式

可以使用已经验证的逻辑备份方案，或 MySQL **干净停机后的完整物理备份**。不要直接复制运行中的数据目录冒充可恢复备份。

下面是逻辑导出的示例，需有匹配的 MySQL 客户端和经过审核的备份权限：

```bash
mysqldump --host=127.0.0.1 --port=3306 --user=wm_migrate --password --single-transaction --quick --no-tablespaces --set-gtid-purged=OFF --hex-blob --routines --events --triggers --default-character-set=utf8mb4 --result-file=PRIVATE_BACKUP_PATH/wordmachine-0011.sql wordmachine
```

注意：

- 先建立私有备份目录并替换 `PRIVATE_BACKUP_PATH`；确认文件不覆盖已有有效备份。
- 使用 `--result-file`，避免部分 Windows PowerShell 的重定向编码改变 SQL 文件。
- `--single-transaction` 适用于 InnoDB 数据一致性，不意味着可以同时进行 DDL；这里仍要求维护停写。
- 存储例程等对象可能需要额外的专用备份权限。备份因权限或其他错误失败时应停止，由管理员审核处理，不能删减备份范围来“通过”。
- 此导出针对指定业务库，不包含 MySQL 系统账号/全局权限，也不包含应用配置；这些需另行安全保管。
- 自定义视图、触发器、例程、事件或外置表空间需要额外审查，不应假定标准项目步骤已覆盖。

### 恢复演练与数据核对

在**独立且不对外提供服务的 MySQL 实例**恢复备份，不向原库导入覆盖：

1. 核对备份文件校验值，完成真实恢复。
2. 确认恢复后版本仍为 0011。
3. 比较所有业务表的结构、行数及按主键排序的完整行内容/摘要。只比较行数不足以证明密码、余额和历史未改变。
4. 把迁移配置明确指向该副本，先执行下一节的 0012 升级。
5. 在副本上完成第 6 节验收，成功后才安排原库升级。

物理备份需匹配 MySQL 版本及完整实例文件，恢复副本必须使用自己的数据目录、socket/端口。不要复用正在运行的实例目录。

## 5. 执行显式升级

以下命令在项目目录、已激活的 Python 环境中执行。确认 `WM_DB_*` 指向本次已授权的目标库，运行配置中的应用密钥保持原值。

### Linux / macOS：Bash

已经加载正常运行配置后，在子 shell 中临时切换迁移账号；退出后外层环境仍是原运行账号：

```bash
(
  export WM_DB_USER=wm_migrate
  read -r -s -p '请输入 MySQL 迁移账号密码: ' WM_DB_PASSWORD
  printf '\n'
  export WM_DB_PASSWORD
  python -m alembic upgrade 0012_manual_rating
)
```

这里使用 Bash 的 `read` 语法；macOS 默认 zsh 用户应先进入 Bash。必须查看命令退出状态及日志，失败后不要继续启动服务。

### Windows PowerShell

已设置正确的运行环境变量后：

```powershell
$runtimeUser = $env:WM_DB_USER
$runtimePassword = $env:WM_DB_PASSWORD
try {
  $env:WM_DB_USER = 'wm_migrate'
  $env:WM_DB_PASSWORD = [System.Net.NetworkCredential]::new(
    '', (Read-Host '请输入 MySQL 迁移账号密码' -AsSecureString)
  ).Password
  python -m alembic upgrade 0012_manual_rating
  if ($LASTEXITCODE -ne 0) {
    throw '迁移失败，请停止并审查实际结构，不要盲目重试。'
  }
} finally {
  $env:WM_DB_USER = $runtimeUser
  $env:WM_DB_PASSWORD = $runtimePassword
  Remove-Variable runtimeUser, runtimePassword
}
```

这些命令不会自动选择开发者本机启动器管理的私有数据库。若使用独立启动器，必须按该实例的配置和生命周期管理方式另行审查升级；不能修改业务 `.env` 后就假定连接到了它。

## 6. 升级后的验收

仍保持维护停写，先执行只读检查：

```sql
SELECT version_num FROM alembic_version;
SHOW CREATE TABLE rating_event;
SHOW CREATE TABLE manual_rating;
SHOW CREATE TABLE rating_adjustment_request;

SELECT COUNT(*) AS manual_sources FROM manual_rating;
SELECT COUNT(*) AS adjustment_requests FROM rating_adjustment_request;
SELECT COUNT(*) AS events_with_manual_source
FROM rating_event WHERE manual_rating_id IS NOT NULL;
```

刚完成迁移、尚无业务调分时：

- 版本应为 `0012_manual_rating`。
- 上述三个计数应全部为 0。
- `rating_event.game_rating_id` 仍为有符号 BIGINT，只改变为可空；新 `manual_rating_id` 可空。
- 事件来源 CHECK、人工来源唯一约束和同用户复合外键应与迁移源码一致。不能只看版本号就认为结构正确。

再与升级前记录比较：

- 所有原业务表的行数与原有列值一致，唯一预期数据变化是 `alembic_version`。
- 比较 `rating_event` 时只投影原列；单独确认新增列全部为 NULL。
- `user.pwhash`、`rating`、`admin_level`、全部会话、历史 JSON、比赛来源和旧事件均应保持原值。
- 除 `rating_event` 的预期结构变化外，原业务表结构不应改变。
- 应用配置、数据库凭据和权限不应被重置或扩大。

用**运行账号**做只读审计：

```bash
python -m flask --app app audit-legacy
```

审计有问题时停止恢复业务，不自动修复或重算历史。需要保存审计输出时，只放私有文件。

同步构建匹配前端并按既有方式启动应用：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

Windows PowerShell 如有需要可使用 `npm.cmd`。不要为了升级数据库而重新生成应用密钥、重置密码或执行 `create-master`。

最后确认：

- `/health/ready` 返回 **200**，响应为 `{"status":"ok"}`。
- 登录页和前端资源正常，原账号仍可登录。
- Lv.4/5 在“管理 → 用户管理”可看到“调整 Rating / 流水”；普通用户没有管理入口，低等级管理员没有调分能力。
- 运行账号仍无 CREATE、ALTER、DROP 等 DDL 权限。

不要在真实账号上随意改分来做冒烟测试；实际写入验证应在隔离副本或合成测试库中进行。

## 7. 失败处理与恢复边界

**MySQL DDL 会隐式提交。命令报错、断线或中断，不代表所有结构变化已回滚。** 0012 包含多个 DDL 步骤，可能留下部分新表或列。

遇到失败：

1. 保持停写，保存私有诊断日志、退出状态和当前版本。
2. 只读检查实际表、列、约束，区分连接/权限错误、等待超时及已发生的部分 DDL。
3. 不直接再次运行升级，不手工填充 `alembic_version`，不执行 `stamp head`。
4. 不删除新表来掩盖失败；不清空用户、重建数据库或重新初始化 MASTER。
5. 由维护人员基于实际状态审查处理，或在明确授权下恢复已验证的备份及匹配的旧应用。

本迁移故意拒绝自动 downgrade。特别是在 0012 已经发生人工调分之后，回退到升级前备份会丢失之后的业务写入，不能把它当成无损撤销。

## 8. 功能启用后的规则

- Lv.4/5 可调整自己或严格下级的活动账号，填写原因并验证本人当前密码。
- 输入新的绝对 Rating；目标正在进行对局时禁止调整。
- 人工来源、事件、余额、审计与成功回执同事务提交。
- 超时不等于回滚；手动重试保留原请求 UUID、目标、数值、原因及审查版本，不自动重复写入。
- 人工事件不伪造比赛 ID，也不修改旧比赛 Perf、评分结果或比赛次数。

升级仅使数据库具备这些能力，不会替操作者自动调整任何 Rating。
