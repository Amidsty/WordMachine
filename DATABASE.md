# 数据库配置说明

本文适用于手工配置数据库并启动 WordMachine 的方式，Linux、macOS 和 Windows 均可参考。不包含开发者本机专用脚本、目录或真实凭据。

**应用读取进程环境变量，不会自动加载 `.env`，也不会在启动时建库、迁移或重置账号。** 独立本地启动器若使用自己的私有配置，则不属于本文的环境变量配置方式，不能靠修改 `.env` 切换它的数据库。

## 1. 环境要求

- MySQL **8.0.16 或以上**，使用 InnoDB；不支持 MariaDB、SQLite。
- 数据库和连接字符集使用 `utf8mb4`。
- Python 3.10+，推荐 3.11；在项目虚拟环境中安装 `requirements.txt`。
- 数据库服务需要独立安装并启动。安装 Python 依赖并不会安装或启动 MySQL。

后端连接使用 PyMySQL；迁移使用 Alembic。两者都读取同一组 `WM_DB_*` 变量，不使用 `DATABASE_URL`，也不靠修改 `alembic.ini` 中的连接地址配置数据库。

## 2. 创建专用数据库和账号

由数据库管理员在受控的 MySQL 管理会话中执行。以下示例使用数据库 `wordmachine`，应用与数据库位于同一台机器，通过 `127.0.0.1` 连接。

**仅用于新数据库/新账号。** 如果同名对象已经存在，先核实用途和权限；不要为了执行示例而删除旧库、覆盖密码或清空数据。

```sql
CREATE DATABASE wordmachine
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

-- 正常运行账号：只允许读写业务数据，不授予建表、改表或删表权限。
CREATE USER 'wm_app'@'127.0.0.1'
  IDENTIFIED BY '替换为运行账号的独立强密码';
GRANT SELECT, INSERT, UPDATE, DELETE
  ON wordmachine.* TO 'wm_app'@'127.0.0.1';

-- 迁移账号：仅在显式初始化/升级时使用，权限限定在这个专用库。
CREATE USER 'wm_migrate'@'127.0.0.1'
  IDENTIFIED BY '替换为迁移账号的另一组强密码';
GRANT ALL PRIVILEGES
  ON wordmachine.* TO 'wm_migrate'@'127.0.0.1';
```

说明：

- 上面的密码是占位文字，必须替换；两个账号不要共用密码。
- 不给应用账号全局权限、`GRANT OPTION` 或 root 权限。迁移账号也不需要全局 `*.*` 权限。
- `wm_app` 是 **MySQL 连接账号**，不是网站管理员；网站 MASTER 要在迁移完成后单独创建。
- 不要使用 `mysql -p明文密码`，避免密码进入命令历史、进程参数、日志或截图。使用交互提示或受控凭据配置。
- 若数据库在另一台机器，MySQL 账号的 `@'主机'` 应限制为**应用服务器在数据库侧看到的来源地址**，不是数据库服务器自身地址；迁移账号也应限制其实际来源。不要直接改成 `%` 向任意来源开放。

## 3. 配置应用连接

配置项定义在 `wm_app/config.py`。

| 环境变量 | 含义 | 未设置时默认值 |
| --- | --- | --- |
| `WM_DB_HOST` | MySQL 主机或地址 | `127.0.0.1` |
| `WM_DB_PORT` | MySQL TCP 端口 | `3306` |
| `WM_DB_NAME` | 已存在的数据库名 | `wm` |
| `WM_DB_USER` | MySQL 连接账号 | `wm` |
| `WM_DB_PASSWORD` | 该连接账号的密码 | 空字符串 |
| `WM_SECRET_KEY` | 应用的随机、稳定密钥，不是数据库密码 | 未配置 |
| `WM_ENV` | 应用环境：development / testing / production | `development` |

默认值只是程序回退值，不会自动创建对应数据库或账号。按照上节示例创建后，必须显式设置数据库名为 `wordmachine`、运行账号为 `wm_app`。

`WM_DB_PORT` 与网页端口 `WM_PORT` 不同：前者通常为 3306，后者默认 5000。端口须为 1–65535 的整数。

应用连接固定使用 `utf8mb4` 和 REPEATABLE READ。当前连接超时为 5 秒，读/写超时各 10 秒；没有对应的 `WM_DB_TIMEOUT` 环境变量，不要添加无效配置。

### Linux / macOS

在项目根目录，仅在尚无 `.env` 时复制 `.env.example` 为 `.env`，然后编辑。例如：

```dotenv
WM_ENV=development
WM_HOST=127.0.0.1
WM_PORT=5000
WM_DEBUG=false
WM_LOG_LEVEL=INFO
WM_SECRET_KEY='替换为随机且稳定的应用密钥'
WM_DB_HOST=127.0.0.1
WM_DB_PORT=3306
WM_DB_USER=wm_app
WM_DB_PASSWORD='替换为运行账号的实际密码'
WM_DB_NAME=wordmachine
```

