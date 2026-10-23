# 重构基线与当前接口约定

## 当前实现范围

工程基础、第 2 阶段用户/词典、幂等/版本、新局题目快照及参赛/答题关系、统一未来结算流水已接入。HTTP/Socket 共用命令、事务和 `legacy-v1`，已完成结算不转换、不重算。此前提供受限旧答案显式转换，仅复制既有快照/参赛父关系及完整答题字段，原成员工具仍只处理成员。此前迁移 Vue 历史详情、播放页和统一 Socket 客户端，保留 URL、守卫和业务协议，复用已有结果/本局结算展示，不重新判题或计算评分。用户、管理员与词典真实数据库浏览器核心流程及维护权限矩阵也已补齐。此前已接入 [Python 格式/静态 lint](PYTHON_CHECKS.md)；此前的 [列表基准/读优化](LIST_PERFORMANCE.md) 已完成；此前新增两个非唯一列表索引、ID 分页取行与零计数短路。此前 N1 首轮在搜索 SQL 内加入单行边界聚合，只对无搜索用户首页直接读取公开字段；公开契约不变，head 仍为 `0008_list_indexes`。后续已完成[名字颜色修复](NAME_COLORS.md)：统一 Rating 显示组件，并给对局/大厅姓名摘要补充当前公开 Rating，不改评分和历史。六分布/34 场景及剩余退化见 [N1 查询记录](LIST_SEARCH_READS.md)，本批 [N1 后续](LIST_FOLLOWUP.md) 重建当前接口基线并保留未采用候选，同时补充 [N2 自然到期/限流恢复](AUTH_FAILURE_TESTS.md) 验证；业务源码不变，迁移保护仍见 [列表索引指南](LIST_INDEXES.md)。

**没有执行真实业务库迁移、数据修复或历史评分重算。** 已提供 SQLAlchemy 元数据和八版显式 Alembic 迁移；运行时仍使用 PyMySQL。数据库须为 MySQL 8.0.16+ / InnoDB，不支持 MariaDB。升级步骤及回滚边界见 [迁移指南](AUTH_MIGRATION.md)。[旧表 SQL](../tests/integration/legacy_schema.sql) 仅供结构参考和隔离测试，不是生产迁移脚本。

| 模块 | 当前情况 | 后续工作 |
|---|---|---|
| 注册、登录、用户资料 | 服务端会话、scrypt、旧密码升级、CSRF、撤销与限流；MySQL 和核心浏览器流程通过 | 更多浏览器/会话故障组合 |
| 管理员用户管理 | root 权限、事务、撤销会话、Vue 页面及分页/搜索；真实浏览器重置/封禁/恢复与越权拒绝通过 | 更多并发/故障组合 |
| 词典、单词、CSV | 创建者/root 维护、标准 CSV、全量校验/事务导入、分页/搜索；真实浏览器 CRUD/CSV 及维护权限矩阵通过 | 生产查询性能验收 |
| 对局 | 共用事务/幂等/版本、自动结算、新局题目快照及参赛/答题关系、未来结算流水；显式参赛及受限旧答案转换工具；大厅摘要分页 | 剩余转换工具、授权副本转换及旧题来源审查 |
| 实时通信 | 同源、会话 + CSRF、逐事件验证、提交后广播；Vue 私有连接/重订阅与人工原请求重试，真实浏览器 Socket/HTTP 关键路径通过 | 更完整故障矩阵、多 worker/代理与生产部署 |
| 页面 | 全部业务页面已迁移 Vue；公共组件、HTTP/Socket 客户端、分页及轮询，旧实现已清理；用户/管理员/词典核心浏览器矩阵通过 | 更多浏览器/故障组合及生产规模性能 |

可维护性要求及进度见 [PLAN.md](../PLAN.md)，开发/构建及路由边界见 [前端指南](FRONTEND.md)。已删除全部旧模板、脚本、共用 CSS/导航/认证适配器和旧 JS 测试，相关功能回归由 Vue/后端与浏览器用例承担。没有全站 SPA fallback。

## 认证与错误约定

