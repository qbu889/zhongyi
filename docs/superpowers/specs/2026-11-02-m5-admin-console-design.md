# M5 管理端设计：`/api/admin/*` 与 `/admin` 控制台

日期：2026-11-02　范围里程碑：M5 第一轮（M5-A）
上游文档：[`需求文档-RAG系统.md`](../../需求文档-RAG系统.md) §6.5 管理端交互、FR-12 / FR-13 / FR-15、D2、§10 E2/E3；
既有实现事实依据：`backend/app/admin/quality.py`、`backend/app/admin/reindex.py`、`backend/app/etl/loaders.py`、`backend/app/search/retriever.py`、`frontend/app/admin/page.tsx`（当前为占位页）。

---

## 1. 背景与本轮目标

M4 交付了对话页与四大库，但 §6.5 规划的整块管理端**没有可用界面**。缺口的真实形状是 2026-11-02 实测出来的（不是读代码推的）：

- **两个 admin 端点已经存在，且匿名可访问**：`backend/app/main.py:36-49` 直接把 `GET /api/admin/quality-report`（转发 `build_quality_report().to_dict()`）和 `POST /api/admin/reindex`（`run_reindex()` + `session.commit()`）挂在 app 上，没有 router，所以按 `include_router` 去搜是搜不到的。`main.py:33-35` 的注释与 `tests/db/test_admin_api.py:37-46` 的 `test_admin_endpoints_are_currently_unauthenticated` 都明确写着"一期无鉴权是 §10 E2 未决项的**故意留痕**，E2 落地时该测试必须改成断言 401/403"。本轮就是那个"E2 落地时"。
- 已有的两个端点缺能力：`/reindex` 没有 `force`、没有 preview、没有并发保护、没有版本列表；`/quality-report` 没有 CSV；两者没有登录门。
- 真正一片空白的是候选方名审核与问答日志：`pending_formula_name` 的 `decision / decided_by / decided_at`（`backend/app/db/models.py:231-233`）三列**存在但从未被写入**——实测 `zhongyi_e2e` 的 64 行全是 `decision=pending`、`decided_by IS NULL`。`loaders.py:8` 声明这三列是"人工资产，重跑只刷新置信度"，但既没有生产代码产生这份资产，此前也没有测试守着它。
- `IndexVersion.status` 的注释写着 `building|ready|retired`（`models.py:249`），但全后端**没有任何地方写入 `building`**：`reindex.py:150` 是在同一事务里把 `ready` 批量翻成 `retired`。所以"重建进行中"横幅**没有可渲染的状态**——见 §7 的口径修正。

本轮把上述四件事做成可交付闭环：给已有两个端点加鉴权门与缺失能力，补齐候选方名审核与问答日志两块空白，并交出 `/admin` 界面。

## 2. 范围切分

**本轮做（M5-A）**

1. **沿用**现有 `GET /api/admin/quality-report`（FR-13），加登录门 + 单表 CSV 导出。路径不改名：`search.py:21` 与 `chat.py:103` 的 `index_not_ready` 文案明确指示维护者调用 `/api/admin/reindex`，`test_admin_api.py:26` 与 `test_search_api.py:17` 也在按这两个名字断言——改名等于同时打断三条既有链路。
2. `GET /api/admin/pending` + `POST /api/admin/pending/{id}/decision`，三动作与留痕（§6.5 候选方名审核）。
3. **扩展**现有 `POST /api/admin/reindex`（加 `force` 与进程内锁，响应体仍是 `asdict(ReindexReport)`，`test_admin_api.py:23` 的字段断言不动），并新增 `GET /api/admin/reindex/preview` 与 `GET /api/admin/index-versions`（FR-12）。
4. `GET /api/admin/logs/{summary,refusals}` 与 `GET /api/admin/logs`（FR-15 只读面，为 D2 阈值校准提供第一份真实输入）。
5. `/admin` 四个子路由替换现有占位页。
6. 共享口令 → 无状态 cookie 的 fail-closed 鉴权门。

**本轮明确不做**（各项理由见 §13）

