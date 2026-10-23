# N2 首轮：自然会话过期与限流恢复

对应 [PLAN.md](../PLAN.md) 的 N2。本轮补充本地故障证据，不重新实现认证或写协议。**N2 已开始但未整体验收，N1 性能收尾仍开放，N3–N8 未开始。** N1 新基线和暂未采用的候选见 [后续测量记录](LIST_FOLLOWUP.md)。

## 覆盖缺口与当前范围

| 项目 | 此前证据 | 本轮补充 / 尚待验证 |
|---|---|---|
| 自然会话到期 | 单元测试、把测试会话 expires_at 改为过去后的 HTTP 拒绝 | 新增等待真实期限的 HTTP、逐 Socket 事件、握手与广播前剔除，以及真实浏览器旧表单/连接清理和人工重登 |
| 429 / Retry-After | MySQL 计数/账户别名共享，修改测试窗口后的恢复；客户端解析/提示单元测试 | 新增按实际 Retry-After 等待的恢复与计数持久性，浏览器确认提示并观察整个窗口内没有自动重发；IP/注册限流的更多浏览器组合仍待补 |
| 长时间后台恢复 | 轮询/连接生命周期组件测试，真实对局断线恢复 | 后台长时间限速、系统休眠等真实浏览器组合未补 |
| 换账号后的迟到响应 | generation、actor/CSRF 及页面卸载等组件测试 | 本轮只验证同账号重新登录更换 Cookie/CSRF 和旧草稿不重放；跨账号迟到成功/错误响应的真实浏览器矩阵未补 |
| 应用重启 | 重建应用后的持久回执重放；后续[本地启动编排](LOCAL_START.md)已实际停止/重启应用及 MySQL，用新浏览器载入原 Cookie 并重放原 UUID | 持续打开浏览器时的实时连接恢复、挂起写意图及丢确认组合仍未补；不把启动编排当完整故障链路 |
| 短暂数据库不可用 | 既有错误适配、事务回滚/确认丢失故障用例 | 实际测试数据库短暂中断及恢复流量未补 |
| 多浏览器、CI | 本地 Chromium；完整工作区有 CI 配置 | 支持矩阵/环境未验收；精简 GitHub 仓库无测试/CI，实际执行须先确认验证仓库及交付权限 |

不是每个期限一到就向全站页面推送登出。当前语义是在 HTTP/Socket 身份复核及广播前拒绝过期身份；页面通过错误/读取发现失效后销毁旧资源。本轮没有新增主动到期推送、自动重新登录或写请求重试。

## 新增的 6 项真实 MySQL 回归

[`tests/integration/test_auth_faults_mysql.py`](../tests/integration/test_auth_faults_mysql.py) 使用真实 MySQL，以及 Flask/Socket.IO 测试客户端调用实际适配器；该层不冒充真实网络传输。

- 先实际提交一个带 UUID/版本的答案，再自然到期。过期会话连**原成功回执重放**也必须先经过认证，不能绕过鉴权；新的结束、词典创建和资料写入均拒绝。原答案、版本、余额、历史和回执保持；重新登录后，人工提交原 UUID/操作者/参数只返回原回执，不重复评分。
- 三个参数用例分别在已订阅连接自然到期后发送 subscribe/answer/end；拒绝操作、断开旧连接，数据库事实不变，原 Cookie/CSRF 也不能重新握手。
- 空闲连接自然过期后触发实际广播函数：先剔除过期连接，另一有效会话仍正常收到更新；没有对局或评分写入。
- 错误密码消耗第一次账户额度，随后正确密码收到真实 429；HTTP Retry-After 与 JSON 一致，计数已经提交，没有新会话或密码升级。按响应等待后只由人工下一次请求恢复，并核对窗口重置与单个新会话。

只缩短所属测试应用的期限/额度，不由测试直接改写 expires_at/window_started 来制造到期，不修改系统/浏览器时钟，也不使用 purge、封禁或登出冒充自然到期。新用例独立 SQL 比较词典、单词、对局、题目/成员/答案/结算/流水、余额/旧历史和回执。

### 时间精度注意

现有认证表 DATETIME 按整秒保存；MySQL 可能把新窗口开始时间向上舍入到下一整秒。因此配置为 3 秒的窗口可能返回 4 秒 Retry-After。首轮新增测试曾错误地断言响应最多 3 秒，已经修正为考虑存储精度，并额外核对响应等待覆盖**实际存储期限**，再真实等待验证恢复。

这不是把失败掩盖成通过或修改限流策略：旧结构/时间字段/服务代码均未变，首轮失败日志保留。浏览器按服务器实际返回的值展示/等待，不自行假设精度，不在计时结束时自动提交。

## 新增的 2 个真实浏览器场景