- 不再读取客户端 `uid/pwhash` 作为身份，旧 Cookie 会被清除；伪造请求中的 `uid/type/ownerid` 不能改变操作者或新词典归属。
- 首先 `GET /api/session`，返回 `success/authenticated/user/csrf_token`。匿名客户端也会获得与 Cookie 绑定的签名 CSRF token。
- 所有 POST/PUT/DELETE 请求包括登录、注册，必须带 `X-CSRF-Token`，使用 JSON 请求体。同源 Cookie 由浏览器自动携带。
- `POST /api/login`：`username/password`，成功设置 HttpOnly 会话 Cookie，并返回更新后的公开用户及 CSRF token；不返回原始会话 token 或密码哈希。
- `POST /api/register`：`username/password/introduction`，成功 201；不能注册为 root。
- `POST /api/logout`：撤销当前会话；`GET /api/user/<id>`：公开资料，不含密码字段。
- `POST /api/user/<id>/update`：只能修改本人，接受 `introduction`，或 `current_password/new_password`。改密返回 `reauthenticate=true` 并撤销全部会话；仅改简介不需要密码。
- `GET /api/admin/check`：返回已登录用户的角色，不再是旧 POST；`GET /api/admin/users?include_deleted=true` 仅 root，可分页/搜索。
- `POST /api/admin/user/<id>/reset-password|delete|restore`：仅 root，重置参数为 `new_password`；拒绝用管理接口操作自己，恢复也不会复活旧会话。
- 失败响应：`success=false, code, message`，可带 `details`；参数 400、认证 401、权限/CSRF 403、不存在 404、冲突 409、超限 413、限流 429、数据库未就绪 503。限流含 `Retry-After`。
- API 和 HTML 响应 `Cache-Control: no-store`；日志不主动记录请求体、Cookie、查询参数。超时或 CSRF 失败不自动重放写请求。

主页、管理页、修改资料和对局页需要登录。普通用户可以进入管理页维护词典，但不能查看用户管理表；公开资料和排行榜保留公开访问。

## 列表分页与搜索

`GET /api/dicts`、`GET /api/dict/<id>/words`、`GET /api/admin/users` 统一接受：

- `page`：从 1 开始，最多 1,000,000；`per_page`：默认 20，最多 100。非法数值及重复的已识别参数返回 400。
- `q`：默认空，去除两端空白后最多 100 字符。词典按名称、单词按英文/中文、用户按用户名做字面包含搜索；`%`、`_`、`!` 不作为通配符，大小写/重音语义由数据库排序规则决定。
- 用户列表另有 `include_deleted=true|false`，默认 false，大小写不敏感；其他值或重复参数返回 400，仍要求 root。
- 响应保留 `dicts` / `words` / `users` 数组，新增 `pagination: {page, per_page, total, pages}`；总数是筛选后的数量。空结果为第 1 页，共 1 页；超过末页时收敛至末页。
- 词典/用户按 ID 倒序，单词按 ID 正序。跨请求翻页不承诺一致快照，并发增删后可刷新。CSV 导出仍是整个词典，不受分页和筛选影响。

**兼容变化：列表不再默认返回全部记录。** 项目内消费者已适配；大厅词典选择器已改为 Vue 分页/搜索，切换页码不会丢失已选词典。外部调用方需遍历分页，前后端及静态资源需一起发布。已新增参赛关系及来源/状态索引；此前的 22 场景合成基准和三处读优化见 [性能记录](LIST_PERFORMANCE.md)。`0008` 提供 word 作用域/ID 与 user 评分顺序索引。单词和用户搜索/深页先分页 ID 再读字段；本批 N1 无搜索用户首页（收敛 offset=0）直接读取公开字段，单词非空搜索在 COUNT/页 SQL 内加入同词典有效单词的单行 MIN/MAX 聚合。精确零计数跳过页查询，结果、权限及同一快照不变，没有新增客户端查询数。大词典搜索改善，但稀疏、高删除比例和部分小词典仍有代价；详见 [N1 记录](LIST_SEARCH_READS.md)，原索引代价见 [索引记录](LIST_INDEXES.md)。词典先取页再一次汇总本页单词数，三次读取保持同一一致快照；无搜索的大厅 COUNT 不关联词典，名称搜索仍保留来源 CASE。包含搜索、精确计数、大 OFFSET 的生产性能仍待验证，响应限长不等于查询成本恒定。

