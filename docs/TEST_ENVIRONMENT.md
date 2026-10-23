# 本地隔离测试环境

本机已补齐 Python/npm 依赖、用户目录下的 MySQL 8.0 和项目锁定 Playwright 对应的浏览器。**不安装系统服务、不需要 sudo、不连接业务库。** 数据库实例只在测试命令执行期间存在。

## 日常命令

在仓库根目录执行：

```bash
make test-mysql         # 启动临时 MySQL，运行 231 项数据库集成测试，随后关闭并清理
make check-with-mysql   # Python/前端静态检查和完整回归，数据库测试不再跳过
make check-python-static # 仅 Python lint/格式检查，无需数据库，不改文件
make format-python      # 明确格式化 Python；不自动修复 lint
make test-browser       # 既有模拟 API 浏览器回归，使用配套浏览器
make test-browser-mysql # 新私有 MySQL + 实际用户/管理/词典/对局 Chromium 流程
make benchmark-mysql    # 可选：新私有 MySQL + 合成列表查询基准，默认 medium / 3 次测量
```

`make check` 现先执行锁定 Ruff 的 Python lint/格式检查，再运行 pytest 和前端检查。数据库选择行为不变：使用调用者明确设置的 `WM_TEST_MYSQL_URL`；未设置时跳过数据库用例。规则、范围和显式格式化方式见 [Python 检查指南](PYTHON_CHECKS.md)。默认 Python 仅收集 `tests/unit` 与 `tests/integration`，真实浏览器编排在 `tests/browser`，不因未配置浏览器而跳过常规检查。CI 使用其专用 MySQL service，构建并安装浏览器后运行 `make test-browser-live PYTHON=python`，不要求安装本地 MySQL 运行器二进制。另已配置 `make benchmark-live PYTHON=python PERF_ARGS="--list-perf-size=smoke --list-perf-runs=1"` 和合成报告上传，常规 pytest 不收集 `tests/performance`；CI 仍无实际执行结果。

自定义测试命令：

```bash
.venv/bin/python scripts/with_test_mysql.py -- \
  .venv/bin/python -m pytest tests/integration/test_game_mysql.py -q -p no:cacheprovider
```

### 隔离与清理

[`scripts/with_test_mysql.py`](../scripts/with_test_mysql.py)：

- 拒绝以 root 运行。默认二进制目录为 `~/.local/share/wordmachine-test/mysql/usr`，可用 `WM_TEST_MYSQL_BASEDIR` 指定另一套兼容 MySQL 二进制及资源目录，不接受现有数据目录。
- 每次创建新的 `/tmp/wm-mysql-*`（权限 0700）；使用 `--no-defaults`，不读取系统 MySQL 配置。
- 初始化时禁止 TCP，只通过私有 Unix socket 设置随机密码。之后仅监听 `127.0.0.1` 的动态空闲端口，禁用 MySQL X 端口；端口被抢占就启动失败，不连接已有服务。
- 测试账号仅获 `wm_test_*` 数据库权限，前缀中的下划线按字面匹配。随机密码不写进仓库、命令参数或日志；连接 URL 只注入测试子进程。
- 覆盖继承的 `WM_TEST_MYSQL_URL`，清除继承的 `WM_DB_*`，将未配置应用的数据库回退地址固定为 `127.0.0.1:1`。只有 pytest 集成夹具从测试 URL 创建随机数据库；**不能用这个运行器直接为开发网站或 Alembic 配置数据库**。
- 正常退出、测试失败及可处理的中断都会停止自己的子进程并清理临时数据。只操作自己创建的进程，不读取 PID 文件后杀进程、不使用 `pkill mysqld`。测试命令的失败状态会传回调用者。
- SIGKILL、断电等无法执行清理；若出现残留，先确认进程和目录确属该次测试再人工处理，不能按通配符删除或关闭其他服务。

## 可选列表查询基准

