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
- 重建的阶段流水与异步作业表：`run_reindex` 在本地默认 embedder 下整库重建为**秒级**（M5-A 的 e2e 实测：冷启动 bootstrap 与 UI 内一次同步 force 重建均为秒级；计划早期的"~1.6s"是另一轮基线的历史数，按本计划回写纪律不再硬编码秒数），无此必要；BGE-M3 变慢时再加，且本轮的 API 形状已为它留好扩展位。
- 多用户账号体系、`/chat/:sessionId` 鉴权、日志保留期策略。
- 管理端图表库与任何新依赖。

## 3. 身份与鉴权

单维护者假设（本轮决策）。机制：

- 口令走 `app.config.Settings` 的新字段 `admin_token: str = ""`（与 `refusal_threshold` 等同源，pydantic-settings 会自动读 `ADMIN_TOKEN` 环境变量）。选 Settings 而不是裸 `os.environ`，是因为 `settings` 在导入期就实例化，测试可以在 fixture 里直接 monkeypatch 它——见 §11 的既有测试连带改造。长度要求 ≥16 字符；**只从环境/配置读**，不写文件、不进仓库、不出现在任何日志或错误信息里。
- `POST /api/admin/session {token}` 校验通过后签发 cookie `zhongyi_admin`，值为 `<过期unix秒>.<HMAC-SHA256(ADMIN_TOKEN, 过期秒)>`（hex）。校验用 `hmac.compare_digest`；cookie 属性 `HttpOnly; SameSite=Lax; Path=/; Max-Age=1800`。无状态设计使重启不丢登录态，TTL 到点自然失效；登出即前端 `POST /api/admin/session/logout` 清 cookie。
- 依赖项 `require_admin` 以 router 级依赖保护受门 `router` 上的全部端点；挂在 `public_router` 上的 `GET /session`（探针）、`POST /session`（登录）与 `POST /session/logout`（登出）不带该依赖（实现拆两个 router 的原因见 `admin.py` 模块注释；受保护性口径见下两条）。
- **fail-closed**：`ADMIN_TOKEN` 未配置时，受登录门保护的全部 admin 端点、`POST /session`（登录动作本身）、`GET /reindex/preview` 与 `GET /index-versions` 等只读路径全部返回 `503 {code: "admin_disabled"}`（枚举用例 `tests/db/test_admin_gate.py::test_fail_closed_when_token_unset` 逐条点名）。管理端绝不能因为漏配环境变量而裸奔。
- **两处不 503 的公开路径，形状不同**：① `GET /session` 状态探针是刻意公开的，未启用时返回 `200 {enabled:false, authenticated:false, expires_at:null}` 而不是 503。这不是漏洞，是前端能区分「未启用」与「连不上」的前提——门的五态（`checking/unreachable/disabled/locked/ready`，R-M5-16）没有这个探针就只能把两者混写成一句谎话；探针只回布尔与过期秒，不含任何管理数据。② `POST /session/logout` 是无状态的清 cookie 指令，任何状态下 204（删不掉的东西也不在里头）。实现见 `backend/app/api/admin.py` 的 `_session_state`，探针行为由 `test_probe_is_public_and_reports_state` 锁定。本文 §4 表格原先把 `POST /session` 写成「唯一不受 `require_admin` 保护的端点」，实际挂在 `public_router` 上的是探针 GET 与登录/登出两条 POST。
- CSRF 依赖 `SameSite=Lax` + 全部写操作走 POST。这是单维护者本地场景下的取舍，不是完整方案：真要对外部署必须补 Origin 校验与 TLS 前置，这条与 E2 一起处理。

## 4. 后端 API 契约

统一沿用前端已认得的错误形状 `{"detail": {"code", "message"}}`（`frontend/lib/api.ts:18-26` 按此解析）。