## 词典与 CSV

- `GET /api/dicts`：登录用户可读，分页返回 `ownerid/can_manage/word_count`。
- 新增 `GET /api/dict/<id>`：返回 `dict: {id, dictname, ownerid, can_manage}`，以及从服务器配置读取的 `csv_limits: {max_bytes, max_rows}`。前端按这些上限预检字节数，真正权限及 CSV 解析仍在后端。
- `POST /api/dict`、`PUT/DELETE /api/dict/<id>`：名称参数 `dictname`；创建者或 root 可维护。旧 `ownerid=NULL` 词典仅 root 可维护。
- `GET /api/dict/<id>/words`、`POST /api/dict/<id>/word`、`PUT/DELETE /api/word/<id>`：单词字段为 `english/chinese`；词典删除同时软删除其单词。
- `POST /api/dict/<id>/import-csv`：`csv` 文本；`GET /api/dict/<id>/export-csv`：返回 `filename/content`。
- CSV 为 UTF-8，可含 BOM，无表头，两列依次英文、中文；支持引号、逗号和带引号换行。名称/单词字段最长 255 字符。
- 默认上限 512 KiB、5000 条非空记录；任一行错误时整批不写入，最多报告 50 个行错误。行号按记录的物理起始行计算；事务失败也不会部分导入。
- 导出保留字段内容，不自动改写公式样式文本；处理来源不可信的 CSV 时使用文本编辑器，或以文本列导入电子表格，避免执行公式。

## 公开资料与排行榜

- `/user/<id>/`、`/leaderboard/` 仍允许匿名访问，现由 Vue 展示。公开资料继续调用 `GET /api/user/<id>`；直达资料 HTML 仍检查用户是否存在/封禁，保持原 404。
- 新增 `GET /api/leaderboard?page=1&per_page=20`：返回 `users/pagination`，每项仅有 `id/username/introduction/rating/rank`，不含密码或会话字段。
- 保留原前 100 名范围，按 Rating 降序、ID 升序打破同分；分页的 `rank` 为该顺序的全局序号。末页不足一页时不越过第 100 名；非空 `q` 暂不支持，返回 400。
- NULL Rating 保持缺失，不填 0、不重算历史数据。服务现在一次有序读取至多 100 条公开记录，用其长度得出精确榜单总数再切页；没有全量用户 COUNT；`0008` 提供 `(deleted,rating DESC,id)` 索引供此顺序读取使用，仍不把 LIMIT 等同于任何分布下的固定成本。

## 对局与实时接口