- 👍/👎 反馈与 `answer_log` 表：需先定症状文本保留期/删除权（E2）。
- ETL 读取 `decision` 回流建方：动到 M1 花力气守住的抽取纪律（"禁止 fallback 造名"），单独一轮。
- 重建的阶段流水与异步作业表：`run_reindex` 在 fake embedder 下整库 ~1.6s，无此必要；BGE-M3 变慢时再加，且本轮的 API 形状已为它留好扩展位。
- 多用户账号体系、`/chat/:sessionId` 鉴权、日志保留期策略。
- 管理端图表库与任何新依赖。

## 3. 身份与鉴权

单维护者假设（本轮决策）。机制：

- 口令走 `app.config.Settings` 的新字段 `admin_token: str = ""`（与 `refusal_threshold` 等同源，pydantic-settings 会自动读 `ADMIN_TOKEN` 环境变量）。选 Settings 而不是裸 `os.environ`，是因为 `settings` 在导入期就实例化，测试可以在 fixture 里直接 monkeypatch 它——见 §11 的既有测试连带改造。长度要求 ≥16 字符；**只从环境/配置读**，不写文件、不进仓库、不出现在任何日志或错误信息里。
- `POST /api/admin/session {token}` 校验通过后签发 cookie `zhongyi_admin`，值为 `<过期unix秒>.<HMAC-SHA256(ADMIN_TOKEN, 过期秒)>`（hex）。校验用 `hmac.compare_digest`；cookie 属性 `HttpOnly; SameSite=Lax; Path=/; Max-Age=1800`。无状态设计使重启不丢登录态，TTL 到点自然失效；登出即前端 `POST /api/admin/session/logout` 清 cookie。
- 依赖项 `require_admin` 保护除 `/api/admin/session` 以外的全部 admin 端点。
- **fail-closed**：`ADMIN_TOKEN` 未配置时，`/api/admin/*` 全部返回 `503 {code: "admin_disabled"}`，包括 `/session` 本身。管理端绝不能因为漏配环境变量而裸奔。
- CSRF 依赖 `SameSite=Lax` + 全部写操作走 POST。这是单维护者本地场景下的取舍，不是完整方案：真要对外部署必须补 Origin 校验与 TLS 前置，这条与 E2 一起处理。

## 4. 后端 API 契约

统一沿用前端已认得的错误形状 `{"detail": {"code", "message"}}`（`frontend/lib/api.ts:18-26` 按此解析）。

| 方法 | 路径 | 请求 | 响应 | 备注 |
|------|------|------|------|------|
| POST | `/api/admin/session` | `{token}` | `{ok: true, expires_at}` | 唯一不受 `require_admin` 保护的端点 |
| POST | `/api/admin/session/logout` | — | `204` + `Set-Cookie: zhongyi_admin=; Max-Age=0` | 必须由后端下发清除指令：HttpOnly cookie 前端删不掉 |
| GET | `/api/admin/quality-report` | — | `QualityReport.to_dict()` | 已存在（`main.py:36-40`），本轮只加登录门；键名集合由 `test_admin_api.py:33-35` 锁定 |
| GET | `/api/admin/quality-report/export` | `list=<清单名>` | `text/csv` | 清单名与响应字段的映射见 §4.1；标准库 `csv`，RFC 4180 引号转义 |
| GET | `/api/admin/pending` | `decision?` `reason?` `limit` `offset` | `{total, items: [{id, raw_name, doc, source_row_no, suggested_parent, confidence, evidence_text, reason, decision, decided_by, decided_at, decided_name}]}` | 默认 `decision=pending` |
| POST | `/api/admin/pending/{id}/decision` | `{action, target_formula_id?, name?, note?}` | 更新后的单条 pending 项（`merged` 另带 `alias_created: bool`） | 语义见 §6 |
| GET | `/api/admin/index-versions` | — | `{current: {...ready}, target_commit_hash, versions: [...]}` | 每行含四元组（语料 hash / embedding / chunking / extract rule）与 `notes.skipped` |
| GET | `/api/admin/reindex/preview` | — | `{current_version, target_commit_hash, corpus_counts, delta, will_reuse}` | 只解析不写库，见 §7 |
| POST | `/api/admin/reindex` | `{force?: bool}` | `asdict(ReindexReport)`：`version_id, commit_hash, status, reused, counts, skipped, chunks, elapsed_ms` | 已存在（`main.py:42-49`，当前无 force/无锁/匿名）；本轮加登录门 + `force` + 进程内锁，响应形状不变 |
| GET | `/api/admin/logs/summary` | `window_days=7` | `{queries_total, queries_recent, refusal_rate, avg_hit_count}` | 只读聚合 `qa_log` |
| GET | `/api/admin/logs/refusals` | `window_days=7` `limit=50` | `{items: [{query, count, top_score_max}]}` | 按原文分组计数降序——高频拒答词即语料补缺清单 |
| GET | `/api/admin/logs` | `intent?` `refused?` `limit` `offset` | `{total, items: [{id, created_at, session_id, query, intent, refused, top_score, hit_count}]}` | `models.py:276` 的现有列，不新增 |