| 方法 | 路径 | 请求 | 响应 | 备注 |
|------|------|------|------|------|
| GET | `/api/admin/session` | — | `{enabled, authenticated, expires_at}` | **公开状态探针**：UI 需要区分「未启用」「未登录」「连不上」，且不能靠猜；未启用时 200 `{enabled:false,…}`（§3 豁免）。原文无此行，是实现比规格多出的端点，按实现回写 |
| POST | `/api/admin/session` | `{token}` | 成功 `{enabled: true, authenticated: true, expires_at}`（`backend/app/api/admin.py` 登录端点；原表误写 `{ok: true, expires_at}`，按实现回写）；未启用 503、口令错 401 两键 detail | 挂在 `public_router` 上、不经 `require_admin`（受保护性见 §3 两条豁免的说明） |
| POST | `/api/admin/session/logout` | — | `204` + `Set-Cookie: zhongyi_admin=; Max-Age=0` | 必须由后端下发清除指令：HttpOnly cookie 前端删不掉 |
| GET | `/api/admin/quality-report` | — | `QualityReport.to_dict()` | 已存在（`main.py:36-40`），本轮只加登录门；键名集合由 `test_admin_api.py:33-35` 锁定 |
| GET | `/api/admin/quality-report/export` | `list=<清单名>` | `text/csv` | 清单名与响应字段的映射见 §4.1；标准库 `csv`，RFC 4180 引号转义 |
| GET | `/api/admin/pending` | `decision?` `reason?` `limit` `offset` | `{total, limit, offset, items: [{id, raw_name, doc, source_row_no, suggested_parent, confidence, evidence_text, reason, decision, decided_by, decided_at, decided_name}]}` | 默认只返回 `decision=pending`（R-M5-10）；显式空串 `?decision=` 是唯一「看全部」通道（§13）；`limit` 端点内钳制 [1,200]，`limit`/`offset` **回显钳制后生效值**（R-M5-8/R-M5-13 口径） |
| POST | `/api/admin/pending/{id}/decision` | `{action, target_formula_id?, name?, note?}` | `{item, alias_created}`——更新后的单条 pending 项 + 幂等标记：**键恒在**，`merged` 分支为布尔（重复归并同目标 `false`），其余动作后端给 `null`（前端类型 `boolean | null` 按此） | 语义见 §6；非 `confirmed_new` 动作服务端清空 `decided_name`（R-M5-9）；`note` 接受不入库（§13-14） |
| GET | `/api/admin/index-versions` | — | `{current: {…ready} \| null, target_commit_hash, versions: [...]}` | 每行含四元组（语料 hash / embedding / chunking / extract rule）与 `notes.skipped`；「哪行是 current」由单一 `current_ready_version` 判定（评审 F-C），与 preview、POST 复用短路同口径；50 行上限只约束 `versions` 列表 |
| GET | `/api/admin/reindex/preview` | — | `{changed, will_reuse, target_commit_hash, corpus_counts, current}` | 只解析不写库；`changed`/`will_reuse` 按**四元组**判定，与 POST 非 force 的复用短路同一谓词（R-M5-14）。原表写的 `current_version, delta` 不存在：`delta` 未实现，语义按 §7 回写 |
| POST | `/api/admin/reindex` | `{force?: bool}`（默认 false） | `asdict(ReindexReport)`：`version_id, commit_hash, status, reused, counts, skipped, chunks, elapsed_ms` | 已存在（`main.py:42-49`，当前无 force/无锁/匿名）；本轮加登录门 + `force` + 进程内锁，响应形状不变 |
| GET | `/api/admin/logs/summary` | `window_days=7` | `{queries_total, queries_recent, refusal_rate, avg_hit_count, window_days}` | 只读聚合 `qa_log`；`window_days` 钳制 [1,365] 并**回显生效值**（R-M5-13） |
| GET | `/api/admin/logs/refusals` | `window_days=7` `limit=50` | `{window_days, limit, items: [{query, count, top_score_max}]}` | 按原文分组计数降序——高频拒答词即语料补缺清单；两参数钳制 [1,365]/[1,200] 并回显（R-M5-13） |
| GET | `/api/admin/logs` | `intent?` `refused?` `limit` `offset` | `{total, limit, offset, items: [{id, created_at, session_id, query, intent, refused, top_score, hit_count}]}` | `models.py:276` 的现有列，不新增；`limit` 钳制 [1,200]、`offset` 钳制 ≥0 并回显；`intent` 透传（未知值诚实返回空列表，显式空串＝全量，§13） |

### 4.1 CSV 导出清单名 → 响应字段映射

七张清单里只有四张是**行表**，另外三张是聚合对象，直接按"表"导出会造假列名。所以导出目标明确限定如下（`build_quality_report()` 的字段名为准）：

| `list=` 取值 | 数据来源字段 | 导出行 |
|-------------|-------------|--------|
| `herb_diff` | `herb_diff[]` | 每对差异一行，`missing_in_gram`/`missing_in_ancient` 用 `、` 连接 |
| `dose_deviation` | `dose_deviation[]` | 每方每药一行（展开 `items` dict：药名、ancient_g、gram_g、deviation_pct） |
| `parse_failure_details` | `parse_failure_details[]` | 每条待审明细一行（`raw_name, doc, source_row_no, reason, decision`）。注意用的是**明细**字段而非 `parse_failures` 的按原因计数——计数表在 UI 上看，导出要给维护者能下钻的行 |
| `annotation_items` | `annotation_items[]` | 每味误抽注记一行（含 `variant_id`，可回指方） |

`dangling_herbs`（⑤，形状是 `{rows, distinct_terms, top[]}`）、`dose_state_distribution`（⑥，五态计数）、`pending_queue`（⑦，两个计数 dict）是聚合视图，**不提供 CSV 导出**；要下载它们请去 `/admin/pending`（⑦ 的真实行）或读 ⑤ 的 top 榜复制。请求未知 `list=` 值一律 `422 invalid_export_list`。

**导出口径以本节为准（本轮回写）**：§9 质量页那条原先写「七张表**每张配**「导出 CSV」」，与本节「只有四张行表可导」直接冲突；实现按本节落地——管理端一共**四个导出入口**（①②③④），聚合表 ⑤⑥⑦ 没有导出按钮，§9 已按此订正。③ 的形态特殊：屏上按原因计数、导出给到明细行（R-M5-19），链接文案逐字 `导出明细 CSV`（其余三节为 `导出 CSV`）。

上一段「要下载它们请去 `/admin/pending`」落实的具体形状（R-M5-20）：`doc + source_row_no` 的**可复制路径格**原先计划挂在质量页表里（T12），执行中判定它与质量页的计数/聚合形状不匹配（R-M5-2 的并入一格形态），已**搬迁**到 T13 的候选方名表——`/admin/pending` 每行以「路径#行号」一格呈现（`select-all` 可整段选中 + 复制按钮），质量页上现在**没有**这个格子（`QualitySection.pathColumn` 死代码已删）。也就是说：质量页只计数与导出，行级下钻与路径复制一律在 `/admin/pending`。

