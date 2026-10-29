# M2：混合检索 + 四大库 API

> 前置：M1 已完成（`feat/m1-data-foundation`，22+ commits，172 passed + 1 xfail）。
> 对应 PRD：FR-2 混合检索、FR-7/8/9/10 四库浏览、§5.4 API、附录 C。
> 目标：让「查得到、查得准、引用可回溯」在 API 层成立；**不接 LLM、不做对话**（M3）。

## Global Constraints

- **精确匹配优先于语义**（FR-2）：方名/药名/穴名整名命中必须排在向量结果之前；
  B/C 类查询不允许被模糊结果污染。排序是**规则**，不是模型。
- **药名精确匹配必须同时覆盖 `herb.name`（本经古名）与 `herb.alias`（现代名）**：
  问「桂枝」必须命中 `牡桂` 条目，而不是只落到语义召回（现状问题 1）。
- **`formula_alias.kind=加减写法` 的行里 `name` 存的是母方名**（见 `test_models_roundtrip.py:73`），
  因此**不得**把该 kind 当作「本方的别名」参与精确召回——否则查「桂枝汤」会命中 30+ 个加减方。
- **检索切片是摘要，不是全文**：`POST /api/search` 返回的 snippet 截断 200 字；
  全文只由 `GET /api/evidence/{ref}` 提供（FR-2 Task 13 定稿）。
- **查询向量与索引向量必须同一模型**：`IndexVersion.embedding_model_version` 与当前 embedder
  不一致时返回 503 并说明，不得用哈希向量去查 BGE-M3 索引（反之亦然）。
- **无索引即失败**：没有 `status=ready` 的 `index_version` 时返回 409「索引未构建」，不静默返回空列表。
- 单测**不得下载模型**：一律 `HashingEmbedder`；真实 BGE-M3 只在 `ZY_ALLOW_INTEGRATION=1` 下跑。
- 分页与 `top` 必须有上限（`top ≤ 50`、`limit ≤ 100`），避免一次拉全库。
- 所有 ref 解析只接受白名单 `ref_type`；未知类型返回 400，未知 id 返回 404。

## File Structure

- `backend/app/search/__init__.py`
- `backend/app/search/query.py` —— 查询规范化、分词/字面重叠、纯排序合并函数
- `backend/app/search/retriever.py` —— 精确召回 + 向量召回 + 字面召回 + 标题/锚点装配
- `backend/app/db/schema.py` —— `ensure_search_indexes(engine)`（HNSW cosine）
- `backend/app/api/__init__.py`
- `backend/app/api/schemas.py` —— 响应模型
- `backend/app/api/search.py` —— `POST /api/search`
- `backend/app/api/formulas.py` —— `/api/formulas`、`/api/formulas/{id}`
- `backend/app/api/library.py` —— `/api/herbs`、`/api/acupoints`、`/api/cases`
- `backend/app/api/evidence.py` —— `GET /api/evidence/{ref}`
- `backend/app/api/tools.py` —— `POST /api/tools/dose-convert`
- `backend/app/etl/aliases.py` —— 别名补录（纯函数，供 loaders/corpus 调用）
- 测试：`backend/tests/unit/test_search_ranking.py`、`backend/tests/db/test_alias_backfill.py`、
  `tests/db/test_search.py`、`tests/db/test_formula_api.py`、`tests/db/test_library_api.py`、
  `tests/db/test_evidence_api.py`、`tests/db/test_dose_api.py`、`tests/db/test_search_acceptance.py`

---

## Task 1：`formula_alias` 补录（M1 缺口的收口）

**背景（实测）**：M1 建了 `formula_alias` 表，但 `loaders.load_corpus` 从未写入任何行
（M1 计划 Task 12 自然键表里只写了「跳过」）。M2 的方剂详情要展示加减方谱系、搜索要按
`汤方尾巴` 命中，这个缺口必须先在 ETL 层补上，不能在 API 层猜。

**两条可判定的规则，宁缺勿造**：

1. **`汤方尾巴`**：克数源里被观测到的原始写法，剥 `方` 尾后才等于规范名（如 `乌梅丸方` → `乌梅丸`）。
   实测原始候选 15 条，其中 1 条是合方串（`厚朴麻黄汤方+泽漆汤方`，字段上是单名但 `kind=pair`）
   → **只收 `kind=single`** → **14 条**。
   落 `formula_alias(name=原始写法, doc="方剂库-经典配方.md", kind="汤方尾巴")`。