`make benchmark-mysql` 复用上述私有实例和合成旧库/迁移夹具，记录 34 个真实服务读负载的 SQL、绑定参数、估算计划、会话访问计数、原始耗时与结果摘要。可选 smoke/medium/large 和 `--list-perf-distribution=standard|spread|sparse|dominant|deleted|wide`，默认 standard、一次预热、三次测量；仅在夹具准备阶段刷新合成库统计信息，测量服务读取不写业务数据。不是 HTTP 并发负载，也不使用毫秒阈值决定通过。

基准默认迁移到当前 `0008_list_indexes`；可显式 `--list-perf-revision=0007_game_settlements` 创建索引前合成结构，仍使用当前 SQL。报告新增索引定义/空间估算；`--list-perf-write-costs` 另行开启 5000 行实际 CSV 导入和 100 行合成 Rating UPDATE 的已提交写探针，清理后核对结果。它不是线上写负载或真实评分结算，细节见 [索引指南](LIST_INDEXES.md)。

报告默认在已忽略的 `performance-results/`，可显式选择不存在的输出路径；拒绝覆盖文件/符号链接。同规模、分布参数、生成器摘要、方法、记录环境和结果一致时，`python -m tests.performance.compare BEFORE AFTER` 才输出耗时对照；跨迁移必须额外给出准确 `--revisions 0007_game_settlements 0008_list_indexes`，仅放行这对版本差异，不忽略其他环境/结果。`benchmark-live` 仅供已有专用测试 MySQL，缺 URL 直接拒绝，禁止生产实例。完整规模、重现命令、测量与剩余扫描成本见 [列表性能记录](LIST_PERFORMANCE.md)。

基准每次 **1 项编排 / 34 个读负载**，不混入常规 829 项 Python 或真实浏览器数量；重复采样不是新增功能场景。此前 N1 六种 medium 分布及 large 各 34 个前后摘要一致，写探针后再次一致；large 另复跑，sparse/deleted 另以五次采样复核，smoke/1 私有实例入口通过。大词典和常见用户首页改善，但稀疏、高删除比例及部分小词典仍有退化；详细证据见 [N1 查询记录](LIST_SEARCH_READS.md)，不是生产性能验收。此前[名字颜色修复](NAME_COLORS.md)后 34 场景 smoke/1 通过；本批已按含 Rating 的接口重新建立七组 34 场景基线、写探针后核对摘要，并保存候选及原方案复测，见 [N1 后续](LIST_FOLLOWUP.md)。未采用新的 SQL/索引，不跨接口版本混比，也不把波动算作优化收益。此前 22 场景/740 测试及索引迁移数据属于 [索引批次历史记录](LIST_INDEXES.md)。

## 真实数据库浏览器编排

`make test-browser-mysql` 先构建前端，再由同一隔离运行器启动 MySQL，运行 `tests/browser/`。`conftest.py` 复用合成旧表/用户和显式迁移夹具，每个 Python 用例使用独立数据库；线程化 Werkzeug 监听 127.0.0.1 随机端口。Node/Playwright 子进程只取得站点地址，不接收 MySQL URL 或 `WM_DB_*`。

现有 7 项 Chromium 场景：`game.spec.ts` 的 2 项对局场景共用一个测试库；`auth.spec.ts`、`admin.spec.ts`、`dictionaries.spec.ts`、`expiry.spec.ts`、`rate-limit.spec.ts` 各一项并各自独立测试库。各用户使用独立 Cookie 上下文，实际 HTTP/Socket/数据库业务不伪造成功响应；直接越权探针也在浏览器内同源 fetch。6 项 Python 编排分别独立 SQL 核对最终持久结果，不计入常规 Python 数量，也不重复计算成浏览器业务场景。