- `GET /api/game/list`：现默认分页，接受通用 `page/per_page/q`，`q` 按展示词典名做字面搜索（新对局用快照名称，旧对局用现有名称）；新增 `status=all|waiting|running|finished|cancelled`，默认 all。非法/重复状态参数返回 400。
- 列表返回 `games/pagination/active_game_id`。每个摘要仅含 `id/version/dictid/dictname/status/owner/users/is_joined/actions`，不再携带整份 `wordlist/result/perf/ratingdelta`；只批量查询当前页涉及的用户，用户摘要为 `{id, username, rating}`，rating 仅是读取时的当前公开余额，不是本局成绩；封禁/未知状态时为 NULL。缺失参赛者保留 ID、NULL 用户名/Rating，不悄悄移除。
- `actions` 的报名/退出/开始/取消提示与命令共用前置检查，但不替代完整事务、权限和历史数据校验。写接口及 HTTP/Socket 共享服务未替换。
- `active_game_id` 是当前用户已报名、进行中且 ID 最大的对局，不受分页/筛选影响。关系模式用 `(user_id, game_id)` 索引查找；旧 JSON 路径限定 `participant_mode=0`，两者选最大 ID。模式 1 的存档 JSON 不参与成员判断。当前页关系行批量读取，缺行/数量/顺序异常返回 `invalid_game_participants / 409`，不回退旧 JSON；旧模式仍严格解码，异常为 `legacy_data_error`。功能已通过真实 MySQL，生产规模性能仍待验证。
- 大厅默认 5 秒只读轮询，暂停/恢复、离页清理和旧响应防覆盖由公共组合式函数处理；不自动重试写请求。已取消对局可在单独标签查看。
- `GET /api/game/<id>` 的 `owner/users` 姓名摘要也包含可为空的当前公开 `rating`，仅用于显示颜色；既有 `userrating` 的历史和本局结算字段不变，不从它们猜当前颜色。
- `GET /api/game/<id>`：权威状态，含 `version/status/current_index/next_turn/next_word`。此前已增加 `question_source: snapshot|legacy_live`，Socket 状态同样包含；播放页和详情均已迁移 Vue，明确显示题目来源。
- `POST /api/game/create`：`dict_id`，创建成功 201；首次成功创建在同一事务保存题目、名称快照和参赛关系，新局 `game.users/result=NULL`，答案来源为关系模式、数量为 0。快照仅供读取，无编辑/删除接口；英文/中文与源字段精确相同，不在捕获时修正异常文本。NULL 名称保留，不回退到后来改过的源名。
- `POST /api/game/<id>/join|leave|start|end|cancel`；`POST /api/game/<id>/answer`：`word_id/answer`。
- Socket 握手传 `auth: {csrf_token}` 并携带同源会话 Cookie；每个 `game.subscribe/join/leave/start/answer/end/cancel` 事件也带 `game_id/csrf_token`，答题另带 `word_id/answer`。
- 写命令可带 `request_id`（UUID v4）和 `expected_version`（0–2147483647 的 JSON 整数；创建不接受）。成功结果增加 `version`，提供 ID 时回传 `request_id`。相同用户/ID/有效命令重放原结果，不重复计分；不同载荷复用 ID 为 `request_id_conflict`/409，新命令版本落后为 `stale_game_version`/409。兼容省略元数据，但相应地不提供结果重放/版本前置检查。
- 每个事件重新校验会话，登出、改密及管理操作提交后断开相应连接；广播前也会剔除失效连接。服务端事件仍为 `game.update`、`game.answer_result`、`game.error`。
- 状态值等待/进行/结束/取消为 `-1/0/1/2`；已结束对局发起新结束命令返回 `already_finished=true`，不推进版本。用原请求 ID 重放则返回原成功回执，包括原来的 `already_finished` 和版本，不重复结算。
- 未答题单词不返回 `english`；已答题允许显示标准答案。登录用户仍可通过共享词典查词，**不是完整防作弊方案**。

客户端仅按权威状态展示成绩，不在答案回执再次加分。通知失败不会撤销已提交命令；轮询/重连恢复状态。原回执可能早于当前状态，不应作为新状态覆盖；完整协议、事务锁顺序及客户端意图边界见 [对局命令协议](GAME_COMMANDS.md)。版本只排序对局命令及显式参赛/答案转换，不是整个返回对象的 ETag。新对局等待、进行和历史状态均与词典删改隔离；旧对局尚未恢复原题。快照损坏为 `invalid_game_snapshot / 409`，不回退到当前词典；创建遇到异常源文本为 `invalid_dictionary_data / 409`。旧题引用缺失为 `legacy_data_error`，不缩短题目列表。存储、并发捕获语义、清单容量限制和旧数据边界见 [题目快照指南](GAME_QUESTIONS.md)。

## 参赛关系与转换边界

`game_participants.py` 只适配存储，不复制房主、轮次或评分规则。模式 1 使用唯一成员/顺序约束、对局/用户外键和数量检查；报名/重排先按用户 ID 升序取共享锁，避免与评分排他锁倒置。关系、人数、版本与回执原子提交，既有成员时间不因重排改变。

`convert-game-participants --game-id <id>` 默认在只读事务内检查并报告。授权审查后使用 `--apply --expected-version <version>`，锁定对局重新校验；只复制原成员顺序并加一次版本，保留原 JSON 作不再更新的存档，不改答案、评分、用户历史或旧回执。未知历史加入时间为 NULL；已规范化的局不重复转换。工具仅审查参赛数据，不替代完整审计；不会自动转换业务数据库。详情及命令示例见 [参赛关系指南](GAME_PARTICIPANTS.md)。

## 答题关系边界

