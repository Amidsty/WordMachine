# WordMachine

多人单词对战网站的运行与构建源码：Flask、MySQL、Socket.IO，Vue 3、TypeScript、Vite。HTTP/Socket共用权限、事务和幂等协议。

> 当前源码要求数据库 `0018_bounded_rating`。普通启动不初始化、迁移、重置账户或重算历史。提交源码不代表实际数据库升级或部署；旧库不能直接使用本版本，新旧服务不得混写。

## 评分与主要功能

- **有界累计Perf v2**：新建局使用`weighted-perf-v2` / `weighted-rating-v2`。词典倍率直接线性缩放单题Perf增量，难度涨/扣系数限定0.75–1.25，不再用对数赔率反推Perf。难度/倍率在创建时冻结，账户与保护/速度参数在开局时冻结。
- **连击反馈**：答对奖励用个人连击；答错惩罚用作答前房间全局连击，成熟期最高3倍，新手仍保留反馈。错误先计惩罚再清本人和全局连击，不清其他人的个人连击。普通答案表显示事后值，评分明细显示实际使用的事前值。
- **额度与Rating**：公开R、剩余额度H、内部U=R+H。新账号总额度1500按600、350、250、150、100、50六次释放，不是每场补到1500；旧账号不补发、不虚构历史次数。升级规则不重置额度序号。
- **竞技结算**：高分上涨系数下限0.75、下跌系数上限1.25；保留两次±200限幅、新手保护、非正净权重禁止正收益及最终取整。倍率不保证最终整数Rating同比变化。竞技项、额度、总事件、账户状态、有效场次及原UUID回执同事务。
- **Rated / Unrated**：同一用户最多一场运行中Rated，可加入多个等待局；Unrated可并行，不更新Rating、额度或有效场次。合法结束且至少一条有效答案即可计有效Rated，全错或授权少题提前结束也可有效；未作答不发额度。
- **配置与展示**：难度为0–4000整数，默认1500不代表已标定；倍率0.10–5.00，与Rated准入区间独立。配置含当前权限、CAS版本、原因及审计；旧局快照不变。显示局分、Perf、R/H/U、冻结系数、竞技变化及额度分项。
- **历史与兼容**：v1等待/运行/结束局继续v1，旧答案、历史及成功回执不重算。更早模型0的运行Rated继续旧规则，等待Rated拒绝开局。公开历史独立分页，Perf取最后保存值；缺失不补零、不推算。人工原因、操作者、UUID和计算审计不公开。
- **其他功能**：CSV原子导入、词表区间删除、词典转系统审批、创建者改名、私人结束请求、观战、账号分级管理与人工调分。

例如U0=1500、D=4000、M=0.10、抽样10、无连击时，v2独立首题正确Perf约+1.249037、错误约−0.750963。Perf是U0加累计本场表现，不是已标定的真实能力；单题有界不代表整场有固定上限，也不保证长期收敛或防刷。

个人词典owner/Lv.5维护，系统词典Lv.3+维护；新Rated只允许系统词典，成员当前公开Rating须符合准入区间。人工调分仅Lv.4/5自调或调严格下级活动用户，任何运行中比赛均阻止调分，指定值仍为公开R且不消耗额度。比赛改名仅创建者；提前结束仅房主或当前Lv.2+，非参赛管理员结束不因此获得成绩。

## 交付范围

仅含运行/构建/迁移源码、配置示例、运行依赖、前端依赖锁及本说明。`scripts/upgrade_database.py`为通用升级入口，不是本机启动器。保留项目署名。

不包含本机启动/测试工具、shell脚本、测试/CI、开发文档、升级指南/报告、实际配置、备份、凭据、日志、缓存、虚拟环境、`node_modules/`或`frontend/dist/`。依赖清单与锁保持原样；测试/lint命令依赖未交付的开发文件，精简树使用`npm ci`和`npm run build`。

完整开发树已重新全量检查：2223项后端（1567单元＋656隔离真实MySQL）、322项前端、19项真实Chromium/MySQL编排、14项mock浏览器、1项隔离启动/重启生命周期，以及Python静态和前端lint/格式/类型/构建，全部通过。精简导出树另用新运行依赖环境与npm ci验证构建和隔离MySQL运行烟测；22个构建产物与受测开发树一致，产物不上传。

这些是本地检查，不等于托管CI、生产容量、多worker、全浏览器或跨平台浮点验收。未部署、未操作实际持久数据库。

## 环境与配置

- Python 3.10+，推荐3.11。
- MySQL **8.0.16+ / InnoDB**，不支持MariaDB/SQLite。
- Node.js `^22.18.0 || >=24.12.0`、npm。
- 独立数据库及账号；迁移使用必要DDL权限，应用仅使用本库DML权限，不长期使用root。

应用与Alembic共用`WM_DB_HOST`、`WM_DB_PORT`、`WM_DB_NAME`、`WM_DB_USER`、`WM_DB_PASSWORD`。不自动建库或建账号，不用`DATABASE_URL`或自填Alembic连接串替代。明确核对目标实例。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 仅复制示例，不能覆盖已有配置；随后自行配置。
cp -n .env.example .env
```

配置真实连接和随机、稳定的`WM_SECRET_KEY`，不要提交实际配置。`.env`不自动加载；仅在审核后手动加载：

```bash
set -a; . ./.env; set +a
```

## 数据库代码

- `migrations/versions/0018_bounded_rating.py`：追加快照规则版本并扩展约束；旧行明确标记v1，不重算旧分数、改写回执或重新初始化账户。已交付的0001–0017迁移、v1引擎及冻结schema未改写。
- `scripts/upgrade_database.py`：明确审查0011–0018链，默认只读查看版本/计划；不初始化、接管账号或自动跟随未来head。参数以代码和`python scripts/upgrade_database.py --help`为准。

实际执行须另行核准，并具备停写、完整备份、独立恢复和副本演练证据。MySQL DDL可能已隐式提交；失败后不得盲重跑、换报告路径绕审查、手改版本、stamp或自动downgrade。报告不是备份，协作锁不能替代停写。本次交付可执行代码，不新增升级指南。

## 构建与启动

以下命令仅用于已完成迁移和验收、版本匹配的数据库。普通启动不创建或重置MASTER；需要时使用显式`create-admin` / `create-master` CLI，同名拒绝接管。Lv.5新密码需16–128字符并包含ASCII大小写、数字和符号。

```bash
npm --prefix frontend ci
npm --prefix frontend run build
python app.py
```

默认 http://127.0.0.1:5000 ，Flask同源提供`frontend/dist/`，缺构建返回503。

- `/admin/`：词典管理；`/admin/users/`：管理员用户管理。
- `/admin/dictionary-promotions/`：申请/审核；普通所有者仅本人申请。
- `/game-end-requests/`：权限内可见的私人结束请求。
- `/health/live`：进程存活；`/health/ready`：连接与唯一版本0018，不代替结构/事实审计。
- `python -m flask --app app audit-legacy`：只读审计；输出保持私有。

`app.py`仅开发入口，在生产配置下拒绝启动。HTTPS/代理、生产容量、异地恢复、多worker及跨平台浮点仍需专项验收；稀疏/高删除比例列表、大答案量重建有性能边界。Socket撤销和观战视图为进程内状态。写请求不自动重发，超时/关闭不代表回滚，须先核对原操作。

## 项目署名

idea: [Amidst](https://github.com/Amidsty)

code: [shicj0927](https://github.com/shicj0927)(With Github Copliot) & [sun2snow](https://github.com/sun2snow)(With ChatGPT 6 Astra)