### 4.1 CSV 导出清单名 → 响应字段映射

七张清单里只有四张是**行表**，另外三张是聚合对象，直接按"表"导出会造假列名。所以导出目标明确限定如下（`build_quality_report()` 的字段名为准）：

| `list=` 取值 | 数据来源字段 | 导出行 |
|-------------|-------------|--------|
| `herb_diff` | `herb_diff[]` | 每对差异一行，`missing_in_gram`/`missing_in_ancient` 用 `、` 连接 |
| `dose_deviation` | `dose_deviation[]` | 每方每药一行（展开 `items` dict：药名、ancient_g、gram_g、deviation_pct） |
| `parse_failure_details` | `parse_failure_details[]` | 每条待审明细一行（`raw_name, doc, source_row_no, reason, decision`）。注意用的是**明细**字段而非 `parse_failures` 的按原因计数——计数表在 UI 上看，导出要给维护者能下钻的行 |
| `annotation_items` | `annotation_items[]` | 每味误抽注记一行（含 `variant_id`，可回指方） |

`dangling_herbs`（⑤，形状是 `{rows, distinct_terms, top[]}`）、`dose_state_distribution`（⑥，五态计数）、`pending_queue`（⑦，两个计数 dict）是聚合视图，**不提供 CSV 导出**；要下载它们请去 `/admin/pending`（⑦ 的真实行）或读 ⑤ 的 top 榜复制。请求未知 `list=` 值一律 `422 invalid_export_list`。

## 5. 数据模型变更（本轮唯一一处）

给 `pending_formula_name` 增加一列可空文本 `decided_name`：承载"确认为独立方"时人工填写的规范方名。

- 理由：不写这列，`confirmed_new` 就只是把状态从 pending 改成另一个状态，57 行 `no_formula_name` 的判定内容（维护者认为它叫什么名）无处落地，等于白点一次按钮。
- 生效路径：模型加列后，测试与 `zhongyi_e2e` 由 `bootstrap` 的 `drop_all/create_all` 自动获得；**已存在的 dev 库（`zhongyi_probe` / `zhongyi_scratch` / `zhongyi_test`）需要一次手工 `ALTER TABLE pending_formula_name ADD COLUMN decided_name TEXT;`**，这条列入 §13 第 8 项与 issue #7 的运维缺口，直到 M5 后续补齐生产建表/迁移路径。
- 不引入 user 表、不给 `chat_session` 加归属字段（本轮决策）。

## 6. 审核动作语义

三个动作都写 `decision / decided_by / decided_at`；`decided_by` 本轮固定为 `"admin"`（单维护者；将来 E2 引入账号后改为真实用户）。