`0006_game_answers` 增加 `answer_mode/count` 和 `game_answer`。新局每题只追加一行，题序主键防重复、复合外键绑定本局快照和参赛者，保留实际 `perf_delta/perf` 的 DOUBLE 精度及规则版本。原结果协议不变；时间仅记录写入时点，不声称提交时间。答案、数量、用户历史、结算、版本及回执同事务提交，FK 写入位于有序评分用户锁之后。

关系模式不读取旧 `result` JSON，读取验证完整已完成前缀和字段，损坏为 `invalid_game_answers / 409`，只读审计不输出答案内容。未转换的旧答案保持 JSON 路径，不自动转换或重算；新的实际结算使用下述流水，旧评分和其余 JSON 仍待转换。迁移、约束、时间与发布边界见 [答题记录指南](GAME_ANSWERS.md)。

`convert-game-answers --game-id <id>` 默认只读，仅接受已有完整快照、关系成员及完整实际答题字段。应用需 `--apply --expected-version <version>`，对局锁内重验，再按升序用户共享锁插入；答题行、模式/数量和版本加一原子提交并回读核对。拒绝重复键、缺失/额外字段、无法精确保存的分数或部分副本；不重新判题、推算评分/规则版本或从当前词典造题。未知作答时间为 NULL；原 `result` 字节保留作不再更新的存档，用户余额/历史、结算和旧回执不变。已规范化不重复写入，后续正常答题仅追加。提交确认丢失时先只读核对，不误报回滚；`ready` 不是全局审计或评分数学证明。完整拒绝范围与流程见 [旧答案转换指南](ANSWER_CONVERSION.md)。

## 结算与评分流水

`0007_game_settlements` 增加 `settlement_mode`、一局一个的 `game_settlement` 和每局每人唯一的 `game_rating`。保存最终 Perf、结算前后 Rating、增量、规则版本及时间；零答案也有空结算头，未答题者没有评分行，零增量的答题者仍有行。用户余额和 `rating_ledger_id` 最新流水引用原子更新；流水外键指向结算和用户，最新引用也有外键。

未来实际结算只有一条写入路径，不再写旧评分 JSON。历史读取保留 `user.ratinghistory` 前缀，再按流水 ID 追加新记录，`userrating` 公开形状不变；同一用户的顺序由用户锁保证，不按对局 ID/墙钟排序。主键当前读避免等待用户锁前建立的旧 MVCC 快照，NULL 指针不扫描空范围锁，也不锁其他对局。结算、余额/指针、答案、版本和回执同事务，坏引用/人数/余额链为 `invalid_game_settlement / 409`，计算超出 INT 范围为 `rating_out_of_range / 409`。

旧已结束对局不产生新流水；旧未结束局在正常结算时切换结算来源，不改变其题目、成员或答案来源。旧评分 JSON 保留原字节；不是历史转换或重算。详情见 [结算流水指南](GAME_SETTLEMENTS.md)。

## Vue 历史详情

`/game/<id>/detail/` 保留服务端与 Vue 登录守卫，使用原状态 GET API；大厅历史链接采用 SPA 导航，播放页原结束跳转继续有效。数字 ID/登录目标/深链接及缺构建处理已适配；旧历史模板、独立脚本和对应旧 JS 测试已替换；播放页及共用旧资源也已清理。

`features/games/` 将协议、读取状态和信息/评分/答题展示分离，复用公共客户端、表格、分页及只读轮询。缺失正确性、Perf、规则版本不推测；Perf 取最后已存个人答题值，Rating 按本局 ID 选择增量/结算后值，不把其他局最新历史或当前余额当作本局结算。题目引用异常不补查当前词典；明确快照/旧题来源，不显示未答英文。分页只减少已读答题的渲染行数，不是数据库分页。

读取合并、离页/身份变化取消、防版本/进度回退和轮询暂停/清理已验证；失败清除旧显示，恢复只重读。详情无写命令/Socket，不重算评分，也不代表旧数据已通过审计。完整边界见 [历史详情指南](GAME_HISTORY_UI.md)。

## Vue 播放页与 Socket