## 5. 数据模型变更（本轮唯一一处）

给 `pending_formula_name` 增加一列可空文本 `decided_name`：承载"确认为独立方"时人工填写的规范方名。

- 理由：不写这列，`confirmed_new` 就只是把状态从 pending 改成另一个状态，57 行 `no_formula_name` 的判定内容（维护者认为它叫什么名）无处落地，等于白点一次按钮。
- 生效路径：模型加列后，测试与 `zhongyi_e2e` 由 `bootstrap` 的 `drop_all/create_all` 自动获得；**已存在的 dev 库（`zhongyi_probe` / `zhongyi_scratch` / `zhongyi_test`）需要一次手工 `ALTER TABLE pending_formula_name ADD COLUMN decided_name TEXT;`**，这条列入 §13 第 9 项与 issue #7 的运维缺口，直到 M5 后续补齐生产建表/迁移路径。
- 不引入 user 表、不给 `chat_session` 加归属字段（本轮决策）。

## 6. 审核动作语义

三个动作都写 `decision / decided_by / decided_at`；`decided_by` 本轮固定为 `"admin"`（单维护者；将来 E2 引入账号后改为真实用户）。

- **`merged`（归并到既有方）——立即生效**。校验 `target_formula_id` 存在，然后按 `(formula_id, name, doc)` upsert 一条 `formula_alias`，`kind` **必须**取 `人工归并`：`retriever.py:62` 显式排除 `kind = "加减写法"`，用错 kind 会让归并在精确通道里静默失效。生效是即时的——精确通道直接查 `formula_alias` 表（`retriever.py:60-66`），不读索引，因此无需重建。响应里 `alias_created` 区分"新建"与"该 alias 已存在"（幂等）。
- **`noise`（判为噪声）——只标注**。数据上它们本来就不入库（`decision` 默认 `pending`，`loaders.py` 从不据其建方），本动作的意义是把这一行从待审列表里摘出去并留下"谁在何时判的"。
- **`confirmed_new`（确认为独立方）——仅登记，不建方**。要求填 `name`（写入 `decided_name`）。UI 必须原话显示：「此动作仅登记判定，不会自动建立方剂记录；建方需 ETL 读取判定结果，属下一轮范围。」理由：这 64 行落队列的原因正是组成缺失或一方多名（实测分布 `no_formula_name` 57 / `multi_name_row` 3 / `pair_without_composition` 3 / `no_composition` 1），凭空建方违反 §5.6"宁缺勿滥、禁止 fallback 造名"。
- 纪律回归：`loaders.py:8` 那句"人工资产重跑只刷新置信度"本轮**首次被测试锁定**——审核后跑一次 `run_reindex`，断言四列不被抹掉（`loaders.py:260-263` 的 upsert update 集只含 confidence/evidence_text/suggested_parent/reason，所以应当成立）。

## 7. 重建端点语义与"蓝绿"口径

- `preview`：调 `build_corpus()`（只解析，约 1 秒）拿目标计数。返回 `changed`（bool）、`will_reuse`（bool）、`target_commit_hash`、`corpus_counts`（各源行数；`vocab`/`pairs` 两个聚合对象取其主集合行数）与 `current`（当前 ready 版本的计数）。**不提供逐实体 `+N/−N` 差值**（原文的 `delta` 未实现）：那需要 dry-run 整套 loaders，一期给「变没变 + 目标侧行数 + 当前计数」三样让人对照，而不是让后端编一个看着精确的差值。UI 在确认框里把这三个数原样列出。`changed`/`will_reuse` 按**四元组**（语料 git hash、embedding 模型版本、切片规则版本、抽取规则版本）判定，用的就是 POST 非 force 复用短路的同一谓词 `reindex.existing_ready`（R-M5-14）——**语料或规则任一有变化都算 `changed`**。计划里只比 commit_hash 的 T7 snippet 是历史材料，不是验收口径：按那个写法，规则版本进位而语料未动时 preview 会谎称「无需重建」，操作者确认后 POST 却全量重建。`target_commit_hash` 来自 `app.git_utils.distilled_commit_hash()`，该函数在 `distilled/` 无提交历史时抛 `ValueError` → 映射为 `503 {code: "corrupt_corpus_git_state"}`。`corpus_counts` 的键名**原样就是 `build_corpus()` 的键名**（真实键是 `herbs`，`vocab`/`pairs` 取主集合行数；计划 T11 snippet 里的 `corpus_counts.herb` 是错键，照抄会静默渲染"药 —"，前端按真实键取值）。preview 另有一次 `current_ready_version` 查询（「哪行是 current」收成单点判定，无正确性影响）。
- `POST /reindex`：现有实现已经做对了两件事——`main.py:48-49` 是 `run_reindex(session)` 后 `session.commit()`，而 `reindex.py:125` 的 docstring 写明"事务由调用方掌管，提交即发布、回滚即什么都没发生"。本轮在其外面包一层：异常时 rollback 并返回 `500 {code: "reindex_failed"}`（当前实现是异常直接冒到 FastAPI，500 但无结构化 code），再加 `force` 透传与进程内锁。响应体保持 `asdict(report)` 不变。
- 幂等：版本四元组 `(语料 git hash, embedding 模型版本, 切片规则版本, 抽取规则版本)` 全同且已有 `ready` 行时返回 `reused: true` 且不产生新版本（`reindex.py:113` `_existing_ready`）；`force=true` 跳过该短路。
- 并发：进程内一把锁，占用时第二个请求直接 `409 {code: "reindex_in_progress"}`。当前部署形态是单 uvicorn 进程，锁够用；多进程部署需要 DB 级咨询锁，登记为边界。
- **口径修正（重要）**：不实现也不声称"双索引蓝绿切换"。`reindex.py:1-12` 的模块 docstring 已经把话说清：一期真实形态是**单事务原子发布**，靠 Postgres MVCC 保证并发读者要么看到旧完整索引、要么看到新完整索引；"原地 upsert 本身不构成蓝绿"，双索引 + 翻指针是退路而非现状。因此 §6.5 的"重建期间页顶横幅提示重建中"**改为可如实渲染的样子**：概览页横幅显示「当前索引 vX（commit / 三规则版本）· 上次重建耗时 / 是否复用」，不显示不存在的中间态。

