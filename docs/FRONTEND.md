# 前端开发与渐进迁移

## 当前范围

已建立 Vue 3 + TypeScript + Vite + Vue Router 工程，并接管：

- `/login/`：登录。
- `/register/`：注册。
- `/changepw/`：修改简介、修改密码。
- `/admin/`：词典分页/搜索、新建、重命名、删除。
- `/admin/dicts/<id>/`：单词分页/搜索、增删改、CSV 文件/文本导入和完整导出；无管理权时只读。
- `/admin/users/`：管理员用户搜索/分页、重置密码、封禁和恢复。
- `/`：大厅分页/筛选，创建、报名、退出、开始、取消，自动刷新和进入已开局对局。
- `/user/<id>/`：公开资料，允许匿名访问。
- `/leaderboard/`：公开前 100 名榜单，分页保留全局序号和原排序。
- `/game/<id>/detail/`：历史详情，按已有记录展示答题/本局评分、缺失值和题目来源，只读刷新与客户端答题分页。
- `/game/<id>/`：当前题目/轮次、Socket/HTTP 答题、提前结束、只读观战、人工重试原意图及连接恢复。

所有业务页面均已接管，`templates/`、`static/` 内的旧实现和共用 CSS/导航/认证适配器、对应 `tests/js/` 已删除。大厅、播放、详情采用 Vue 导航，不再有 `navigateLegacy` 或 CDN Socket 脚本；Socket 客户端由锁定的 npm 依赖随构建发布。