- **`merged`（归并到既有方）——立即生效**。校验 `target_formula_id` 存在，然后按 `(formula_id, name, doc)` upsert 一条 `formula_alias`，`kind` **必须**取 `人工归并`：`retriever.py:62` 显式排除 `kind = "加减写法"`，用错 kind 会让归并在精确通道里静默失效。生效是即时的——精确通道直接查 `formula_alias` 表（`retriever.py:60-66`），不读索引，因此无需重建。响应里 `alias_created` 区分"新建"与"该 alias 已存在"（幂等）。
- **`noise`（判为噪声）——只标注**。数据上它们本来就不入库（`decision` 默认 `pending`，`loaders.py` 从不据其建方），本动作的意义是把这一行从待审列表里摘出去并留下"谁在何时判的"。
- **`confirmed_new`（确认为独立方）——仅登记，不建方**。要求填 `name`（写入 `decided_name`）。UI 必须原话显示：「此动作仅登记判定，不会自动建立方剂记录；建方需 ETL 读取判定结果，属下一轮范围。」理由：这 64 行落队列的原因正是组成缺失或一方多名（实测分布 `no_formula_name` 57 / `multi_name_row` 3 / `pair_without_composition` 3 / `no_composition` 1），凭空建方违反 §5.6"宁缺勿滥、禁止 fallback 造名"。
- 纪律回归：`loaders.py:8` 那句"人工资产重跑只刷新置信度"本轮**首次被测试锁定**——审核后跑一次 `run_reindex`，断言四列不被抹掉（`loaders.py:260-263` 的 upsert update 集只含 confidence/evidence_text/suggested_parent/reason，所以应当成立）。

## 7. 重建端点语义与"蓝绿"口径

- `preview`：调 `build_corpus()`（`reindex.py:68`，只解析）拿目标计数，与当前 `ready` 版本比较给出 `delta`；`target_commit_hash` 来自 `app.git_utils.distilled_commit_hash()`，该函数在 `distilled/` 无提交历史时抛 `ValueError` → 映射为 `503 {code: "corrupt_corpus_git_state"}`。
- `POST /reindex`：现有实现已经做对了两件事——`main.py:48-49` 是 `run_reindex(session)` 后 `session.commit()`，而 `reindex.py:125` 的 docstring 写明"事务由调用方掌管，提交即发布、回滚即什么都没发生"。本轮在其外面包一层：异常时 rollback 并返回 `500 {code: "reindex_failed"}`（当前实现是异常直接冒到 FastAPI，500 但无结构化 code），再加 `force` 透传与进程内锁。响应体保持 `asdict(report)` 不变。
- 幂等：版本四元组 `(语料 git hash, embedding 模型版本, 切片规则版本, 抽取规则版本)` 全同且已有 `ready` 行时返回 `reused: true` 且不产生新版本（`reindex.py:113` `_existing_ready`）；`force=true` 跳过该短路。
- 并发：进程内一把锁，占用时第二个请求直接 `409 {code: "reindex_in_progress"}`。当前部署形态是单 uvicorn 进程，锁够用；多进程部署需要 DB 级咨询锁，登记为边界。
- **口径修正（重要）**：不实现也不声称"双索引蓝绿切换"。`reindex.py:1-12` 的模块 docstring 已经把话说清：一期真实形态是**单事务原子发布**，靠 Postgres MVCC 保证并发读者要么看到旧完整索引、要么看到新完整索引；"原地 upsert 本身不构成蓝绿"，双索引 + 翻指针是退路而非现状。因此 §6.5 的"重建期间页顶横幅提示重建中"**改为可如实渲染的样子**：概览页横幅显示「当前索引 vX（commit / 三规则版本）· 上次重建耗时 / 是否复用」，不显示不存在的中间态。

## 8. 日志看板

全部只读，全部走 `qa_log` 现有列，不新增表：

- 四张卡片：累计提问数、近 7 日提问数、拒答率、平均证据命中数。
- 高频拒答表：`refused = true` 按 `query` 原文分组计数降序，附该组 `top_score` 最大值——它是 D2 阈值校准与 `distilled/` 补缺的直接输入。分组**不做任何归一化或模糊匹配**（错字/繁简未归一是 E3 已登记的边界，此处不偷偷发明规则）。
- 明细表：`intent` / `refused` 筛选 + 分页。
- 隐私提示：看板页顶部固定一行说明「日志含用户主诉原文，勿截图外传；保留期与删除权待 E2 定义」。工程侧主动提示，不等产品催。