## 8. 日志看板

全部只读，全部走 `qa_log` 现有列，不新增表：

- 四张卡片：累计提问数、近 7 日提问数、拒答率、平均证据命中数。
- 高频拒答表：`refused = true` 按 `query` 原文分组计数降序，附该组 `top_score` 最大值——它是 D2 阈值校准与 `distilled/` 补缺的直接输入。分组**不做任何归一化或模糊匹配**（错字/繁简未归一是 E3 已登记的边界，此处不偷偷发明规则），**相近但不同的原文必须是两组**——这条由 `tests/db/test_admin_quality_logs.py` 的用例逐字锁住，不是口头承诺。
- 明细表：`intent` / `refused` 筛选 + 分页。
- 隐私提示：看板页顶部固定一行说明「日志含用户主诉原文，勿截图外传；保留期与删除权待 E2 定义」。工程侧主动提示，不等产品催。

## 9. 前端结构

四个子路由替换 `frontend/app/admin/page.tsx` 的占位实现：`/admin`（概览 + 重建）、`/admin/quality`、`/admin/pending`、`/admin/logs`，共用 `<AdminShell>`（导航 + 全局态）。选子路由而非页内 Tabs：质量报告数据量大、需要可分享 URL，且 §6.5 要求管理页"弱交互、表格为主"。

数据获取一律**客户端组件 + `apiGet`**（相对路径经 `next.config.ts` rewrite 到后端，浏览器自动携带 HttpOnly cookie）。不在服务端组件转发 cookie——那要多一套 header 传递机制，而管理端首屏 loading 完全可接受。

由此得到一条**安全要求而非渲染偏好**：管理端四个页面在服务端不取任何数据，因此构建期预渲染出的 HTML 里不可能含有质量报告、候选队列或日志内容——这正是我们敢让它们保持客户端取数的原因。`next build` 把某个 `/admin` 路由标成 `○`（静态外壳）还是 `ƒ`（动态）都**可以接受**，两者都不影响安全边界；但实现与验收都必须盯住真正的不变量：**管理数据只经浏览器带 cookie 的 `/api/admin/*` 调用到达页面**。这条要在 e2e 里断言（未登录访问 `/admin/quality` 只见登录门，页面文本里不含任何清单标题之外的报告内容）。

状态面（每页都要有，不得合并成一句"加载失败"）：未启用（503 `admin_disabled`）、未登录（401）、登录口令错误（401 且表单保留）、加载失败（可重试）、空数据、写操作进行中（按钮禁用且文案说明原因）、写成功（`role="status"` 播报）。门本身收为**五态** `checking / unreachable / disabled / locked / ready`（R-M5-16，原文只有三态）：探针失败**不得**并进「未启用」——`unreachable` 只在非「503 + `admin_disabled`」时出现，显示逐字 `管理端暂时连不上：…`（附 `code · HTTP 状态`）与 `重试` 按钮，且该态下不挂 children、不发数据请求；`disabled` 态没有重试按钮（配了口令才有意义）。

具体交互：

- 概览页：当前索引卡片 + 版本历史表 + 重建流程三段式（preview 显示 `changed`、目标 hash 与 `corpus_counts`/`current` 两侧行数对照 → 二次确认框把这三样原样列出，**不显示 +N/−N 差值、不预测耗时**（§7 口径）→ 结果卡片显示 `reused` / `elapsed_ms` / counts）。`409` 单独提示"已有重建在跑"。`force` 有 UI 归属（R-M5-17，原文未写、Task 8 加的参数一度零消费者）：默认不勾选的原生 checkbox（`htmlFor` label 即可访问名，label 逐字 `强制重建（即使语料与规则未变化）`，说明行 `强制重建会新起一个索引版本；同步执行期间页面不可用。`），**只有一条发请求的路径**（不开第二个按钮），勾选态在 `running` 期间禁用，且 POST 一返回（成功与失败都算）立即复位——force 是一次性升级，不残留到下一次「确认重建」（R-M5-18）。
- 质量报告页：按 PRD 的 ①–⑦ 编号渲染七个数据面；**导出入口只有四个行表**（herb_diff / dose_deviation / parse_failure_details / annotation_items，§4.1 为准——本句原文写「七张表每张配『导出 CSV』」，与 §4.1「只有四张行表可导」自相矛盾，实现按 §4.1 落地，本轮回写订正）。③ 屏上按原因计数、导出给到明细行，链接文案逐字 `导出明细 CSV`（其余三节为 `导出 CSV`）。**§6.5 的"解析失败行点击跳到 distilled 源文件路径"按现实改口径**：浏览器打不开服务器本地文件、语料是 0600 权限（M0 前置），所以展示 `doc + source_row_no` 并提供复制，不提供伪链接——且这个可复制格在 `/admin/pending` 的候选行上（R-M5-20 搬迁，见 §4.1），质量页不展示它。
- 候选方名页：筛选 + 表格；三个动作行内展开（不开弹窗，沿用 M4 侧栏确认的风格）；归并的目标方选择器**复用 M4 的 `<SearchSuggest>`**（`POST /api/search`，`kind: ["formula"]`），不新做搜索；确认独立方的表单里原话显示"仅登记不建方"；已判定行默认展开留痕。
- 日志看板页：§8 的三块 + 顶部隐私提示行。