第一次可在自己的终端生成应用密钥，妥善保存后重复使用，不要每次启动重新生成：

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

限制 `.env` 权限，并在**启动程序的同一个终端**显式加载：

```bash
chmod 600 .env
set -a
. ./.env
set +a
```

这里的 `.` 是 shell 执行操作，只能加载自己审查过的文件。密码含引号等特殊字符时，必须按 shell 语法正确转义。不要加载来源不明的 `.env`。密钥缺失时开发模式可能使用临时值，不能据此认为配置已经完整。

### Windows PowerShell

激活项目虚拟环境后，在将要启动应用的同一 PowerShell 窗口设置：

```powershell
$env:WM_ENV = 'development'
$env:WM_HOST = '127.0.0.1'
$env:WM_PORT = '5000'
$env:WM_DEBUG = 'false'
$env:WM_LOG_LEVEL = 'INFO'
$env:WM_DB_HOST = '127.0.0.1'
$env:WM_DB_PORT = '3306'
$env:WM_DB_USER = 'wm_app'
$env:WM_DB_NAME = 'wordmachine'

$env:WM_DB_PASSWORD = [System.Net.NetworkCredential]::new(
  '', (Read-Host '请输入 MySQL 运行账号密码' -AsSecureString)
).Password
$env:WM_SECRET_KEY = [System.Net.NetworkCredential]::new(
  '', (Read-Host '请输入已保存的应用密钥' -AsSecureString)
).Password
```

首次可用 `python -c "import secrets; print(secrets.token_hex(32))"` 生成应用密钥并私下保存。上面的交互输入避免把密码直接写入命令历史，但环境变量在进程内仍是明文，并非加密的凭据保险箱。

这些变量只影响当前窗口及其子进程；换窗口需要重新设置。PowerShell 不会通过上述操作自动读取 `.env`，也不要用 Bash 的 `. ./.env` 语法加载它。

## 4. 初始化数据库结构

**以下升级命令只适用于确认可用的空开发库，或已经授权、备份并在副本演练过的库。已有数据先看第 7 节。**

当前源码的迁移 head 为：

```text
0012_manual_rating
```

先核对当前源码要求，避免使用不同版本说明：

```bash
python -m alembic heads
```

迁移时临时使用 `wm_migrate`，完成后恢复运行账号。不要以迁移账号启动日常网页服务。

**Linux / macOS（Bash）：** 已加载运行配置后，在子 shell 内覆盖凭据，不污染外层运行环境。下面使用 Bash 的 `read` 语法；macOS 默认使用 zsh 时，请先进入 Bash 再执行该片段。

```bash
(
  export WM_DB_USER=wm_migrate
  read -r -s -p '请输入 MySQL 迁移账号密码: ' WM_DB_PASSWORD
  printf '\n'
  export WM_DB_PASSWORD
  python -m alembic upgrade head
)
```

**Windows PowerShell：**

```powershell
$runtimeUser = $env:WM_DB_USER
$runtimePassword = $env:WM_DB_PASSWORD
try {
  $env:WM_DB_USER = 'wm_migrate'
  $env:WM_DB_PASSWORD = [System.Net.NetworkCredential]::new(
    '', (Read-Host '请输入 MySQL 迁移账号密码' -AsSecureString)
  ).Password
  python -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) { throw '迁移失败，请停止并核对实际结构，不要盲目重试。' }
} finally {
  $env:WM_DB_USER = $runtimeUser
  $env:WM_DB_PASSWORD = $runtimePassword
  Remove-Variable runtimeUser, runtimePassword
}
```

任一平台迁移报错都应停止后续步骤。**MySQL DDL 隐式提交：报错或中断不代表所有修改已经回滚。** 不要直接重跑、`stamp head` 或自动 downgrade。

## 5. 验证连接和迁移版本

在自己的终端使用运行账号连接。下面仍以示例数据库为准，实际地址/端口/名称须与 `WM_DB_*` 一致：

```bash
mysql --host=127.0.0.1 --port=3306 --user=wm_app --password wordmachine
```

输入密码后执行只读 SQL：

```sql
SELECT DATABASE(), CURRENT_USER(), VERSION();
SELECT version_num FROM alembic_version;
```

应连接到预期数据库，`version_num` 为 `0012_manual_rating`。如果 `alembic_version` 不存在，不要手工创建或填值，应先核实是否连接错库或尚未初始化。

### 显式创建网站管理员

确认环境已经恢复为运行账号，并完成迁移后：

```bash
python -m flask --app app create-master
```

交互输入 MASTER 密码两次，要求 16–128 个字符，包含 ASCII 大写、小写、数字和符号。该命令只创建全新的 MASTER / Lv.5，已有同名账号会拒绝覆盖或提权，不重置已有密码。

普通管理员可使用：