此前已接入请求 ID/版本及 [题目快照](GAME_QUESTIONS.md)，Vue 播放页与历史详情按 `question_source` 区分来源。此前的 [参赛关系/显式转换工具](GAME_PARTICIPANTS.md) 不改变公开成员结构。此前的 [新局答题关系](GAME_ANSWERS.md) 保持原答题协议。此前增加 `0007_game_settlements` 和 [结算流水](GAME_SETTLEMENTS.md)，`userrating` 保留旧历史前缀并追加新流水，公开结构不变，前端补结算异常提示；不改变认证、词典权限或评分规则，不自动转换历史 JSON。此前的 [受限答案转换工具](ANSWER_CONVERSION.md) 仅提供显式 CLI，不改页面/接口形状；成功转换推进对局版本，通过现有读取/轮询恢复，不自动重放写请求。列表接口已改为有界分页，协议及兼容变化见 [基线文档](BASELINE.md#列表分页与搜索)。已补通用弹窗、表格、分页及轮询组合式函数；此前交付 [历史详情](GAME_HISTORY_UI.md) 和 [播放页与统一 Socket](GAME_PLAYING_UI.md)，复用状态资源和成绩/答题组件；[管理真实浏览器验收](MANAGEMENT_BROWSER_TESTS.md) 也已补齐；Python 代码整理与统一检查见 [检查指南](PYTHON_CHECKS.md)；此前 [合成列表基准与查询优化](LIST_PERFORMANCE.md) 已完成；此前 [列表索引及分页取行](LIST_INDEXES.md) 将后端就绪版本推进到 `0008_list_indexes`；此前 [N1 搜索/首页读取](LIST_SEARCH_READS.md) 保持分页/权限/来源契约。此前 [名字颜色修复](NAME_COLORS.md)增加共享 `UserName.vue`，各页按当前公开 Rating 着色；游戏/大厅摘要补充该字段，旧响应省略时中性显示。阈值及样式集中管理，不根据角色、Perf 或历史结算猜色，不改评分或迁移版本。本批没有修改前端业务源码，新增 [自然过期和限流恢复](AUTH_FAILURE_TESTS.md) 的真实浏览器证据；N1 新基线/候选复测另见 [后续记录](LIST_FOLLOWUP.md)。

## 安装和运行

使用 Node.js `^22.18.0 || >=24.12.0`，建议 Node 22 的受支持补丁版本。依赖由 `frontend/package-lock.json` 锁定，使用 `npm ci` 重现。

### 从 Flask 运行构建后的页面

在仓库根目录执行：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
# 按 README 配置 Python 环境、数据库与环境变量后：
.venv/bin/python app.py
```

构建产物在 `frontend/dist/`，不提交到版本库，但部署时必须与对应应用版本一起交付。运行已构建产物不需要另起 Node 服务。Flask 的 `wm_app/frontend.py` 只为上述已迁移 URL 提供 `index.html`，为 `/ui/assets/<filename>` 提供带内容哈希的 JS/CSS。

- 页面入口不缓存；哈希资源可长期缓存。发布时完整更新构建目录，不能只替换 HTML 或只替换 JS。
- 缺少构建产物返回明确的 503，不悄悄使用旧页面；应用启动及 `/health/live` 本身不要求构建或数据库可用。
- `/health/ready` 当前仍检查数据库及迁移版本，不代替前端构建/页面冒烟检查。
- 未知 URL、缺失资源保持 404；没有全站 `/<path>` SPA fallback，不吞掉 API、Socket 或健康检查。
- Flask 直达 `/`、`/changepw/`、播放/历史详情和管理路径保留登录守卫，`/admin/users/` 额外检查 root（普通用户返回 403）；SPA 内也检查会话/角色，普通用户跳回词典管理。真正权限始终在后端 API。
- 已迁移页面可直接访问、刷新。服务端登录跳转保留目标路径，登录成功只接受白名单站内目标（首页、资料修改、管理、公开资料、排行榜及规范 ID 的播放/历史详情）；其他值回首页。公开资料 HTML 保留用户存在性/封禁检查及 404，SPA 内则展示 API 的不存在提示。

### 前端热更新

终端一在仓库根目录启动 Flask，终端二执行：

```bash
npm --prefix frontend run dev
```

在 Vite 输出的地址进入 `/login/` 或 `/register/`，默认 `http://127.0.0.1:5173/login/`。后端不是默认的 5000 端口时：

```bash
WM_API_PROXY=http://127.0.0.1:5000 npm --prefix frontend run dev
```

Vite 仅将 `/api`、`/socket.io`、`/health` 代理到 Flask，所有业务页面由 Vue/Vite 接管。代理不改写浏览器 Host/Origin，Socket 开启 WebSocket 代理；浏览器始终同源，CSRF/CORS 校验不放宽。开发环境的未知前端路径显示 Vue 的未找到页面，正式 Flask 路由返回真正的 404；旧 `/static/` 资源不再提供。

本地开发使用 HTTP、`WM_ENV=development`。生产 TLS 终止和可信反向代理配置仍属于部署阶段，不能简单把开发代理当作生产方案。

## 代码组织

```text
frontend/src/
  app/                  # 应用布局、路由、依赖注入、跨页面导航规则
  features/
    auth/               # 登录、注册、认证服务和密码表单校验
    profile/            # 资料修改
    management/         # 管理导航/布局及组件回归测试
    dictionaries/       # 词典列表/详情、词典/单词操作弹窗、CSV、协议服务
    users/              # 用户列表、管理操作弹窗及协议服务
    lobby/              # 大厅、卡片、创建/操作弹窗及摘要协议
    people/             # 公开资料、排行榜及只读协议服务
    games/              # 播放/详情、权威状态、连接生命周期、命令意图与共享展示
  shared/
    api/                # 同源 HTTP/Socket、会话状态、分页协议及运行时校验
    data/               # 分页/后台刷新、取消、防覆盖及只读轮询生命周期
    forms/              # 提交状态、取消及统一错误展示
    ui/                 # 字段、表单、提示、按钮、弹窗、表格及分页
    styles/             # 公共样式和设计变量
```

- 页面只组合控件并协调表单；不得复制 fetch/CSRF 处理或读取 Cookie 中的身份。
- Zod 定义关键响应的运行时结构，并推导 TypeScript 类型；不能用 `as SomeType` 代替验证。
- 会话只存内存，浏览器自动携带 HttpOnly Cookie，不使用密码哈希凭据或 localStorage 保存 token。
- 会话请求合并；过期请求不得覆盖新登录状态；账号、角色或 CSRF 会话身份变化时重建页面，避免显示另一个账号的草稿或管理数据。
- CSRF 失败可以刷新会话，但不会自动重放写请求。密码错误不清除有效会话，登录失效才触发重新认证；限流展示 `Retry-After`。
- 表单提交期间禁用控件，组件卸载时取消所属请求。取消网络等待不等于撤销已提交的后端事务，不能自动重复提交。
- 文本通过 Vue 默认转义；禁止将用户名、简介或错误消息交给 `v-html`。
- `next` 跳转仅允许明确的站内目标，不接受任意 URL。播放和详情都使用规范的数字 ID 白名单与 Vue 导航，保留服务端登录目标。
- 管理子页面按路由懒加载；权限展示使用服务端 `can_manage` 或当前公开角色，不推测历史归属。NULL 历史文本显示缺失提示，不自动填回数据库。
- `usePagedResource` 统一搜索、翻页、请求取消和递增版本校验；即使传输层忽略 abort，旧响应也不能覆盖新结果。失败时不保留可误操作的旧列表，重试只重读，不重放写入。
- 原生 `<dialog>` 管理焦点和键盘，关闭时恢复焦点，提交中不允许误关闭。表格/分页/错误提示共用组件，不再拼接管理页面 HTML。
- 写入成功先关闭操作弹窗，再独立刷新列表；刷新失败不把成功写入伪装成失败。重命名保留正在编辑的 CSV 草稿。文件读取使用严格 UTF-8，字节上限由详情 API 提供，逐行校验/原子导入仍由后端负责。导出生成下载链接并释放对象 URL。
- 大厅 `usePolling` 默认 5 秒，只重复读请求；不重叠慢轮询，离页清理定时器/事件监听，后台、离线、弹窗或手动关闭时暂停。恢复后重新读取，不使用缓存的成员关系自动跳转；已报名进行中对局由服务器独立查询，不依赖当前页。
- 后台刷新保留正在显示的列表，避免每次轮询移除按钮和焦点；读取失败清除旧行，显示错误。翻页/筛选会取消旧请求，晚到结果不能触发页面跳转。
- 大厅通过 `shared/api/gameCommand.ts` 校验版本与成功回执中的请求 ID；同一确认弹窗手动重试保留 ID/版本，重新确认或更换词典意图使用新 ID。服务器拒绝旧版本时提示关闭弹窗并刷新，不自动重放。Vue 播放页冻结原意图，跨 Socket/HTTP 手动重试保留 ID/参数/版本，即使当前状态已推进；换意图必须显式放弃原回执，再重新确认。只读订阅可排队，写命令 volatile、不缓存或自动重发；回执不填充状态/累加分数。细节见 [对局命令协议](GAME_COMMANDS.md)。
- 历史详情复用公共客户端/轮询和表格组件，`useGameState` 合并慢读取、离页取消并拒绝旧版本/进度回退。失败清除旧显示，保留进度基线；换身份重建页面。播放页复用同一资源接收校验后的推送，旧 GET 的失败或返回不能擦掉新推送；提交后等旧 GET 结束再发一次新读取。同版本允许资料更新，不把版本当完整 ETag。只展示已有 Perf 和当前 game_id 的结算记录，不填补缺失值或重算；答题表每页 20 行仅是客户端分页，接口仍读取全部记录，生产规模成本未验收。
- 大厅卡片使用服务端 `actions`，不复制开局人数/房主规则；写操作仍由后端完整验证。词典选择器复用分页/搜索，选择跨页保留。登录成功使用 SPA 导航到大厅；因身份变更而重建登录表单不能吞掉成功跳转，但离开表单后的迟到登录响应不得覆盖当前会话。

## 检查与测试

仓库根目录：

```bash
make check                         # Python、前端 lint/格式/类型/测试/构建
make check PYTHON=python           # 已激活环境或 CI 使用系统命令
make build-frontend
```

单独检查新前端：

```bash
npm --prefix frontend run check
npm --prefix frontend audit
```

`check` 含 ESLint、Prettier 检查、Vitest、vue-tsc 和 Vite 构建；修改格式可运行 `npm --prefix frontend run format`。Python 已接入锁定 Ruff 的全项目静态 lint/格式检查和 pytest；`make check-python-static` 只检查，`make format-python` 才改格式，详见 [Python 检查指南](PYTHON_CHECKS.md)。这不等于完整 Python 类型检查。

### 浏览器测试的范围与环境

在 Playwright 支持的系统安装 Chromium 后运行：

```bash
cd frontend
npx playwright install chromium
npm run test:browser
```

测试会先构建，再启动专用 Flask/Vite 子进程，默认端口 18766/18765。拒绝复用已占用的端口，不接管或关闭其他项目的服务；如冲突可设置 `WM_BROWSER_API_PORT` / `WM_BROWSER_UI_PORT`。

测试后端显式连接本机端口 1，不使用业务数据库。14 项检查中：

1. 构建后的页面、哈希资源、直接刷新、匿名管理深链接登录跳转和缺失路径，由真实 Flask 提供。
2. 匿名会话、HttpOnly CSRF Cookie、Vite 到 Flask 的同源校验走真实后端；以无效输入在访问数据库前终止登录请求。
3. 登录、简介修改、改密及深链接流程使用模拟 API。
4. 注册确认和 429 提示使用模拟 API。
5. 普通用户的共享词典只读、用户管理拒绝访问与详情刷新使用模拟 API。
6. 词典/单词增删改、弹窗 Escape/焦点恢复、CSV 错误行/UTF-8 文件/下载：使用 Flask 提供的构建产物及懒加载资源，API 仍为模拟。
7. 管理员密码确认、封禁/恢复和服务端筛选：同样验证 Flask 构建产物，API 仍为模拟。
8. 匿名排行榜/公开资料、分页序号、缺失值、文本转义及开发环境深链接刷新：模拟 API，部分使用 Flask 构建资源。
9. 大厅创建/报名/退出/取消/开始：Flask 构建产物、模拟 API；通过 SPA 导航到真实 Vue 播放组件。
10. 大厅轮询、离页清理、弹窗暂停及页外已开局对局跳转：模拟 API、Vue 路由及浏览器时钟。
11. 构建后的历史详情、大厅 SPA 导航、保存的评分/缺失值、文本转义与客户端分页：真实 Flask 构建资源、模拟 API。
12. 详情只读轮询、提前结束同步、拒绝回退、失败重读及离页清理：模拟 API/浏览器时钟。
13. 详情的真实 Flask 匿名 HTML 守卫、Vue 登录目标/Vite 深链接刷新、旧记录缺失显示、拒绝泄露未来英文及失效会话跳转：业务 API 仍模拟。

14. 名字颜色的全部色阶、hover/导航、3000+ 首字与 Unicode/HTML 转义：实际构建 CSS，业务 API 模拟；确认不产生逐用户颜色请求。

组件和浏览器测试共用 `frontend/testing/managementApi.ts`、`lobbyApi.ts` 和 `gameApi.ts` 的内存夹具；它们不是业务实现，不能验证 MySQL、CSV 解析或真实越权效果。181 项前端单元/组件用例（此前包含 25 项名字颜色边界/响应式/历史分离回归）另覆盖过期响应、卸载、分页契约、XSS、CSV 上限、写后刷新失败、轮询不重叠/离线/后台恢复和草稿保留，并覆盖请求 ID/版本契约、手动重试与新意图区分，以及详情协议、实际评分/缺失值、读取防回退、取消/换会话隔离、播放轮次提示、Socket 订阅/回执、断线/超时人工重试、终态导航。生产公开资料 HTML 的数据库存在性/封禁检查已在下述真实浏览器场景验证。

**以上 14 项仍不验证真实数据库业务。** 另有 252 项真实 MySQL 集成测试，以及独立真实浏览器入口：

```bash
make test-browser-mysql  # 新私有 MySQL + 实际 Flask/Socket.IO + Chromium
# CI 已有专用 WM_TEST_MYSQL_URL 且已构建时：make test-browser-live PYTHON=python
```

`tests/browser/conftest.py` 复用迁移夹具并启动随机回环线程化服务器；每个 spec 独立合成数据库，实际测试在 `frontend/mysql-e2e/`。现有 7 项 Chromium 场景和 6 项独立 Python 编排/SQL 核对，本批通过，不混入常规 811 项 Python。此前的导航、大厅/对局及管理姓名 computed CSS 断言全部保留；本批新增自然期限与 429/Retry-After 两个场景/两个编排，另独立复跑通过，见 [认证故障验证](AUTH_FAILURE_TESTS.md)。对局的 2 项覆盖 Socket/HTTP、实际 WebSocket 重连、丢失确认后的原 ID 重试和结算，详见 [播放页验证](GAME_PLAYING_UI.md#验证与边界)。此前 3 项覆盖注册/改密/登出、管理员重置/封禁/恢复、实际 Socket 撤销、词典/单词/CSV 维护和匿名/创建者/他人/root 权限，详见 [管理浏览器验收](MANAGEMENT_BROWSER_TESTS.md)。SQL 独立核对持久结果、软删除、会话和旧评分/历史未变；不是 API stub，也不使用 SQLite。多浏览器、所有网络/会话故障、生产代理和多 worker 仍未验收；本地完整工作区有 CI 配置但无托管执行结果，已合并的精简 GitHub 构建源码未包含测试/CI。

本机现已安装 Playwright 1.64.1 对应的 Chrome for Testing / Headless Shell 156.0.8078.4 及 FFmpeg，并用配套浏览器重跑 14 项检查通过；直接 `make test-browser` 即可，无需指定旧 Chromium 134。Ubuntu 20.04 仍不受官方支持，本次通过显式下载映射完成兼容安装，步骤及限制见 [测试环境指南](TEST_ENVIRONMENT.md#playwright-配套浏览器)。这不是操作系统升级或官方支持承诺。仍可用 `WM_BROWSER_EXECUTABLE=/absolute/path/to/chromium` 指定其他兼容浏览器。CI 使用受支持的 Ubuntu 和配套浏览器，仍需实际执行确认。Python 默认优先使用仓库 `.venv/bin/python`，可用 `WM_TEST_PYTHON` 覆盖。

## 下一批

继续按 [PLAN.md](../PLAN.md) 推进生产规模查询性能和更多浏览器/故障组合；合成基准、两个索引的代价评估/显式迁移及分页取行优化已完成，但已知热点搜索和用户列表计划仍有退化，实际生产负载尚未验收。Python 全项目格式/静态 lint、用户/管理员/词典核心浏览器权限矩阵、Vue 页面迁移、统一 Socket 与旧资源清理已完成，不重复列作待实现。旧题来源、其余转换工具、授权副本/恢复演练和生产部署仍独立待验收；本地功能通过不能替代这些工作。