不引入任何 UI 组件库或图表库：卡片是纯文本，拒答频次是表格而不是柱状图。

## 10. 可访问性与视觉纪律

沿用 M4 已验收的那套：表格必须有 `<caption>` 与真 `<th scope>`；按钮有可访问名（不靠 `title` 传达关键信息）；写操作结果走 `role="status" aria-live="polite"`；破坏性操作的确认必须键盘可达——**不复现 M4 已知的"disabled 按钮 + title，键盘/AT 读不到"毛病**；对比度继续 `text-ink/70`（实测 ≈5.54:1）；焦点环沿用 `frontend/app/globals.css:14-20`。口令输入框 `type="password"`、`autoComplete="off"`，并有可见的标签文案。

## 11. 测试策略

**后端（pytest，`backend/tests/db/test_admin_api.py` 等）**

**加登录门前必须先改的既有测试（实测发现，不是推测）**：`backend/tests/db/test_search_api.py:17` 的 `_indexed()` 夹具直接 `client.post("/api/admin/reindex")` 并断言 200——它是整个 search 套件的建索引入口，门一上加就全线 401/503。改造方案：在 `tests/conftest.py` 里加一个 `admin_token` fixture monkeypatch `settings.admin_token`，并让 `client` fixture 默认携带已签发的 cookie（同时保留一个 `anon_client` 用于断言未登录态）。另外 `tests/db/test_admin_api.py:37-46` 的 `test_admin_endpoints_are_currently_unauthenticated` 是 E2 的**故意留痕**（docstring 自己说"E2 落地时这个测试会失败，强迫改动者回来把『匿名可访问』改成断言 401/403"）——本轮正是那个时刻，必须把它改写为"匿名访问返回 401/503"，并保留原 docstring 的意图说明，不要一删了之。**实际落地（T16 回写）**：该测试现为 `tests/db/test_admin_api.py:44` 的 `test_admin_endpoints_require_login`——匿名 `GET /quality-report`/`POST /reindex` 断言 401、带合法 cookie 断言 200，docstring 明写"§10 E2 的显式留痕换了方向，不是被删掉"；未启用 503 枚举在 `test_admin_gate.py::test_fail_closed_when_token_unset` 守。


1. fail-closed：未设 `ADMIN_TOKEN` 时受门端点与 `POST /session`、`GET /reindex/preview`、`GET /index-versions`、`POST /reindex` 一律 503 `admin_disabled`（枚举用例逐条点名）；**`GET /session` 探针是唯一 200 豁免**，返回 `{enabled:false,…}`（§3 的公开性设计，行为同样有枚举断言）。
2. 口令：错误口令 401；正确口令 → `Set-Cookie` 含 `HttpOnly`/`SameSite=Lax`/`Max-Age`；伪造签名与过期时间戳的 cookie 均 401。
3. 质量：端点响应的 key 集合与 `build_quality_report()` 的 dataclass 字段逐一相等（防"API 与报告两套口径"）；CSV 断言表头、行数与含逗号/引号字段的转义。
4. 审核：`merged` 后**立刻**用人工别名调 `/api/search` 能命中目标方（这条是"立即生效"的回归锁）；重复 `merged` → `alias_created=false` 且 `formula_alias` 行数不变；`target_formula_id` 不存在 → 404；三动作都写 `decided_by/decided_at`；`confirmed_new` 写 `decided_name`；审核后 `run_reindex` 一遍，断言四列人工字段未被抹掉。
5. 重建：`preview` 不写库（`index_version` 行数不变）；`POST` 成功 → 新行 `ready`、旧行 `retired`、report 字段齐；hash 全同且非 force → `reused=true` 且不产生新行；锁占用 → 409；复用现有 `fail_after_load` 注错 → 回滚后版本行与统计完全不变。
6. 日志：固定 `qa_log` fixture 断言四指标数值与拒答分组的排序、以及 `refused=false` 不进入拒答榜。

**前端（vitest + MSW）**：全局态三态文案（未启用/未登录/加载失败）、CSV 链接 href 与 `list` 参数、三个动作的表单校验与请求 body、重建三段式状态机含 `reused` 分支、看板数字确实来自 API 响应、归并选择器复用 `SearchSuggest` 的渲染。

**端到端（`frontend/e2e/admin.spec.ts`，serial）**：真实登录门；三页在 `zhongyi_e2e` 真实数据上渲染；候选方名页把某行归并到既有方后**在四大库检索里搜得到它**（本轮最有价值的浏览器证明）；重建按钮走 preview → 确认 → 完成。