2. **`加减写法`**：方名以某个**已确认且带剂量 variant** 的方名为字面前缀，后接 `加/去/减`
   （`桂枝汤加葛根` → `桂枝汤`；`桂枝加葛根汤` → `桂枝` + `汤` 补全 → `桂枝汤`）。
   实测 39 条结构匹配，其中 4 条的母方（`柴胡汤`×3、`白通汤`）只出现在方证出处/方名里、
   没有任何剂量 variant → 剔除，**落 36 条**。落 `formula_alias(name=母方名, doc="方名结构推导", kind="加减写法")`。
   `doc` 如实写「方名结构推导」：这是方名结构证据，不是某份文档的说法。

**不做**：不推断 `古名/现代名` 方名对、不做 `一行多方拆分` 别名（来源行多义，已进候选队列），
不因别名做任何 `formula` 合并（D6）。

**Interfaces:**
- `aliases.derive(formula_names, parent_pool, classic_candidates) -> list[AliasRow]`
  - `AliasRow(formula_name, name, doc, kind)`
  - `parent_pool`: 有剂量 variant 的方名集合
  - `classic_candidates`: `[(raw, normalized)]` 单名行原始/规范写法
- `loaders.load_corpus` 新增写入 `formula_alias`，冲突键 `(name, doc)` → `DO NOTHING`。

- [x] **Step 1: 写失败测试**（36 / 14；桂枝加葛根汤←桂枝汤；柴胡加芒硝汤无谱系；`汤方尾巴` 14 条）
- [x] **Step 2: 实现 `aliases.derive`**
- [x] **Step 3: 接入 `build_corpus`/`loaders`，跑两遍 reindex 计数不变**
- [x] **Step 4: 校准并记录实测数（不得沿用本计划的预估值）**

**验收（已完成，2026-10-29）**：`formula_alias` 实测 **50 行**（36 谱系 + 14 尾巴）；
桂枝加葛根汤的 `加减写法` 行 `name="桂枝汤"`；柴胡加芒硝汤无谱系；
重复入库行数不变；`alias` 计数进入 `load_summary.counts`。
**附带修正**：`formula_alias` 唯一键由 `(name, doc)` 改为 `(formula_id, name, doc)`——
27 个桂枝汤加减方都写 `name="桂枝汤"`，旧键只留得下一条。旧开发库需重建（无迁移工具）。

---

## Task 2：检索核心（精确 + 向量 + 字面，规则 rerank）

**Interfaces:**
- `query.normalize_query(q: str) -> str` —— 全半角/空白规范化；
  方名查询再走 `identity.normalize_name`（`射干麻黄汤方` → `射干麻黄汤`），但**保留原串**用于展示。
- `query.literal_score(query, content) -> float` —— 中文按 1/2-gram 覆盖面计分（0~1）。
- `query.merge_hits(exact, vector, literal, *, top) -> list[Hit]`
  - 去重键 `(ref_type, ref_id)`；同名多切片只保留最高分
  - 排序键 `(channel_rank, -score)`，`exact=0 / vector=1 / literal=2`（FR-2）
  - `Hit(ref_type, ref_id, title, snippet, score, match, anchor)`
- `retriever.search(session, q, *, kinds, section, top, embedder) -> SearchResult`
  - 精确：`formula.canonical_name` / `formula_alias`（**排除 `加减写法`**）/ `herb.name` + `herb.alias` /
    `acupoint.name`；query 必须先规范化再整名相等
  - 向量：`ChunkVector.embedding.cosine_distance(vec)` 升序，取 `top*5`（上限 100）
  - 字面：`chunk_vector.content ILIKE %query%`（完整 query，长度 ≥ 2），取 `top*5`
  - `section`：只对 `formula`/`evidence` 生效，匹配 `formula_evidence.six_jing` 或 `bing_duan`；
    其他 kind 在给定 section 时被过滤
  - 标题/锚点批量装配（不做 N+1）：
    方剂 → 证据 `source_doc#six_jing|bing_duan#clause_no`，无证据则 variant 源文档；
    药 → `04-神农本草经/中药库.md#<name>`；穴 → `05-针灸/十二经穴位库.md#<meridian>#<name>`；
    医案 → `06-医案/临床问答对.md#<no>`；框架 → `<doc>#<section>`
  - 索引守卫：无 ready 版本 → `IndexNotReady`；模型版本不一致 → `EmbeddingMismatch`

- [x] **Step 1: 写失败测试（纯函数层）**：exact 压过更高分的 vector；同名多切片去重；`top` 截断；
      kind 过滤；字面分只由 overlap 决定
- [x] **Step 2: 实现 `query.py` 并通过单测**
- [x] **Step 3: 实现 `retriever.py` + `db/schema.py:ensure_search_indexes`**
- [x] **Step 4: 在 `run_reindex` 末尾创建 HNSW（`IF NOT EXISTS`），conftest 建表后同样创建**
- [x] **Step 5: DB 集成测试**（真实语料 + HashingEmbedder）：`射干麻黄汤` 精确第一；
      `桂枝` 精确命中 `牡桂`；`咳嗽气喘痰白不能平躺` 的向量 Top-5 至少含 `杏仁` 或 `桑白皮`
      （以实测为准，测前先跑一遍看结果，不得先写断言）