每个 spec 默认 210 秒编排超时，场景 90 秒、动作等待 15 秒；失败/超时/可处理 SIGTERM 回收自己创建的浏览器进程组、服务器及测试库，SIGKILL/断电仍不保证清理。失败 trace 分别保存到 `frontend/test-results/mysql/<spec 名>/`，后续 spec 不覆盖前面的诊断；其中可能含合成凭据/Cookie，只能作为受控测试产物。详细范围见 [管理浏览器验收](MANAGEMENT_BROWSER_TESTS.md)、[播放页验证](GAME_PLAYING_UI.md#验证与边界) 和 [认证故障验证](AUTH_FAILURE_TESTS.md)。

`test-browser-live` 只供已有专用测试 MySQL 的 CI/受控环境使用，必须显式提供 `WM_TEST_MYSQL_URL`；该 Make 入口在没有 URL 时直接拒绝；不要绕过入口，把直接运行 pytest 时夹具的跳过误报为通过。推荐日常只用自动隔离的 `test-browser-mysql`。

## 本机一次性安装记录（Ubuntu 20.04 x86-64）

### Python 与 npm

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
uv pip check --python .venv/bin/python
npm --prefix frontend ci
```

上述环境修复没有升级运行时依赖；后续 Python 检查批次仅新增开发依赖 Ruff 0.14.10，安装版本必须匹配 `ruff.toml`。前端按锁文件重装。Python 需 3.10+，本机使用 `.venv` 的 3.11，而非系统 Python 3.8。

### MySQL，无系统安装权限时

本机从已配置的 Ubuntu APT 仓库下载包并解压到用户目录，没有执行 `apt install` 或修改 `/etc/mysql`：

```bash
root="$HOME/.local/share/wordmachine-test/mysql"
cache="$HOME/.cache/wordmachine-deps"
install -d -m 700 "$root" "$cache"
(
  cd "$cache"
  apt-get download mysql-server-core-8.0 mysql-client-core-8.0 \
    libaio1 libmecab2 libevent-core-2.1-7 libevent-pthreads-2.1-7
  for package in ./*.deb; do dpkg-deb -x "$package" "$root"; done
)
LD_LIBRARY_PATH="$root/usr/lib/x86_64-linux-gnu" \
  "$root/usr/sbin/mysqld" --no-defaults --version
```

本机版本是 `8.0.42-0ubuntu0.20.04.1`；另补 `libaio1`、`libmecab2`、两个 libevent 库。6 个包的 SHA-256 已与本机 APT 元数据核对，版本及摘要记录于 `~/.local/share/wordmachine-test/mysql/installed-packages.txt`。库搜索路径仅用于 MySQL 子进程，不修改全局动态链接配置。

这只是本机发行版仓库提供的**隔离测试版本，不是生产版本推荐**。其他系统应使用各自受支持、维护中的 MySQL 包并重新运行测试；CI 镜像仍为 MySQL 8.0。本次没有安装 Docker、升级操作系统或修改现有服务。

### Playwright 配套浏览器

受支持系统通常只需 `cd frontend && npx playwright install chromium`，缺少系统库时按官方文档安装依赖。

本机 Ubuntu 20.04 已不在 Playwright 官方支持列表。安装器没有其 Chromium 下载映射；本次明确选用 Ubuntu 22.04 映射对应的通用 Linux x64 Chrome for Testing 包：

```bash
cd frontend
PLAYWRIGHT_SKIP_BROWSER_GC=1 PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu22.04-x64 \
  npx playwright install chromium
npm run test:browser
```

已安装并运行 Playwright **1.64.1** 对应的 **Chrome for Testing / Headless Shell 156.0.8078.4（revision 1248）** 和 **FFmpeg revision 1013**。仅安装时指定映射；本机正常测试无需该覆盖变量，也无需 `WM_BROWSER_EXECUTABLE`。保留了已有浏览器，不替换系统 Chrome。

**实测能运行不等于 Ubuntu 20.04 恢复官方支持。** 后续更新可能不再兼容；长期应迁移到受支持系统，不能持续强行覆盖平台。CI 的受支持环境仍需实际执行。参考 [Playwright 系统要求](https://playwright.dev/docs/intro) 和 [浏览器安装文档](https://playwright.dev/docs/browsers)。

## 已验证与未验证

本次另配置了[独立持久化本地启动入口](LOCAL_START.md)，不改变下面测试运行器的临时数据语义；它的实际生命周期验证通过 `make test-startup` 单独执行（1 项编排/两个 Chromium 阶段），不混入常规测试或既有浏览器数量。首次断言误用分页字段的失败日志保留，修正为真实契约后通过。

- 本次 `make check-with-mysql`：**829 项 Python（577 单元 + 252 真实 MySQL）、181 项前端单元/组件测试通过**；105 个 Python 文件通过 Ruff lint/格式检查，前端 lint、格式、类型及构建通过，没有跳过数据库测试。本次新增 18 个本地启动单元回归；上一批新增 6 个自然会话到期、HTTP/Socket 复核/回执保留及实际限流窗口恢复回归；此前颜色修复的 13 单元与 1 MySQL 回归继续验证当前姓名 Rating/可见性与读取不修改历史；此前 N1 新增的 37 单元与 14 MySQL 回归继续覆盖六分布、搜索范围/首页策略、NULL/有符号 ID、并发变化下的同一快照；既有索引迁移/故障、数据/会话/回执保留和写探针恢复用例也完整通过。此前索引批次三项 DDL 失败/等待用例独立复跑，51 项连接/命令/状态/播放生命周期用例曾连续三轮通过。完整类型检查/安全审计不在 Ruff 承诺范围内。
- 此前 `make test-browser` 对应命令：**14 项检查使用配套浏览器通过**。业务 API 仍使用模拟数据，边界见 [前端指南](FRONTEND.md#浏览器测试的范围与环境)。
- 此前认证故障批次 `make test-browser-mysql`：**7 项真实浏览器场景 + 6 项 Python 编排/SQL 核对本批通过**。本批新增自然过期和实际 429/Retry-After 两个场景/两个编排；新增 6 MySQL + 2 编排又在新私有实例独立复跑通过，见 [认证故障验证](AUTH_FAILURE_TESTS.md)。此前颜色断言及核心场景全部保留，没有伪造成功响应。除双用户开局、Socket/HTTP、重连、原请求重试及结算外，此前新增注册/改密、管理员重置/封禁/恢复、实际 Socket 撤销、词典/单词/CSV 维护与权限拒绝。核心管理限定范围见管理验收文档，新增故障范围见上方链接；不代表所有浏览器/故障组合或生产部署。此前管理批次提取共用编排后曾在实际浏览器运行期间发送 SIGTERM，运行器返回 143，未残留所属浏览器、服务器或临时 MySQL。
- 另实测了仅回环监听、测试账号不能创建前缀外数据库、测试命令失败码传递和退出清理。运行器的环境隔离、拒绝 root、子进程回收和失败清理由新增单元测试覆盖。
- MySQL 用例使用合成旧结构/数据，覆盖迁移、约束、JSON 查询、事务、持久请求重放、状态版本竞争、新对局题目快照、参赛关系（重排/外键锁顺序/混合查询）及显式成员转换（默认只读、版本竞争、原子回滚）、新局答题关系（轮次/FK、binary64 精度、仅追加、跨局结算及失败回滚）、新结算/评分流水（空结算、唯一键、用户最新指针、当前读、不同用户首次结算及五阶段回滚）、受限旧答案转换（来源拒绝、原值保留、版本竞争、一致快照、四阶段回滚及确认丢失）、历史详情 HTTP 读取契约（评分历史定位、守卫/构建入口、未来答案与旧字段保留）和既有并发场景；此前 11 项转换关键用例另连续三轮通过。**数据库集成用例不等于真实旧数据副本迁移、备份恢复、生产规模性能或浏览器验收**；浏览器关键流程由上述独立真实场景验证。
- 本地完整工作区的 CI 配置仍未取得托管执行证据；用户已确认合并的 GitHub 精简构建源码不含测试或 CI。N2 要实际运行 CI，需先确认验证仓库/交付范围和权限，不能把本地执行相同入口当作 CI 通过。
- 未连接业务数据库、未获取或迁移真实旧数据，未改动评分规则。生产部署仍按 [PLAN.md](../PLAN.md) 单独验收。