```bash
python -m flask --app app create-admin your-admin-name --level 1
```

这里等级允许 1–4；普通注册固定 Lv.0。

## 6. 构建并启动开发服务

首次准备或前端源码更新后执行：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
python app.py
```

Windows PowerShell 可使用 `npm.cmd` 替代 `npm`。前端构建还要求 Node.js `^22.18.0 || >=24.12.0`。

默认访问 `http://127.0.0.1:5000/`。

- `/health/live`：仅检查进程存活，不访问数据库。
- `/health/ready`：检查数据库连接及迁移版本；正确时返回 200 / `{"status":"ok"}`。
- 版本不匹配时返回 503 / `{"status":"migration_required"}`；数据库访问异常时返回 503 / `{"status":"unavailable"}`。

**前端构建成功不代表数据库已经就绪。** 版本号检查也不能代替完整结构/数据核验，不要伪造版本号来消除 503。

## 7. 已有数据库升级注意事项

1. 先确认目标数据库和实际版本，停掉所有旧写入者；备份并在隔离副本演练恢复/升级，再安排正式维护窗口。
2. 0009 管理员等级迁移要求为所有旧 `type='root'` 账号提供完整精确的 ID→等级映射，包括已封禁账号。先只读查看：

   ```sql
   SELECT id, username, type, deleted FROM user WHERE type = 'root' ORDER BY id;
   ```

3. 审查映射后，以迁移账号执行。下面 **17 和 2 只是示例，不可照抄**；传参方式见注释：

   ```bash
   # Bash 示例
   python -m alembic -x 'admin_levels={"17":2}' upgrade head
   ```

   JSON 键是实际账号 ID，值是审核后的等级；必须列出所有旧 root。不同 PowerShell 版本向原生命令传递嵌套双引号的规则可能不同，不能未经核对直接照搬 Bash 的 JSON 参数。应确认参数原样传入；不要因解析失败而省略映射、改用户名或直接修改等级字段。

4. 0009 不替旧账号改名或重置密码；0010 建立未来结算的 Rating 事件链，不回填旧事件；0011 初始化词典倍率为 1.00，但旧局继续旧规则、不补造倍率。0012 扩展人工 Rating 事件及幂等回执，迁移本身不调整任何余额或重写历史。
5. 不改写已经应用的迁移，不使用旧建表脚本覆盖当前结构；不直接修改 Rating 绕过流水，不为通过校验静默重算历史。
6. 同步部署匹配的前后端代码。普通启动不会替你完成升级，也不能让新旧应用同时写同一个库。

清空重建是另一种破坏性操作，**不是升级的必选步骤**。必须另行明确授权数据丢弃，不能用重建代替迁移故障排查。

## 8. 常见问题

| 现象 | 排查方向 |
| --- | --- |
| `Access denied` / 1045 | 用户名、密码、账号允许的来源地址是否匹配；`localhost`、`127.0.0.1`、IPv6 与远程来源不能想当然混用 |
| 数据库访问权限不足 / 1044、1142 | 是否给了正确账号在正确数据库上的权限；正常运行只需 DML，迁移另用专用账号，不直接把应用改成 root |
| `Unknown database` / 1049 | 数据库是否已创建，`WM_DB_NAME` 是否正确 |
| 无法连接 / 2003 | MySQL 是否启动，地址/端口、监听配置和防火墙是否正确 |
| 找不到表 / 1146，找不到列 / 1054 | 是否连接错库、迁移未完成，或代码与结构不匹配；不要手补猜测字段或修改版本号 |
| `/health/ready` 返回 503 | 区分连接失败与版本不匹配；查看脱敏应用日志并核对版本 |
| `.env` 已修改但没有变化 | 程序不会自动加载；应在启动终端重新加载，再重启应用。也检查是否实际使用了独立配置的启动方式 |
| 页面返回“Frontend build missing” | 前端产物缺失，不是数据库错误；在对应源码版本执行前端构建 |
| 写请求超时、断线、2006/2013 | 先核对服务状态和已提交结果；不要假设回滚并自动重复写入 |

## 9. 安全边界

- 不提交真实 `.env`、数据库导出、凭据文件或诊断日志；分享配置时隐藏密码、密钥和登录令牌。
- 只允许必要机器访问 MySQL，不把 3306 直接暴露到公网。
- 当前 `WM_DB_*` 配置未暴露数据库 TLS 选项。远程生产数据库需专门规划受控网络/隧道或实现并验证 TLS；网页 HTTPS 不等于数据库连接已加密，不能通过关闭已有安全策略来绕过安全传输要求。
- `WM_ENV=production` 要求非空数据库密码、至少 32 字符的应用密钥并关闭 debug；这不是完整生产部署验收。`app.py` 是开发入口，会拒绝作为生产服务器启动。
- 本文只描述配置和操作步骤，不表示已在读者的数据库执行过初始化、备份或升级。
