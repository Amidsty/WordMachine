# WordMachine

多人单词对战网站，基于 Flask、MySQL、Socket.IO 和 Vue 3 + TypeScript。

仓库：<https://github.com/sun2snow/WordMachine>

本仓库按精简源码范围交付运行、前端构建、数据库迁移及示例配置。测试、CI、开发文档、本机专用启动工具、实际配置、数据库、日志和构建产物不在交付范围内。代码推送不代表数据库升级或生产部署。

## 功能

- 多人对局、实时状态、观战、对局记录与公开个人主页。
- Rated / Unrated 模式；保留旧评分模型与历史记录，不自动重算历史。
- 词典、词条及 CSV 管理；个人词典转系统词典的申请与审核。
- 0–5级管理员权限、严格下级管理、会话撤销及人工 Rating 调整。人工调整的原因和操作者可逐条独立选择公开，默认不公开。
- 排行榜最多100人：相同 Rating 采用 `1、1、3` 并列排名，同分按参赛次数降序、再按 ID 升序；先计算全榜名次再分页，所有并列前三名显示对应牌子。
- 个人主页展示全历史 Rating / Perf 双折线，可切换 Rated / Rated + Unrated；人工调分独立标记，Unrated 保持此前可确认的 Rating，缺失 Perf 跨点连接，不补零或伪造旧日期。历史明细合为一张表，同场对局的 Rating 与 Perf 同行展示，统一分页。
- 参赛次数统计已结束且本人为成员、至少保存一次本人作答的比赛，Rated / Unrated 均计入；未作答和观战不计。
- 大厅、对局和详情自动读取；公开资料、评分历史及排行榜使用独立低频自动刷新。未知写入保留原请求，必须明确重试，不自动重复提交。
- 顶部“管理中心”内分词典管理、系统词典申请、用户管理三个同级栏目，入口和操作均保留原权限限制。

## 环境要求

- Python 3.10+，推荐 Python 3.11。
- MySQL 8.0.16+ / InnoDB；不支持 MariaDB 或用 SQLite 替代。
- Node.js `^22.18.0 || >=24.12.0`、npm。

当前唯一迁移 head 为 **`0019_manual_visibility`**。应用启动不会自动建表、迁移、创建管理员或重置密码。

## 开发准备

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：填写专用开发数据库连接信息和随机、稳定的 WM_SECRET_KEY。
set -a; . ./.env; set +a

npm --prefix frontend ci
npm --prefix frontend run build
```

`.env`不会自动加载，也不得提交。Windows 请使用对应虚拟环境激活方式并显式设置环境变量。

数据库需预先存在。**已有数据的实例不要直接初始化、清库或盲目执行迁移**；先停写、备份、在副本恢复并演练，审查迁移及旧数据完整性。

仅对确认可用的空开发数据库，可显式执行：

```bash
python -m alembic upgrade head
python -m flask --app app create-master
```

`create-master`通过隐藏输入设置密码，同名账户拒绝覆盖；不会替已有账户重置密码。迁移账号需要DDL权限，日常运行账号应使用受限权限。

已有数据库的升级工具：

```bash
python scripts/upgrade_database.py --help
```

工具要求明确目标和数据库连接；默认仅检查，不自动执行升级。不要对不明状态的数据库使用`stamp`、降级或重复执行失败的DDL。升级报告不是备份。

## 启动与前端开发

```bash
python app.py
```

默认只监听 `http://127.0.0.1:5000`，debug关闭。`frontend/dist/`由本地构建产生、由Flask同源提供，缺少构建时页面返回503。

前端热更新可在另一个终端执行：

```bash
npm --prefix frontend run dev
```

Vite 默认将 API、健康检查和 Socket.IO 代理到 `http://127.0.0.1:5000`；需要时通过`WM_API_PROXY`指定专用开发后端。

- `/health/live`：进程存活，不读取数据库。
- `/health/ready`：检查数据库连接及`0019_manual_visibility`版本，就绪失败返回503。
- `/admin/`：管理中心，默认词典列表；用户管理继续要求管理员身份。
- `/user/<id>/`、`/leaderboard/`：公开资料和排行榜。
- `/game/<id>/`、`/game/<id>/detail/`：对局及历史详情。

本仓库的依赖清单保留完整开发依赖与锁文件，但测试套件未随精简源码交付；使用`npm --prefix frontend run build`构建，不将缺少测试的精简仓库称为完整回归环境。

**开发启动不等于生产部署。** `app.py`拒绝作为生产服务器运行；生产还需明确TLS/反向代理、Socket.IO进程模型、安全配置、容量及恢复方案。`WM_ENV=production`会强制安全Cookie、密钥与debug校验，但不代替上述验收。

## 主要目录

- `wm_app/`：应用工厂、HTTP/Socket接口、认证、权限、事务及业务服务。
- `wm_app/models/`、`migrations/`：存储模型和显式迁移；旧迁移与历史兼容路径保留。
- `frontend/src/`：Vue界面、接口契约、生命周期和交互逻辑。
- `scripts/upgrade_database.py`：通用数据库升级检查与明确执行工具。

不上传真实数据库凭据、会话、私钥或备份；公开字段隐藏和服务端权限不能用前端按钮隐藏替代。

## 项目署名

idea: [Amidst](https://github.com/Amidsty)

code: [shicj0927](https://github.com/shicj0927)(With Github Copliot) & [sun2snow](https://github.com/sun2snow)(With ChatGPT 6 Astra)