**验收（已完成，2026-10-29）**：199 passed + 1 xfail。实测：
- `射干麻黄汤` → formula exact 第 1，锚点 `03-金匮/金匮方剂库.md#辨肺痿肺痈咳嗽上气病脉证治`
- `桂枝` → herb exact 第 1，标题 `牡桂`（HR-2 的现代名/古名合并成立）
- `桂枝汤` 的 exact 只有 1 条；36 个加减方只出现在 vector 通道（`加减写法` 未污染召回）
- `咳嗽气喘痰白不能平躺` → herb Top-5：白前 0.301、**杏核仁 0.291**、诃黎勒、天门冬、五味子；
  case 通道第 1 为 `问11`。这是 HashingEmbedder 的词袋结果，**不是语义质量证明**
- `section="太阳"` 前缀匹配语料里的 `太阳病`；`section="少阴"` 正确排除无少阴出处的桂枝汤
- HNSW(`vector_cosine_ops`) 由 reindex 在同一事务内创建

**已知限制**：17/426 个方名既无 evidence 也无 variant（合方无组成、医案中的候选名），
锚点落为 `方名候选#<name>`，不是真实文件路径。M2 不隐藏这些结果，但在前端应以「未溯源」样式呈现。

---

## Task 3：`POST /api/search`

**Request**：
```json
{"query": "射干麻黄汤", "kind": ["formula"], "section": "太阳", "top": 10}
```
`query` 长度 1–200；`kind` 省略 = 全部；`top` 默认 10、上限 50；`section` 可选。

**Response**：
```json
{
  "query": "射干麻黄汤",
  "normalized_query": "射干麻黄汤",
  "index_version": {"id": 3, "commit_hash": "d10f9cb…", "embedding_model_version": "hashing-2026.10"},
  "hits": [{"ref_type": "formula", "ref_id": 12, "title": "射干麻黄汤",
            "snippet": "射干麻黄汤｜组成：…", "score": 1.0, "match": "exact",
            "anchor": "方剂库-经方组成.md#射干麻黄汤"}]
}
```

**边界**：索引未构建 → 409 `{"detail": {"code": "index_not_ready"}}`；模型版本不符 → 503
`{"detail": {"code": "embedding_mismatch", ...}}`；空 query → 422；未知 kind → 422。

- [x] **Step 1: 写失败测试**（200 结构、kind/section 过滤、top 上限、409/503/422）
- [x] **Step 2: 实现 `api/schemas.py` + `api/search.py`，在 `create_app` 注册**
- [x] **Step 3: 用 `dependency_overrides` 跑真实语料，核对锚点可读**

**验收（已完成，2026-10-29）**：6 个 API 用例全绿；409/503/422 的 `detail.code` 分别为
`index_not_ready` / `embedding_mismatch` / FastAPI 校验错误。

---

## Task 4：方剂库 API（FR-7）

- `GET /api/formulas`：`q`（规范名/别名 contains）、`six_jing`、`bing_duan`、`status`、`kind`、
  `herb`（古名或现代名 → `formula_item.herb_id` 反查）、`limit/offset`。
  单项含 `id, canonical_name, status, kind, variant_count, evidence_count, dose_complete`。
- `GET /api/formulas/{id}` 返回：
  - `aliases[]`（含 kind；`汤方尾巴` 用于展示）
  - `lineage`：`parent`（读 `加减写法` 别名 → 母方）与 `children[]`（以本方为母方的加减方）
  - `variants[]`：`source_doc, dose_basis, raw_composition, items[]`
    （`herb_text, herb_name, dose_text, dose_g, dose_state, preparation, conversion_note`）
  - `dose_complete`：每个 variant 独立 + 整方（任一药味非 `exact` 即 false，FR-3/NFR-4）
  - `pairs[]`：`variant_a/b` 的源文档与药味差异 `herb_diff`、剂量偏差 `dose_dev`、
    `score, algorithm_version, pairing_method`（读 ETL 物化结果，不运行时算，D8）
  - `components[]`：`kind=pair` 时两个成分方的 `id/canonical_name/items`
  - `evidence[]`：六经/病段/条文号/原文
  - `cases[]`：引用本方的医案号
- **禁止**把 `加减写法` 别名当作本方别名展示；谱系必须走 `lineage`。

- [ ] **Step 1: 写失败测试**（桂枝汤 detail：有 variant_pair、children 含桂枝加葛根汤；
      桂枝加葛根汤 detail：parent=桂枝汤 且自身无 pair；合方 detail 有 components；
      `herb=桂枝` 反查含桂枝汤；`six_jing=太阳` 过滤）
