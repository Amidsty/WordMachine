# Python 格式化与静态检查

本文记录此前 `PLAN.md` 第 4 阶段的全项目 Python 格式化及静态 lint 接入批次；下文文件数、AST 对比及 642 项回归是该批交付时的历史记录，最新计数见 [测试环境](TEST_ENVIRONMENT.md)。后续 [列表查询优化](LIST_PERFORMANCE.md) 已单独修改三处服务 SQL，不在原格式等价声明范围内。应用、历史迁移、测试脚本和全部测试都纳入检查；**这不是完整类型检查、安全审计或数据库事务证明**。

## 安装和统一入口

Ruff **0.14.10** 只加入 `requirements-dev.txt`，不增加运行时依赖。`ruff.toml` 的 `required-version` 与安装版本精确匹配；版本不符直接失败，不随编辑器的全局安装改变结果。Python 目标语法为 3.10，实际完整回归环境为 Python 3.11。

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
# 或在激活的虚拟环境内：python -m pip install -r requirements-dev.txt

make check-python-static  # Ruff lint + format --check，不改文件、不访问数据库
make format-python       # 明确修改格式；不自动修复 lint 或排序导入
make check-python        # 先静态检查，再 pytest
make check               # 上述 Python 检查 + 前端检查/测试/构建
make check-with-mysql    # 同一入口，另启动新的隔离 MySQL，数据库用例不跳过
```

可使用 `PYTHON=python` 指定已激活环境。`Makefile` 的 `PYTHON_SOURCES` 为 `app.py wm_app migrations scripts tests`；新增这些目录内的 Python 文件自动覆盖，新增其他顶层源码目录时需同时更新该清单与覆盖回归。命令显式使用根目录 `ruff.toml`。`.ruff_cache/` 已忽略；缓存不是验收证据。

CI 既有步骤安装 `requirements-dev.txt` 并执行 `make check PYTHON=python`，因此自动获得这道检查；**本地通过不等于 CI 已运行**。默认检查使用 `--no-fix` 和 `format --check`，不会因检查而写代码，亦不会启动迁移或连接业务库。`make test-mysql`、直接运行 pytest 和独立浏览器命令仍是特定测试入口，不冒充全套检查。

## 规则及有限例外

配置采用稳定模式，禁用 preview 和 unsafe fixes，不选择 `ALL`：

| 规则 | 范围 |
|---|---|
| `E4/E7/E9` | 导入/语句风格及相关语法问题 |
| `F` | 未定义/未使用名称、重复定义等 Pyflakes 检查 |
| `I` | 导入顺序与分组 |
| `B` | 常见易错写法，如可变默认值、默认参数调用、异常链、zip 长度约定 |
| `RUF100` | 过期/无效的 `noqa`，避免豁免失去理由后长期残留 |

格式使用 100 列目标、4 空格、优先单引号和 LF，不改写 docstring 中的代码示例。没有启用 `E501` 强制截断长字符串；尤其不为列宽改动 SQL 或用户可见文本。

仅有两项有依据的规则配置，不排除整个目录或历史代码：

1. `migrations/versions/000[1-7]_*.py` 仅豁免 `I001`，保留七版历史迁移的导入执行顺序。仍接受格式检查及其他 lint；新版本（如未来 `0008`）不豁免。`migrations/env.py` 也不豁免。迁移模板已整理导入，新增迁移仍需正常审查、格式化和检查；本批没有新增迁移版本。
2. `B008` 只认可完整名称 `wm_app.services.pagination.ListQuery` 为不可变构造器。它是 frozen dataclass，只含验证后的 int/str，五处共享默认查询并非可变默认参数。测试约束字段与不可变性；其他模块的同名构造器仍被拒绝。

`tests/browser/conftest.py`（以及后续的 `tests/performance/conftest.py`）的共享 MySQL 夹具通过 `__all__` 明确导出，不能让自动清理“未使用导入”删掉 pytest 的依赖。没有为测试文件批量忽略 `F401/F811`。

Ruff 的 lint 自动修复与 formatter 是两条不同路径。`make format-python` 不排序导入；若需要修复导入，应先查看有界 `--select I --diff`，审查后才应用，尤其检查初始化顺序和动态注册。不默认运行全量 `--fix`，不使用 `--unsafe-fixes` 让检查变绿。Ruff 版本升级需同时更新依赖及 `required-version`，重新审查格式/规则变化并跑完整回归。

## 本次代码调整与保护

1. 格式化前保存原有 **85 个 Python 文件**快照；单独格式化后 **78 个文件文本变化，但全部 85 个 AST 一致**，包含 SQL 字符串、迁移预检与 DDL、版本链和评分公式。
2. 导入排序单独查看 diff 后处理 30 项；保留模块内为避免循环依赖而设置的局部导入，不把工厂初始化移到模块导入时执行。
3. `game_requests.reserve()` 的三个预期重复键分支显式使用 `raise ... from None`：对外错误码/状态/消息和请求重放行为不变，仅明确异常链显示，不把预期重复键作为后续领域错误的展示原因。其他数据库错误仍原样抛出。
4. `game_questions.validate_snapshot()` 已先检查两侧数量，之后使用 `zip(..., strict=True)` 表达成对完整性。增加“额外快照行”回归，数量不符仍报原领域错误，不变成原生 ValueError 或静默截断。
5. 最终复核：七版迁移和 `migrations/env.py` 的 AST 与原始快照一致；应用/迁移 SQL 常量逐项不变。除单独审查的导入调整外，旧文件中的 AST 差异仅限上述两个服务、浏览器夹具导出及三处回归测试。新增检查测试后共 **86 个 Python 文件**，全部以 Python 3.10 语法解析通过；这不声称已经执行 Python 3.10 的完整运行时测试。

AST 比较是本次格式迁移的独立核对，不是 Ruff 自带的等价保证，也不能证明所有动态行为。没有修改结构迁移内容、评分规则、业务写协议或历史数据。该格式批次的 head 为 `0007_game_settlements`；当前发行版要求见 [迁移指南](AUTH_MIGRATION.md)，旧应用不得混写和生产恢复要求保持不变。

## 回归与边界

`tests/unit/test_python_checks.py` 的 **16 项检查工具回归**实际启动已安装 Ruff/Make，覆盖：

- 所有源码目录和现有文件均被发现，新文件中的未定义名称、可变默认值及导入错误会失败。
- 历史迁移仅豁免导入排序，未来迁移不豁免；不可变构造器例外必须匹配完整模块名。
- Make 的 lint 失败、格式失败均返回非零且不改源文件；显式格式化保留示例 AST 且幂等；工具版本不符拒绝运行。
- Alembic 模板在临时目录渲染后可解析/检查，不导入执行、不运行 DDL。

另新增 **4 项边界回归**：缺失/冲突回执异常链、额外快照行和共享默认查询不可变性；原有坏 JSON/NULL/非对象回执测试也补异常链断言。

本批 `make check-with-mysql`：**642 项 Python（453 单元 + 189 真实 MySQL）、156 项 Vue 测试**以及 Python/前端 lint、格式、类型和构建通过，无数据库跳过。浏览器结果及隔离限制以 [测试环境](TEST_ENVIRONMENT.md) 为准；与 [管理验收](MANAGEMENT_BROWSER_TESTS.md) 和 [播放页验收](GAME_PLAYING_UI.md) 共用既有真实场景。

未引入全项目 mypy/pyright 类型检查、全量安全扫描或所有 Python 版本的运行矩阵。生产性能、更多浏览器/网络故障、授权旧数据副本审计/转换/恢复及部署仍按 [PLAN.md](../PLAN.md) 单独验收。

工具行为参考 [Ruff 配置](https://docs.astral.sh/ruff/settings/)、[格式化](https://docs.astral.sh/ruff/formatter/) 和 [lint 修复安全性](https://docs.astral.sh/ruff/linter/#fix-safety)。