- [`frontend/mysql-e2e/expiry.spec.ts`](../frontend/mysql-e2e/expiry.spec.ts)：真实登录后打开资料和已订阅的对局页面，关闭只读轮询并等待自然期限；旧表单提交得到 401，私有页面返回登录，旧实时连接随页面清理关闭。另一个独立观察者保留原 token 为浏览器会话 Cookie，先确认有效再轮询到服务端拒绝，避免把浏览器自动删 Cookie 误当服务端期限证明；主浏览器保持正常签发 Cookie。期限后再次重放旧 token，服务端仍拒绝。人工重新登录更换 Cookie/CSRF，原简介未写入、旧草稿没有自动重发。
- [`frontend/mysql-e2e/rate-limit.spec.ts`](../frontend/mysql-e2e/rate-limit.spec.ts)：实际服务器返回 429 和 Retry-After，页面显示准确秒数；完整等待该窗口后仍停在登录页、只有原两次请求，第三次必须手动点击。成功登录后退出，SQL 核对无残留有效会话。
- [`tests/browser/test_auth_fault_browser.py`](../tests/browser/test_auth_fault_browser.py)：两个独立编排，各自使用新合成数据库，复用现有服务器/进程清理夹具及历史不变断言；另核对会话、限流计数、简介和连接注册表。

不拦截或伪造成功 API，不用 SQLite。自然过期下的“浏览器挂起游戏写命令 + 回执丢失 + 重登”全部组合尚未覆盖；本轮后端回执证明与已有双用户实际重试场景分别记录，不能合并成未实际执行的场景。

## 验证结果

```bash
make check-with-mysql
make test-browser
make test-browser-mysql

# 针对本轮用例，仍只新建私有合成 MySQL。
.venv/bin/python scripts/with_test_mysql.py -- .venv/bin/python -m pytest \
  tests/integration/test_auth_faults_mysql.py tests/browser/test_auth_fault_browser.py \
  -q -s -p no:cacheprovider
```

- 完整 **811 Python = 559 单元 + 252 MySQL**，无数据库跳过；102 个 Python 文件 Ruff lint/格式通过，也完成 Python 3.10 语法解析。
- **181 Vitest / 16 文件**，前端 lint、格式、类型检查和构建通过。
- **14 个模拟 API 浏览器检查**，另 **7 个真实 MySQL/Chromium 场景 + 6 个独立 Python 编排/SQL 核对**通过；不把编排重复算成业务场景。
- 新增用例定向通过后，全量通过，再以新私有实例独立复跑 **6 个 MySQL + 2 个浏览器编排（含 2 个 Chromium 场景）**通过。完整 Python 342.71 秒，针对新增用例的独立复跑 62.63 秒；之后补强浏览器的服务端期限观察者，前端全检查及全套真实浏览器（6 编排 69.80 秒）再次通过，新增 2 个编排又独立通过（28.22 秒）。这些不是性能门限。
- 实际运行 Python 3.11.17、MySQL 8.0.42、既有 Playwright/Chromium。Ubuntu 20.04 仍非当前 Playwright 官方支持系统，不外推多浏览器或生产验收。

日志为 `/tmp/wm-n2-auth-faults-{check,mock-browser,real-browser,repeat}.log`；最终前端检查为 `wm-n2-auth-faults-frontend-authoritative-final.log`，最终真实浏览器及其独立复跑为 `wm-n2-auth-faults-browser-authoritative{,-repeat}.log`，均在 `/tmp/`。定向及初期失败日志一并保留。

补强后的第一次前端复跑曾因 node_modules 中 Vitest/jsdom 依赖文件短暂缺失而未能启动测试；随后检查时文件已恢复，源码、依赖清单和锁文件未变，未确定缺失触发者。没有修改依赖版本或丢弃失败日志；`npm ls --all` 及重新执行前端全检查、真实浏览器和独立复跑均通过。

与 N1 证据共同逐字节归档至本机忽略目录：

`performance-results/n1-followup-n2-auth-4f621d41058b47ccbc20de1d0a166eca-final/`

其中 `manifest.json` 记录最终 122 个证据/源码文件的 SHA-256，包含补强后的浏览器测试快照及额外复跑。此前 117 文件归档仍保留，未改写旧报告或上传归档。

## 交付边界

本轮仅新增测试、测量记录和开发文档。构建/运行源码与已合并 PR #2 的 `b8e8ed4` 逐字节一致；八版迁移、依赖、评分、历史与写协议不变，head 仍为 `0008_list_indexes`。没有业务库操作、生产发布或新的 GitHub 上传。该仓库依约不包含测试/CI，本地通过不等于托管 CI 通过。N2 剩余矩阵、实际 CI 与受支持环境仍继续跟踪。