**执行顺序硬约束**：重建用例会改动 `zhongyi_e2e`，所以 admin 套件排在既有 chat/library 套件之后（`playwright.config.ts` 声明 `projects: [app, admin]`，`workers: 1`；`admin.spec.ts` 顶部另有显式 `test.describe.configure({mode:"serial"})`——并发重建会撞 `REINDEX_LOCK` 出 409，顺序是契约不是巧合）。默认走 `force=false` 的 `reused` 路径，另开一条 `force` 用例**走 UI**（勾选 → 确认 → 版本行 +1 且四类计数不减少，不直接 POST），**不断言具体行数**——否则我们只是在给数据库写快照。已知张力如实登记：reused 基线用例里保留了一条 plan 带来的 `toContainText("1818")` 库快照读数（`zhongyi_e2e` 冷启动重建后的 chunk 数），与本句「不断言具体行数」方向相反；本轮按「不放宽既有断言」保留并加注释说明出处，判给整枝评审。口令注入形态（R-M5-24，原文「在 `playwright.config.ts` 注入 `ADMIN_TOKEN`」按实现回写）：**仓库内零口令字面量**（`playwright.config.ts`、`e2e/*.spec.ts` 与历史计划片段都已涂掉），`playwright.config.ts` 只读 `process.env.E2E_ADMIN_TOKEN`（≥16 字符，与后端 `auth.MIN_TOKEN_LENGTH=16` 同值），满足时以 `ADMIN_TOKEN` 注入后端 webServer env；**未设置/过短时 admin project 整个从 projects 里去掉并打印一行原因**——`--list` 是 26 条/3 文件而不是 42 条/4 文件，看到 26 条就是没设口令，不是管理端验过了。该情形退出码仍为 0 是已知残留（仓库当前没有 CI），是否改非零退出留给整枝评审，**本轮回写时仍未做**。

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

**标签层的一条有意取舍（R-M5-23，本轮回写）**：`invalid_decision_payload` 在前端 `ADMIN_ERROR_LABELS`（`frontend/lib/admin.ts`）里有对应闭集标签「参数不完整」，所以命中它的用户看到的是这个标签，端点按场景逐字段生成的 message 原文（`_invalid_payload`，如「`merged` 需要 `target_formula_id`」）**被有意吞掉**——表里没有的 code 才会透出后端原文。若要改为透出逐字段原因，是**下一轮的决定**，本轮未做，代码注释与本报告都按此陈述。

## 13. 本设计的边界条目（编号供本文内部引用；实现完成后同步进 M4 设计规格 §13 与 PRD）