## 9. 前端结构

四个子路由替换 `frontend/app/admin/page.tsx` 的占位实现：`/admin`（概览 + 重建）、`/admin/quality`、`/admin/pending`、`/admin/logs`，共用 `<AdminShell>`（导航 + 全局态）。选子路由而非页内 Tabs：质量报告数据量大、需要可分享 URL，且 §6.5 要求管理页"弱交互、表格为主"。

数据获取一律**客户端组件 + `apiGet`**（相对路径经 `next.config.ts` rewrite 到后端，浏览器自动携带 HttpOnly cookie）。不在服务端组件转发 cookie——那要多一套 header 传递机制，而管理端首屏 loading 完全可接受。

由此得到一条**安全要求而非渲染偏好**：管理端四个页面在服务端不取任何数据，因此构建期预渲染出的 HTML 里不可能含有质量报告、候选队列或日志内容——这正是我们敢让它们保持客户端取数的原因。`next build` 把某个 `/admin` 路由标成 `○`（静态外壳）还是 `ƒ`（动态）都**可以接受**，两者都不影响安全边界；但实现与验收都必须盯住真正的不变量：**管理数据只经浏览器带 cookie 的 `/api/admin/*` 调用到达页面**。这条要在 e2e 里断言（未登录访问 `/admin/quality` 只见登录门，页面文本里不含任何清单标题之外的报告内容）。

状态面（每页都要有，不得合并成一句"加载失败"）：未启用（503 `admin_disabled`）、未登录（401）、登录口令错误（401 且表单保留）、加载失败（可重试）、空数据、写操作进行中（按钮禁用且文案说明原因）、写成功（`role="status"` 播报）。

具体交互：

- 概览页：当前索引卡片 + 版本历史表 + 重建流程三段式（preview 显示 diff 与目标 hash → 二次确认列出 +N/−N 与预期耗时 → 结果卡片显示 `reused` / `elapsed_ms` / counts）。`409` 单独提示"已有重建在跑"。
- 质量报告页：按 PRD 的 ①–⑦ 编号出七张表，每张配「导出 CSV」。**§6.5 的"解析失败行点击跳到 distilled 源文件路径"按现实改口径**：浏览器打不开服务器本地文件、语料是 0600 权限（M0 前置），所以展示 `doc + source_row_no` 并提供复制按钮，不提供伪链接。
- 候选方名页：筛选 + 表格；三个动作行内展开（不开弹窗，沿用 M4 侧栏确认的风格）；归并的目标方选择器**复用 M4 的 `<SearchSuggest>`**（`POST /api/search`，`kind: ["formula"]`），不新做搜索；确认独立方的表单里原话显示"仅登记不建方"；已判定行默认展开留痕。
- 日志看板页：§8 的三块 + 顶部隐私提示行。

不引入任何 UI 组件库或图表库：卡片是纯文本，拒答频次是表格而不是柱状图。

## 10. 可访问性与视觉纪律

沿用 M4 已验收的那套：表格必须有 `<caption>` 与真 `<th scope>`；按钮有可访问名（不靠 `title` 传达关键信息）；写操作结果走 `role="status" aria-live="polite"`；破坏性操作的确认必须键盘可达——**不复现 M4 已知的"disabled 按钮 + title，键盘/AT 读不到"毛病**；对比度继续 `text-ink/70`（实测 ≈5.54:1）；焦点环沿用 `frontend/app/globals.css:14-20`。口令输入框 `type="password"`、`autoComplete="off"`，并有可见的标签文案。

## 11. 测试策略

**后端（pytest，`backend/tests/db/test_admin_api.py` 等）**