`/game/<id>/` 保留服务端/Vue 登录守卫，和大厅/详情之间采用 SPA 导航。当前题目/轮次只使用权威状态，成绩和记录复用详情组件。`shared/api/socket.ts` 的私有 Manager 在每次连接/重连重验会话，只读订阅可在握手忙时排队；写命令 volatile、禁用自动重试。未订阅或关闭连接时新命令使用 HTTP，已经尝试的命令不自动换传输再发。订阅/报名的房间加入若遇连接已关闭，只忽略该断连竞态，不掩盖其他房间错误。

`useGameCommand` 冻结 UUID、业务参数及审查版本，超时/断线后保留意图供人工重试；状态推进不擅自改变原意图，放弃等待也不撤销事务。只使用发送关联且匹配 ID 的 ack，不用重复/无归属事件结束新请求。回执不是状态，写成功后刷新失败不能称为写失败。`useGameState` 接收校验后的 GET/推送并防回退；提交后等待旧 GET，再读取新快照。离页/账号/角色/CSRF 会话变化清理请求、连接和定时器。完整实现及限制见 [播放页指南](GAME_PLAYING_UI.md)。

## legacy-v1 评分基线

公式源自原 `socket_game.py`，随机数范围为闭区间，具体随机增量写入每条答案；每条新答案标记 `rating_version=legacy-v1`。

- 正确：个人连击与全局连击增加，增量为 `1500 / clamp(rating,1300,1700) × randint(10+ceil(combo^0.7),15+5×ceil(combo^0.7))`。
- 错误：连击归零；旧实现清零后计算惩罚，实际随机范围为 1～5。
- 首次正确或错误答案从 Rating 基线计算；前五场最低基线为 1500。继续答对从上次 Perf 累加。
- **旧实现答错会重新从 Rating 基线计算 Perf，而不是从前一题 Perf 扣除；有意保留并测试这一行为。**
- Rating 按原来的正负方向系数和差值的 `0.95` 次方调整，使用 Python `round`。
- 未答题用户不调整 Rating；同一场对局只记录一次游戏参与历史并只结算一次。
- 旧 HTTP 答案缺失 Perf 时返回 `legacy_data_error`，不推算、不静默改写，需要审计后单独处理。

## 数据审计

```bash
python -m flask --app app audit-legacy --output legacy-audit.json
```

在 MySQL 只读事务内检查 JSON 形状、引用、精确重复用户名、缺失 Perf、异常状态、重复结算、题目快照、参赛/答题、结算/评分关系完整性及余额链/最新指针。兼容迁移前结构；快照对局不要求源单词/词典仍存在，关系模式不把旧成员/答案存档当作当前状态；旧模式仍检查原引用。报告只含实体 ID 与问题类型，不输出密码、用户名、题面或答案。无问题退出 0，有问题退出 1。真实旧数据审计尚未执行；迁移另按现有数据库排序规则检查用户名冲突。

## 测试与限制

```bash
make check  # 默认 .venv/bin/python；可用 PYTHON=python 覆盖
# 浏览器安装/环境要求见 FRONTEND.md
make test-browser
make test-browser-mysql  # 独立真实 MySQL/双用户浏览器场景
```

已补齐本机隔离实例和配套浏览器，安装记录与清理边界见 [测试环境指南](TEST_ENVIRONMENT.md)：

```bash
make test-mysql         # 临时实例，只运行数据库测试
make check-with-mysql   # 临时实例，全套检查；不再跳过数据库测试
```

普通 `make check` 未配置数据库时仍明确跳过。使用另一专用实例时，显式启用：

```bash
export WM_TEST_MYSQL_URL='mysql+pymysql://test_runner:password@127.0.0.1:3306'
python -m pytest -m mysql -q
```

**仅使用专门测试实例和账号，禁止使用生产实例。** 测试创建随机 `wm_test_<uuid>` 数据库，加载旧结构/数据、执行迁移，并在结束时删库；账号需建库/删库及 DDL 权限，不使用 URL 指定的业务库。不使用 SQLite 替代事务、唯一约束和行锁。