- [ ] **Step 2: 实现列表 + 详情，分页**
- [ ] **Step 3: 核对真实数值（pair 77、component 28 的落点）**

**验收**：D6 在 API 层可见——桂枝加葛根汤不出现在桂枝汤的 `variants` 里，只出现在 `lineage.children`。

---

## Task 5：中药 / 针灸 / 医案 API（FR-8/9/10）

- `GET /api/herbs`：`q` 同时匹配 `name` 与 `alias`；`taste_group`、`organ_group`、`flavor_state`；
  返回 `formula_count`（`herb_id` 反查；悬空药味不计入并在文档注明 FR-13 ⑤）。
  `GET /api/herbs/{id}`：全字段 + `formulas[]`（id/name）+ `flavor` 为空时 `flavor_state=missing`
  （不生成推测文案）。
- `GET /api/acupoints`：`q` 名、`meridian`、`role`、`symptom`（`acupoint_symptom` contains，
  按症取穴）；`GET /api/acupoints/{id}`：穴位 + `symptoms[]` + 来源文档。
- `GET /api/cases`：`category`、`q`（主诉）；`GET /api/cases/{id}`：四段 + `treatment_formulas[]`。
- 药/穴/案列表均 `limit ≤ 100`、`offset`。

- [ ] **Step 1: 写失败测试**（`桂枝`→`牡桂`；`flavor_state=missing` 的条目存在；
      `symptom=项强` 至少返回后溪/天柱（实测校准）；医案 30、`问11` 治方含射干麻黄汤）
- [ ] **Step 2: 实现三个模块，注意 `formula_count` 用聚合而非逐行查询**
- [ ] **Step 3: 实测并回填断言**

---

## Task 6：证据回溯与剂量换算 API

- `GET /api/evidence/{ref}`：`ref = <ref_type>:<id>`，白名单
  `formula|evidence|herb|case|acupoint|framework`。
  - `evidence` → `original_text` 全文 + 六经/病段/条文号
  - `formula` → 全部 variant 的 `raw_composition` + items + evidence（**不截断**）
  - `herb` → 全字段（`raw_note` 全文）
  - `case` → `raw_md`；`acupoint` → 全字段 + symptoms；`framework` → 该 chunk 全文
  - 响应统一 `{ref_type, ref_id, anchor, text, fields}`
- `POST /api/tools/dose-convert`：`{herb, dose}` → `{g, dose_state, trace}`，
  直接调 `app.etl.dose.convert`，**不在 API 重算**（PRD §5.4）。

- [ ] **Step 1: 写失败测试**（`evidence:<id>` 全文；`formula:<id>` 含古制留痕；
      非法 ref_type→400；不存在→404；`半夏 半斤`→60/exact；`大枣 十二枚`→count_only；
      `甘草 二分`→absent）
- [ ] **Step 2: 实现 + 注册**
- [ ] **Step 3: 与 PRD 附录 B 的六个实测样例逐一对照**

---

## Task 7：验收与诚实边界（E3 / BGE-M3）

PIPELINE §6 两条样例，按**可在当前环境验证的部分**拆开：

| 查询 | 当前可验证 | 依赖 |
|---|---|---|
| ①「咳嗽气喘痰白不能平躺」 | 药 Top-5 含 杏仁/桑白皮（以实测为准）；医案命中问11 | 语义质量需 BGE-M3 |
| ②「发烧怕冷头痛颈项强急脉浮」 | 穴 风池/后溪/天柱（精确/字面）；药 麻黄 | 六经脉象语义需 BGE-M3 |

- [ ] **Step 1: 写 `test_search_acceptance.py`，只断言实测通过的部分**
- [ ] **Step 2: 语义验收标记 `@pytest.mark.integration` + `ZY_ALLOW_INTEGRATION=1`，
      未安装 sentence-transformers 时 skip 并打印原因**
- [ ] **Step 3: 在 PRD §8 M2 行与 §10 E3 写明：M2 的「命中达标」目前只到结构/精确层，
      语义层待 E3 评测集与真实 embedding**

**验收**：测试全绿；skip 原因可读；不把 HashingEmbedder 的结果冒充语义检索质量。

---

## 已知风险与不做的事

- `HashingEmbedder` 是词袋哈希，**没有语义能力**；M2 的向量通路只证明管线正确，不证明检索质量。
- `herb_id` 悬空 449 行：反查与 `formula_count` 会偏低，这是 FR-13 ⑤ 的已知失真面，不在 M2 修。
- 不做 `POST /api/chat`、不做意图分类、不做拒答阈值（M3/D2）。
- 不做前端；四大库 API 的字段以 PRD FR-4 为准。
- 不引入 ORM 迁移工具：`ensure_search_indexes` 是幂等 DDL，随 reindex 与测试建表执行。