**加登录门前必须先改的既有测试（实测发现，不是推测）**：`backend/tests/db/test_search_api.py:17` 的 `_indexed()` 夹具直接 `client.post("/api/admin/reindex")` 并断言 200——它是整个 search 套件的建索引入口，门一上加就全线 401/503。改造方案：在 `tests/conftest.py` 里加一个 `admin_token` fixture monkeypatch `settings.admin_token`，并让 `client` fixture 默认携带已签发的 cookie（同时保留一个 `anon_client` 用于断言未登录态）。另外 `tests/db/test_admin_api.py:37-46` 的 `test_admin_endpoints_are_currently_unauthenticated` 是 E2 的**故意留痕**（docstring 自己说"E2 落地时这个测试会失败，强迫改动者回来把『匿名可访问』改成断言 401/403"）——本轮正是那个时刻，必须把它改写为"匿名访问返回 401/503"，并保留原 docstring 的意图说明，不要一删了之。


1. fail-closed：未设 `ADMIN_TOKEN` 时全部 `/api/admin/*` 返回 503 `admin_disabled`（含 `/session`、`/preview`、`POST /reindex`）。
2. 口令：错误口令 401；正确口令 → `Set-Cookie` 含 `HttpOnly`/`SameSite=Lax`/`Max-Age`；伪造签名与过期时间戳的 cookie 均 401。
3. 质量：端点响应的 key 集合与 `build_quality_report()` 的 dataclass 字段逐一相等（防"API 与报告两套口径"）；CSV 断言表头、行数与含逗号/引号字段的转义。
4. 审核：`merged` 后**立刻**用人工别名调 `/api/search` 能命中目标方（这条是"立即生效"的回归锁）；重复 `merged` → `alias_created=false` 且 `formula_alias` 行数不变；`target_formula_id` 不存在 → 404；三动作都写 `decided_by/decided_at`；`confirmed_new` 写 `decided_name`；审核后 `run_reindex` 一遍，断言四列人工字段未被抹掉。
5. 重建：`preview` 不写库（`index_version` 行数不变）；`POST` 成功 → 新行 `ready`、旧行 `retired`、report 字段齐；hash 全同且非 force → `reused=true` 且不产生新行；锁占用 → 409；复用现有 `fail_after_load` 注错 → 回滚后版本行与统计完全不变。
6. 日志：固定 `qa_log` fixture 断言四指标数值与拒答分组的排序、以及 `refused=false` 不进入拒答榜。

**前端（vitest + MSW）**：全局态三态文案（未启用/未登录/加载失败）、CSV 链接 href 与 `list` 参数、三个动作的表单校验与请求 body、重建三段式状态机含 `reused` 分支、看板数字确实来自 API 响应、归并选择器复用 `SearchSuggest` 的渲染。

**端到端（`frontend/e2e/admin.spec.ts`，serial）**：真实登录门；三页在 `zhongyi_e2e` 真实数据上渲染；候选方名页把某行归并到既有方后**在四大库检索里搜得到它**（本轮最有价值的浏览器证明）；重建按钮走 preview → 确认 → 完成。

**执行顺序硬约束**：重建用例会改动 `zhongyi_e2e`，所以 admin 套件排在既有 chat/library 套件之后；默认走 `force=false` 的 `reused` 路径，另开一条 `force` 用例只断言"结构不劣化"（四类计数不减少、版本行 +1），**不断言具体行数**——否则我们只是在给数据库写快照。e2e 需要在 `playwright.config.ts` 的 webServer env 里注入 `ADMIN_TOKEN`（与 `E2E_PORT` 同处配置）。

## 12. 错误码表

| HTTP | code | 触发 |
|------|------|------|
| 401 | `admin_unauthorized` | 口令错误或 cookie 缺失/过期/签名不符 |
| 404 | `pending_not_found` / `formula_not_found` | 审核对象不存在 |
| 409 | `reindex_in_progress` | 锁被占用 |
| 422 | `invalid_decision_payload` | 动作与参数不匹配（如 `merged` 缺 `target_formula_id`、`confirmed_new` 缺 `name`） |
| 422 | `invalid_export_list` | CSV 导出用了未定义的 `list=` 值（见 §4.1） |
| 500 | `reindex_failed` | 重建异常，事务已回滚 |
| 503 | `admin_disabled` | `ADMIN_TOKEN` 未配置（fail-closed） |
| 503 | `corrupt_corpus_git_state` | `distilled_commit_hash()` 拿不到 hash |

