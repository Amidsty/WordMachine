# Word2Machine

多人单词对战网站的运行与构建源码：Flask、MySQL、Socket.IO，Vue 3、TypeScript、Vite。支持账号与分级管理、词典维护、CSV、多人对局和评分历史；HTTP/Socket 共用权限、事务及幂等协议。

> 当前源码要求数据库 `0017_weighted_rating`。普通启动不初始化、迁移或重算历史。源码提交不代表数据库升级或部署，旧库不能直接使用本版本，新旧评分服务不得混写。

## 本次更新（PR #4 之后）

- **加权 Perf / Rating**：个人连击奖励、当前房间全局连击惩罚；原始局分与 Perf 分开，字典倍率用于证据权重。创建冻结难度/倍率，开局冻结账户及保护/速度参数。
- **新手额度**：公开 Rating 为 R，剩余额度为 H，内部 U=R+H。新账号总额度1500按600、350、250、150、100、50释放，不是每局补到1500；旧账号默认关闭政策，不补发、不虚构历史场次。
- **竞技结算**：高分上涨减速、下跌加速，仅影响竞技变化。竞技变化、额度释放、总事件、账户状态、有效场次和原UUID回执同事务；公开总变化可能为正而竞技变化为负。
- **Rated 互斥**：同一用户只能参加一个运行中的 Rated，可同时加入多个等待局；Unrated 可并行，不更新 Rating、额度或有效场次。全错及授权少题提前结束仍可构成有效场次，无答案不发额度。
- **难度与分项界面**：词典难度整数0–4000，默认1500不代表已标定；与倍率和 Rated 准入区间独立。配置含当前权限、版本CAS、原因和事务审计，已有局快照不变。展示局分、Perf、R/H/U、保护/速度系数和竞技/额度分解。
- **公开历史**：独立分页的 Rating / Perf 历史及账户额度状态；只展示保存事实，Perf 取最后保存值，旧缺失不补零、不推算。人工原因、操作者、UUID及计算审计不公开。
- **私有结束请求**：仅房主或当前Lv.2+可直接提前结束；其他用户可提交私有请求和留言，不改变比赛版本或评分。非参赛管理员结束不因此获得成绩。
- **兼容边界**：旧运行 Rated 保留旧评分和占用直至结束；旧等待 Rated 不再开局，可由原权限取消后另建。旧答案、结算及成功回执不重算。既有人工调分、准入区间、转系统审批、比赛改名和账号权限保留。

个人词典由owner/Lv.5维护，系统词典Lv.3+维护；新Rated只允许系统词典且成员当前公开Rating符合准入区间。人工调分仅Lv.4/5自调或调严格下级活动用户，任何运行中比赛均会阻止调分；指定值仍为公开Rating，不消耗新手额度。仅创建者可改比赛名称，无管理员豁免。

## 交付范围

仅含运行/构建/迁移源码、配置示例、依赖清单及锁、本说明。`scripts/upgrade_database.py` 是通用数据库升级入口，不是本机启动器。

不包含本机启动/测试工具、`.sh`、测试、CI、计划/开发文档、升级指南/报告、实际配置、备份、凭据、日志、缓存、虚拟环境、`node_modules/` 或 `frontend/dist/`。项目署名保留。

依赖清单及锁保持原样。测试/lint命令依赖未交付的开发文件；此精简树使用 `npm ci`、`npm run build`。完整开发树本地验证通过：1752后端（1108单元＋644真实MySQL）、312前端、18项真实浏览器编排/20场景、14项mock浏览器、1项启动生命周期，以及静态/类型/构建检查；这不是托管CI或生产验收。

## 环境与配置

- Python 3.10+（推荐3.11）；MySQL **8.0.16+ / InnoDB**，不支持MariaDB/SQLite。
- Node.js `^22.18.0 || >=24.12.0`、npm。
- 独立数据库及账号；迁移使用必要DDL权限，应用仅使用本库DML权限，不长期使用root。

应用与Alembic共用 `WM_DB_HOST`、`WM_DB_PORT`、`WM_DB_NAME`、`WM_DB_USER`、`WM_DB_PASSWORD`。不自动建库/建账号，不使用 `DATABASE_URL` 或自填Alembic连接串；必须明确核对目标实例。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 不覆盖已有配置；仅示例值，必须自行修改。
cp -n .env.example .env
```

设置真实连接和随机、稳定的 `WM_SECRET_KEY`，不提交真实配置。`.env` 不自动加载；仅在审核后手动加载：

```bash
set -a; . ./.env; set +a
```

## 数据库代码

- `migrations/versions/0017_weighted_rating.py`：版本化迁移；已交付的0001–0016未改写。
- `scripts/upgrade_database.py`：明确审查0011–0017链，默认只读查看版本/计划；不初始化或接管账号，不自动跟随未来head。参数与拒绝条件以代码及 `python scripts/upgrade_database.py --help` 为准。

实际执行必须另行核准，并具备停写、完整备份、独立恢复和副本演练证据。MySQL DDL可能已隐式提交；失败后不得盲重跑、绕过报告审查、手改版本、stamp或自动downgrade。脚本报告不是备份，确认参数不能替代恢复与数据验收事实。本次交付提供代码，不新增升级指南。

## 构建与启动

以下仅适用于已完成迁移和验收、版本匹配的数据库。普通启动不会创建或重置MASTER；需要时使用显式 `create-admin` / `create-master` CLI，同名拒绝接管。Lv.5新密码需16–128字符并包含ASCII大小写、数字和符号。

```bash
npm --prefix frontend ci
npm --prefix frontend run build
python app.py
```

默认 http://127.0.0.1:5000 ，Flask同源提供 `frontend/dist/`，缺构建返回503。

- `/admin/`：词典管理；`/admin/users/`：管理员用户管理。
- `/admin/dictionary-promotions/`：申请/审核列表，普通所有者仅本人申请。
- `/health/live`：进程存活；`/health/ready`：数据库连接及唯一版本0017，不代替结构/数据审计。
- `python -m flask --app app audit-legacy`：只读事实审计；输出保持私有。

`app.py`仅开发入口，生产配置下拒绝启动。生产容量、HTTPS/代理、异地恢复、多worker、更多浏览器及跨平台浮点仍需专门验收；稀疏/高删除比例列表和大答案量重建仍有性能边界。Socket撤销/观战视图为进程内状态。写请求不会自动重发，超时/关闭不代表回滚，须先核对原操作结果。

## 项目署名

idea: [Amidst](https://github.com/Amidsty)

code: [shicj0927](https://github.com/shicj0927)(With Github Copliot) & [sun2snow](https://github.com/sun2snow)(With ChatGPT 6 Astra)