1. 单维护者共享口令，无用户体系；`decided_by` 固定 `"admin"`。
2. **本轮之前 `/api/admin/quality-report` 与 `/api/admin/reindex` 已匿名上线**（`main.py:33-35` 自陈是 E2 未决的故意留痕）。所以本轮不是"新接口配鉴权"，而是**给一个已暴露的重建能力补上门**；实现期间两者在测试与 e2e 配置里必须同时受门，且 `test_admin_api.py:37-46` 的留痕测试必须改写而非删除。
3. `/chat/:sessionId` 仍无鉴权即公开（症状文本可被任何拿到链接的人读取）——本轮不解决，属 E2。
4. 日志保留期/删除权/是否用于微调未定义；本轮只在 UI 顶部加提示，不加策略。
5. 反馈表 `answer_log` 与 👍/👎 未做，"按 👎 筛 bad case"仍无数据源。
6. 重建是同步单事务原子发布，**不是双索引蓝绿**；无 `building` 中间态，横幅如实显示"当前索引 + 上次重建结果"。多进程部署需 DB 级咨询锁替换进程内锁。
7. `confirmed_new` 仅登记不建方；ETL 读 `decision` 回流建方是独立一轮。
8. "解析失败行跳源文件"降级为"显示路径 + 行号 + 可复制"；且这格最终落在 `/admin/pending` 的候选行上而非质量页（R-M5-20 搬迁，见 §4.1），质量页页脚保留路标句（R-M5-21；该页脚**零断言**，靠人读，登记在此）。
9. dev 库需手工 `ALTER TABLE ... ADD COLUMN decided_name`；生产建表/迁移路径仍是 issue #7 的未决项。
10. CSRF 只靠 `SameSite=Lax` + POST，公网部署前必须补 Origin 校验与 TLS。cookie 的 `secure=False` 是本地明文 http（`127.0.0.1`）下的刻意选择，不是遗漏；HTTPS 落地时同轮必须翻成 `True`。
11. **错误形状的不一致面（执行期登记，不装全局 handler）**：admin 端点自己抛的错都是 `{"detail": {"code", "message"}}` 两键形状，但 FastAPI **参数层**的类型/越界失败仍是默认的 `{"detail": [数组]}` 形状——具体触发面：路径参数 `pending_id="abc"`；`GET /pending` 的 `limit=abc` 这类非整数串、负 `offset`（该端点参数层仍保留 `ge=0`）、`decision`/`reason` 超长；`refused=abc` 这类非布尔串；非布尔 `force`。注意区分：`/logs` 与 `/logs/*` 的数值越界已改为端点内钳制+回显（`offset` 在那里钳到 ≥0，不报错），`GET /pending` 的 `limit` 同样钳制——R-M5-8/R-M5-12/R-M5-13 的收口只覆盖了这几处，上面列出的参数面**仍是数组形状**。**本轮不装全局 `RequestValidationError` handler**——那会改掉 M4 已验收端点的错误形状，超出管理端范围。
12. `merged` 的"移动"按 `(raw_name, doc)` 生效、**不按 pending 行**（R-M5-6 的精确后果）：两条共享同一 `(raw_name, doc)` 的 pending 行，归并第二条会删掉第一条的人工 alias（删除严格限定 `kind=人工归并`，绝不碰 loader 写入的行），而**第一条自己的 `decision` 仍显示「已归并」**——它的行状态不随 alias 被移动而回滚。UI 在归并表单里如实写出这一口径（逐字见 §15），不承诺更强的隔离。
13. **没有按行撤销归并的端点**，UI 也不得提供或暗示（`admin-pending.test.tsx` 锁住屏上不得出现「撤销/回退/恢复/undo」字样）。纠正途径只有再归并一次（即第 12 条的行级移动）。
14. `note` 字段：决策端点请求体**接受**它，M5-A **不持久化**（表里无对应列）。UI 因此不提供备注框——不给会静默吞掉输入的字段留入口。是否入库留下一轮。
15. `GET /api/admin/pending` 缺省只返回 `decision=pending` 的行（R-M5-10，规格 §4 表格为权威、计划 snippet 作废）；显式空串 `?decision=` 是唯一的"看全部"通道，队列页只用四个具体值（`admin-pending.test.tsx` 有用例锁住页面永远不发空串）。同族形状：`/admin/logs` 的 `intent=` 显式空串＝全量透传。
16. 队列页一次请求 `limit=200`（端点钳制并回显；真实队列 64 行、其中 `no_formula_name` 57，在 200 之内）。**分页 UI 没有**：`total > 200` 时屏上提示语的最后一句仍是「请用筛选缩小范围」——当筛选也缩不到 200 以内时，这句是给不到的建议，如实登记为边界（请求发 `limit=200` 与截断提示行上屏各由单测钉住：`admin-pending.test.tsx` 的 `:589-601` 与 `:604-615`；「缩小范围」这四个字本身在断言命中的 `<p>` 之内，但未逐字钉）。
17. 管理端 e2e **运行文件里没有兜底口令**：跑之前必须 `export E2E_ADMIN_TOKEN=你的口令`（至少 16 字符，只在 shell env，绝不写进任何进仓库的文件）。未设置/过短时的实测行为 = **排除 admin project 并打印原因**（不是 globalSetup 抛错）：`--list` 显示 26 条/3 文件而非 42 条/4 文件，stderr 打一行原因，退出码仍是 0（已知残留，本轮未改，见 §11）。**仓库零字面量（整枝评审已处置）**：本文与 PRD 原先把承诺写成"e2e **运行文件**零字面量"，
因为被跟踪的历史计划文档 `docs/superpowers/plans/2026-11-02-m5-admin-console.md` 的 Task 15 片段里
还留着被 R-M5-24 废弃的兜底串。处置方式是**涂掉计划片段**而不是继续放宽措辞——
留在被跟踪文档里的一条形似凭据的串，将来谁加真口令都会照抄那个位置；
被忽略的 `.superpowers/**` 规划材料不作为承诺对象。措辞已改回"仓库零字面量"，实测全仓 grep 为 0 命中。
18. 筛选竞态的收口是**不对称**的：`/admin/pending` 已收口——`load()` 有自增序号陈旧响应守卫（晚到的旧筛选结果被丢弃，不取消请求；不用 timer），并由一条确定性单测钉住"去掉守卫必翻红"（`ed65faa`）。`/admin/logs` 的 `intent` 筛选同样重跑 `load` 且三个请求 `Promise.all` 后**按到达顺序写覆盖、没有守卫**——同一类"筛选框显示新值、表格显示旧结果"的形状只是没有卸载窗口放大；`/admin` 与 `/admin/quality` 不暴露此形状。是否统一抽 `useLatestRequest()` 留给整枝评审，**不得写成"全站已无竞态"**。
19. 门（AdminShell）的两个残余误诊面（T10 登记）：被代理改写/非 JSON 的 503 会显示「管理端暂时连不上」而非「未启用」；200 但缺 `enabled` 键的响应会走 `!session.enabled` 显示未启用文案。两者都不泄漏数据（不挂 children、不发数据请求），错的是措辞归类。
20. `_parse_target_formula_id` 沿用整数可解析串的宽松（`"999999"`、`"5_0"`、`"+5"` 都能进 404 判定而非 422）；且非 `merged` 动作会**静默忽略**非法 `target_formula_id`（不报错也不生效）。与第 15 条的空串通道同族，登记为形状边界。

## 14. 验收清单（M5-A 自证）