## 13. 本设计的边界条目（编号供本文内部引用；实现完成后同步进 M4 设计规格 §13 与 PRD）

1. 单维护者共享口令，无用户体系；`decided_by` 固定 `"admin"`。
2. **本轮之前 `/api/admin/quality-report` 与 `/api/admin/reindex` 已匿名上线**（`main.py:33-35` 自陈是 E2 未决的故意留痕）。所以本轮不是"新接口配鉴权"，而是**给一个已暴露的重建能力补上门**；实现期间两者在测试与 e2e 配置里必须同时受门，且 `test_admin_api.py:37-46` 的留痕测试必须改写而非删除。
3. `/chat/:sessionId` 仍无鉴权即公开（症状文本可被任何拿到链接的人读取）——本轮不解决，属 E2。
4. 日志保留期/删除权/是否用于微调未定义；本轮只在 UI 顶部加提示，不加策略。
5. 反馈表 `answer_log` 与 👍/👎 未做，"按 👎 筛 bad case"仍无数据源。
6. 重建是同步单事务原子发布，**不是双索引蓝绿**；无 `building` 中间态，横幅如实显示"当前索引 + 上次重建结果"。多进程部署需 DB 级咨询锁替换进程内锁。
7. `confirmed_new` 仅登记不建方；ETL 读 `decision` 回流建方是独立一轮。
8. "解析失败行跳源文件"降级为"显示路径 + 行号 + 可复制"。
9. dev 库需手工 `ALTER TABLE ... ADD COLUMN decided_name`；生产建表/迁移路径仍是 issue #7 的未决项。
10. CSRF 只靠 `SameSite=Lax` + POST，公网部署前必须补 Origin 校验与 TLS。

## 14. 验收清单（M5-A 自证）

1. 不设 `ADMIN_TOKEN` 时，`/admin` 四页与 `/api/admin/*` 全部呈现"未启用"，且没有任何一条只读数据泄漏。
2. 正确口令登录后，质量报告七张清单全部渲染，且各表行数与 `/api/admin/quality-report` 响应逐条对得上；任选一张表导出的 CSV 能被表格软件正确解析（含引号字段）。
3. 待审队列渲染成功。**基线读数（非断言）**：2026-11-02 实测 `zhongyi_e2e` 有 64 行 pending，其中 `reason=no_formula_name` 57 行、`multi_name_row` 3、`pair_without_composition` 3、`no_composition` 1。这些数字**不写进任何测试断言**——审核用例本身就会改动它们。测试只断言不变量：列表 `total` 等于后端响应、`reason` 筛选后每行的 `reason` 都等于所选值、已判定行不再出现在 `decision=pending` 视图里。
4. 归并动作完成后：`formula_alias` 新增一行 `kind=人工归并`、`pending_formula_name.decision/decided_by/decided_at` 被写入、**不重建索引**即可用人工别名在 `/api/search` 与四大库列表精确命中目标方。
5. 重复归并同一目标不产生第二条 alias，UI 提示"该别名已存在"。
6. `run_reindex` 之后，上述人工字段与 `decided_name` 全部保留（有测试断言，非口头保证）。
7. `confirmed_new` 写入 `decided_name`，且表单与列表都能看到"仅登记、不建方"的原话提示。
8. 重建 preview 显示的 `delta` 与实际 `POST /reindex` 结果一致；hash 未变时 `reused=true` 且不新增 `index_version` 行。
9. 重建进行中并发第二个请求得到 409，UI 有对应文案，不出现两个版本行同时 `ready`。
10. 日志看板四卡片数值与 `qa_log` 手算一致，拒答榜按次数降序且不含非拒答记录；顶部隐私提示行可见。
11. `/admin` 四页 + 未登录态 + 重建确认对话框在 axe `wcag2a`/`wcag2aa` 下 serious/critical = 0。
12. 全量回归：后端 pytest、`npx vitest run`、`PW_BROWSER_CHANNEL=chrome npx playwright test` 全绿，且既有 chat/library/a11y 套件未被放宽任何断言。