252 项集成测试覆盖认证/词典、分页/大厅/排行榜、迁移、幂等/版本、题目快照、参赛/答题关系、结算流水、成员与受限答案转换；此前 N1 新增 14 项六分布/有符号 ID/搜索范围/首页快照回归，颜色修复新增 1 项当前姓名 Rating/可见性/只读保留回归；本批新增 6 项自然会话到期、Socket 复核/广播前剔除、原回执保留与真实限流窗口恢复回归。此前索引批次新增的 31 项升降级/数据保留/部分 DDL/等待、分页快照及写探针恢复回归均保留。此前新增的 2 项真实 MySQL/HTTP 用例，验证历史详情守卫/构建入口、本局与后续局的评分历史区分、未答英文隐藏、旧字段/用户引用缺失保留及普通读取不修复数据。252 项在本机 MySQL 8.0.42 全部通过，没有跳过。使用合成旧结构与数据，不是业务库副本，也不是浏览器。CI 配置使用 MySQL 8.0，但当前没有 CI 执行结果。

本次常规检查共 **829 项 Python（577 单元 + 252 MySQL）、181 项 Vitest 单元/组件测试**通过；105 个 Python 文件接受锁定 Ruff 的 lint/格式检查，前端 lint/格式/类型/构建通过。上一批新增上述 6 项 MySQL 回归，本次本地启动入口新增 18 项单元回归；不以查询计划/基准代替业务一致性证明；旧 JS 实现及独立回归入口已移除。14 项 Chromium 检查仍模拟业务 API（含新增颜色检查），大厅播放落地改为真实 Vue 路由，不能据此验证数据库业务。

另有 `make test-browser-mysql` 的 **7 项真实 MySQL/Chromium 场景及 6 项 Python 编排/SQL 核对**，本批通过；新增 2 项自然期限/限流恢复场景及其独立 SQL 编排，又与新增 6 项 MySQL 一同独立复跑通过。此前 5 个核心场景曾多轮通过。2 项对局场景覆盖登录、词典创建/CSV、开局、Socket/HTTP、实际断线重连、提交后确认丢失的原 ID 重试与结算。此前 3 项管理场景覆盖注册/改密/登出、管理员重置/封禁/恢复、真实 Socket 撤销、词典/单词/CSV 及维护权限矩阵，详见 [管理验收范围](MANAGEMENT_BROWSER_TESTS.md)。共用编排按 spec 隔离数据库并保留各自失败产物；SQL 独立核对持久结果/评分证据和未改历史。本批新增范围与未覆盖组合见 [认证故障验证](AUTH_FAILURE_TESTS.md)。不模拟成功业务响应或评分，也不把 6 项编排重复计为业务场景。此前的 51 项前端关键生命周期用例曾连续三轮通过。

普通 Python 默认只收集 `tests/unit`、`tests/integration`；真实浏览器编排位于 `tests/browser`，需独立命令和浏览器依赖，不混入上述 829 项。新增 `tests/startup` / `make test-startup` 单独运行 1 项生命周期编排（两个 Chromium 阶段），核对独立本地实例的 CSS/HTTP/Socket、应用及 MySQL 重启后的数据/会话/回执保留，见 [本地启动指南](LOCAL_START.md)，不接管用户持久目录，也不替代持续打开浏览器的故障矩阵。`tests/performance` 也需独立 `make benchmark-mysql`：每次 1 项编排/34 个实际服务读负载；此前 N1 六种 medium 分布及 large 前后全部结果摘要一致，有复跑及 smoke 验证；颜色修复增加 Rating 后已通过 smoke/1，本批再按当前接口建立七组基线并复测候选，写探针后每组核对 34 个摘要，仍未采用新 SQL/索引；方法/剩余退化见 [N1 后续](LIST_FOLLOWUP.md)，不能与旧响应摘要混比。索引迁移和可选写探针基础仍见 [索引指南](LIST_INDEXES.md)。本地完整工作区有 smoke 基准及报告上传的 CI 配置，但无托管执行结果；已合并的 GitHub 精简构建源码不含测试和 CI。本机使用锁定 Playwright 1.64.1 对应的 Chrome for Testing 156.0.8078.4；Ubuntu 20.04 仍非官方支持系统。

生产规模查询性能、更多浏览器/网络/会话故障组合、授权旧数据副本迁移/恢复演练及生产部署仍待完成。当前版本不应直接作为生产安全版本上线。