1. 不设 `ADMIN_TOKEN` 时，`/admin` 四页与 `/api/admin/*` 全部呈现"未启用"，且没有任何一条只读数据泄漏。
2. 正确口令登录后，质量报告七张清单全部渲染，且各表行数与 `/api/admin/quality-report` 响应逐条对得上；任选一张表导出的 CSV 能被表格软件正确解析（含引号字段）。
3. 待审队列渲染成功。**基线读数（非断言）**：2026-11-02 实测 `zhongyi_e2e` 有 64 行 pending，其中 `reason=no_formula_name` 57 行、`multi_name_row` 3、`pair_without_composition` 3、`no_composition` 1。这些数字**不写进任何测试断言**——审核用例本身就会改动它们。测试只断言不变量：列表 `total` 等于后端响应、`reason` 筛选后每行的 `reason` 都等于所选值、已判定行不再出现在 `decision=pending` 视图里。
4. 归并动作完成后：`formula_alias` 新增一行 `kind=人工归并`、`pending_formula_name.decision/decided_by/decided_at` 被写入、**不重建索引**即可用人工别名在 `/api/search` 与四大库列表精确命中目标方。
5. 重复归并同一目标不产生第二条 alias，UI 提示"该别名已存在"。
6. `run_reindex` 之后，上述人工字段与 `decided_name` 全部保留（有测试断言，非口头保证）。
7. `confirmed_new` 写入 `decided_name`，且表单与列表都能看到"仅登记、不建方"的原话提示。
8. 重建 preview 显示的 `changed`/`will_reuse` 与随后 `POST /reindex` 的判定一致（同一个四元组复用谓词，R-M5-14；原句的 `delta` 未实现，见 §7）；四元组未变且非 force 时 `reused=true` 且不新增 `index_version` 行。
9. 重建进行中并发第二个请求得到 409，UI 有对应文案，不出现两个版本行同时 `ready`。
10. 日志看板四卡片数值与 `qa_log` 手算一致，拒答榜按次数降序且不含非拒答记录；顶部隐私提示行可见。
11. `/admin` 四页 + 未登录态 + 重建确认对话框在 axe `wcag2a`/`wcag2aa` 下 serious/critical = 0。
12. 全量回归：后端 pytest、`npx vitest run`、`PW_BROWSER_CHANNEL=chrome npx playwright test` 全绿，且既有 chat/library/a11y 套件未被放宽任何断言。

## 15. 产品文案逐字清单（M5-A 执行期新增，本轮回写收口成一处）

以下串**逐字**上屏并被测试钉住（出处列为断言所在；改文案=改契约，需同轮改断言）。行号以 `feat/m5-admin` 收口态为准。

| 文案（逐字） | 上屏位置 | 断言出处 |
|---|---|---|
| `管理端暂时连不上：…`（后随 `code · HTTP 状态` 诊断串） + 按钮 `重试` | 门 `unreachable` 态（`AdminShell.tsx:84-87`） | `tests/unit/admin-gate.test.tsx`（500→可重试且不发数据请求） |
| `管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）` | 门 `disabled` 态（前后端同串：`admin.py:_admin_disabled` 与 `admin.ts:167`） | `admin-gate.test.tsx`（503 admin_disabled 无重试按钮） |
| `强制重建（即使语料与规则未变化）` | 概览页 force 复选框 label（`ReindexPanel.tsx:113`） | `admin-panels.test.tsx:114`、e2e `admin.spec.ts` 的 checkbox 可访问名 |
| `强制重建会新起一个索引版本；同步执行期间页面不可用。` | force 说明行（`ReindexPanel.tsx:114`） | `admin-panels.test.tsx:115` |
| `构建摘要` | 版本历史卡片 dl 标签（`VersionTable.tsx:38`；替换名不副实的 `skipped` 标签——`notes` 不止 skipped 一个键） | `admin-panels.test.tsx:132` |
| `导出明细 CSV`（其余三节为 `导出 CSV`） | 质量页 ③ 导出链接（`app/admin/quality/page.tsx:81`） | `admin-panels.test.tsx:586-597`、e2e `admin.spec.ts:114` |
| `屏上按原因计数，导出给到可下钻的明细行。` | 质量页 ③ 说明行（`page.tsx:82`，经 `aria-describedby` 附到表格） | `admin-panels.test.tsx:566/569`（`toHaveAccessibleDescription`） |
| `⑤⑥⑦ 不提供导出；③ 屏上按原因计数，导出给到明细行。要下钻待审真实行请去「候选方名」页。` | 质量页页脚现值（`page.tsx:121`，**报告里的旧串作废**；路标句按 R-M5-21 保留） | 零断言（登记为 §13-8 边界） |
| `判定已记录，该别名已存在。`（含闭集逐字 `该别名已存在`，且不得出现「新增」二字） | 归并幂等分支播报（`PendingTable.tsx:59`；§14-5：brief 同时要求说明未新增又禁止「新增」字样，按意图闭合） | `admin-pending.test.tsx:311-327` |
| `判定提交中，请稍候…（提交进行中，按钮已禁用，请勿重复点击）` | 写操作在途原因行（全局禁用，R-M5-22；`PendingTable.tsx:146`） | `admin-pending.test.tsx:374-382`（延迟 promise、不用 timer，双击只发一次 POST） |
| `判定留痕：{decided_by} · {decided_at 的 toLocaleString("zh-CN")}` | 已判定行次级留痕行（`PendingTable.tsx:200`，沿用 M4 格式化口径） | `admin-pending.test.tsx`、e2e 的 merged 筛选态 + axe `colSpan===7` |
| `复制失败，请手动选择路径` | 路径格剪贴板失败分支（`PendingTable.tsx:83`；只在真失败时上屏，成功才播报成功） | `admin-pending.test.tsx:70-74`（前置 `expect(navigator.clipboard).toBeUndefined()`）。**历史材料点名**：T12 brief 逐字给的处理器（`await navigator.clipboard?.writeText(path)` 后**无条件**播报成功）是说谎片段，未采用；落地形态是 `try/catch`、失败绝不播报成功 |
| `仅登记，不建方：ETL 读取判定结果建方属下一轮范围。` | 确认独立方表单（`PendingTable.tsx:171`；既有闭集 `仅登记，不建方` 的确认，本轮无改） | `admin-pending.test.tsx:137-143` |
