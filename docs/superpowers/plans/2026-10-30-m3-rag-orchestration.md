# M3 RAG 编排链 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 PRD FR-1/3/4/5/6/15 的后端编排链：意图分类 → 检索 → 证据门禁/拒答 → 剂量工具 → 结构化回答 → 免责声明 → 会话与问答日志 → SSE 输出。

**Architecture:** 编排是**确定性 Python**：剂量、拒答、引用锚点、免责声明全部由服务端计算，LLM 只负责把已定稿的结构写成 `prose` 字段。因此 M3 可在无 API Key、无模型下载的环境下完整测试（`FakeLlm`）；真实 provider 通过 OpenAI 兼容适配器接入，未配置时不得联网。

**Tech Stack:** FastAPI、pydantic v2、SQLAlchemy 2.x + PostgreSQL/JSONB、现有 `app.search.retriever`、`app.etl.dose`、`app.search.anchors`、pytest。

**Spec:** `docs/需求文档-RAG系统.md`（FR-1/3/4/5/6/15、D1/D2）、`PIPELINE.md` §6–§7、`.claude/skills/*/SKILL.md`

## Global Constraints

- 剂量只出**克**，古制在括号留痕：`茯苓 45g（三两，1两≈15g）`；非 exact 态保留原文、不得造数（NFR-4）。
- 无证据必须拒答；拒答时不得出现任何方/药/穴的疗效断言，只给候选与"本地库未收录"。
- 免责声明由服务端追加，不依赖模型：`本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。`
- 单测不得下载模型、不得访问网络；真实 LLM 只允许在显式配置 `LLM_API_KEY`（`.env`，pydantic-settings 无前缀）时启用。
- 管理端仍无鉴权（E2 未定稿），M3 不改鉴权。
- 所有测试用 `backend/.venv/bin/python -m pytest ...` 运行；integration 用例默认 deselect。
- 切片/索引不改动；M3 只读已有表。新增会话/日志表的建表目前只在测试夹具 `backend/tests/conftest.py` 中执行；生产/开发库初始化路径未提供，留待 M5 部署。
- 每完成任务即提交；提交信息沿用仓库风格 `feat(m3): …` / `test(m3): …`。

---

### Task 1: 意图分类（FR-1）

**Files:**
- Create: `backend/app/rag/__init__.py`
- Create: `backend/app/rag/intent.py`
- Test: `backend/tests/db/test_rag_intent.py`

**Interfaces:**
- Produces: `Intent`（StrEnum，值 `A/B/C/D/E/F`）、`classify(session, query) -> Intent`、`mentions(session, query) -> dict[str, tuple[int, str]]`。
- `mentions` 的 key 是 `formula/herb/acupoint`，value 是 `(id, 正名)`；组合链与实体门禁复用。

- [x] **Step 1: 写失败测试**

```python
import pytest

from app.admin.reindex import run_reindex
from app.rag.intent import Intent, classify, mentions


@pytest.fixture
def indexed(db_session):
    run_reindex(db_session)
    return db_session


@pytest.mark.parametrize("query, expected", [
    ("桂枝汤", Intent.formula),
    ("桂枝加葛根汤", Intent.formula),
    ("桂枝", Intent.herb),
    ("牡桂", Intent.herb),
    ("风池", Intent.acupoint),
    ("咳嗽气喘按什么穴", Intent.acupoint),
    ("问11", Intent.case),
    ("咳嗽气喘痰白不能平躺", Intent.syndrome),
    ("太阳病怎么办", Intent.syndrome),          # 太阳也是穴位名，裸名不得抢走六经问句
    ("桂枝汤配合风池穴怎么用", Intent.composite),
])
def test_classify(indexed, query, expected):
    assert classify(indexed, query) == expected


def test_mentions_picks_longest_name_inside_sentence(indexed):
    found = mentions(indexed, "桂枝加葛根汤配合风池穴")
    assert found["formula"][1] == "桂枝加葛根汤"
    assert found["acupoint"][1] == "风池"
    # 别名也算命中，但返回正名：桂枝 → 牡桂（FR-8）
    assert mentions(indexed, "桂枝")["herb"][1] == "牡桂"
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_intent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.rag'`

- [x] **Step 3: 最小实现**

`backend/app/rag/__init__.py` 留空。

`backend/app/rag/intent.py`:

```python
"""FR-1 意图分类：确定性规则，离线可测；LLM few-shot 是后续增强，不是前置条件。"""

import re
from enum import StrEnum

from sqlalchemy import select

from app.db.models import Acupoint, Formula, FormulaAlias, Herb
from app.search import query as qmod


class Intent(StrEnum):
    syndrome = "A"
    formula = "B"
    herb = "C"
    acupoint = "D"
    case = "E"
    composite = "F"


_CASE_NO = re.compile(r"问\s*\d+")
_ACUPOINT_CUE = re.compile(r"穴位|配穴|取穴|扎针|针灸|按穴|针哪|什么穴")
_COMPOSITE_CUE = re.compile(r"同时|以及|还有|并且|配合|怎么配|加上")


def _best_mention(q: str, rows):
    """rows 是 (id, 正名, 别名列表)；同句多命中取最长名，返回 (id, 正名)。"""
    pool = [(alias, rid, canonical)
            for rid, canonical, aliases in rows
            for alias in {canonical, *(aliases or [])}
            if alias and alias in q]
    if not pool:
        return None
    _, rid, canonical = max(pool, key=lambda item: len(item[0]))
    return rid, canonical


def mentions(session, query: str) -> dict[str, tuple[int, str]]:
    """句中出现的实体（含别名，最长匹配）→ {kind: (id, 正名)}。

    不做分词：只判断库内正名/别名是否为 query 的子串。组合问句（「桂枝汤配合风池穴」）
    和带说明的实体问句（「桂枝汤怎么用」）都靠它；精确检索仍是整名相等，两者互补。
    `加减写法` 别名指向母方，会把「桂枝汤」错接到 27 个加减方，故排除。
    """
    q = qmod.normalize_query(query)
    formula_aliases: dict[int, list[str]] = {}
    for fid, name in session.execute(
            select(FormulaAlias.formula_id, FormulaAlias.name)
            .where(FormulaAlias.kind != "加减写法")):
        formula_aliases.setdefault(fid, []).append(name)

    rowsets = (
        ("formula", [(fid, name, formula_aliases.get(fid, []))
                     for fid, name in session.execute(
                         select(Formula.id, Formula.canonical_name))]),
        ("herb", list(session.execute(select(Herb.id, Herb.name, Herb.alias)))),
        ("acupoint", [(aid, name, ()) for aid, name in session.execute(
            select(Acupoint.id, Acupoint.name))]),
    )
    found: dict[str, tuple[int, str]] = {}
    for kind, rows in rowsets:
        hit = _best_mention(q, rows)
        if hit is not None:
            found[kind] = hit
    return found


def classify(session, query: str) -> Intent:
    q = qmod.normalize_query(query)
    if _CASE_NO.search(q):
        return Intent.case
    found = mentions(session, q)
    if len(found) >= 2 and _COMPOSITE_CUE.search(q):
        return Intent.composite
    if "formula" in found:
        return Intent.formula
    if "herb" in found:
        return Intent.herb
    point = found.get("acupoint")
    # 穴位名常是普通词的前缀（太阳穴 vs 太阳病）：裸名必须整句相等，否则要显式取穴线索
    if (point is not None and q == point[1]) or _ACUPOINT_CUE.search(q):
        return Intent.acupoint
    return Intent.syndrome
```

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_intent.py -q`
Expected: PASS（11 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/rag/__init__.py backend/app/rag/intent.py backend/tests/db/test_rag_intent.py
git commit -m "feat(m3): 意图分类六类规则（FR-1）"
```

---

### Task 2: 门禁、拒答与免责声明（FR-3 / D2）

**Files:**
- Create: `backend/app/rag/gate.py`
- Test: `backend/tests/unit/test_rag_gate.py`

**Interfaces:**
- Consumes: `app.rag.intent.Intent`、`app.search.query.Hit`。
- Produces: `DISCLAIMER`、`REFUSAL_HEADLINE`、`GateDecision(refused, reason, candidates)`、`decide(intent, hits, *, threshold=None, entity_found=False) -> GateDecision`。
- `entity_found=True` 表示 `intent.mentions` 已解析出与 intent 同类型的实体（服务层只对 formula/herb 传）；此时不再要求整句等于正名。穴位裸名不传：`太阳` 是穴名但 `太阳病` 是六经问句。

- [x] **Step 1: 写失败测试**

```python
from app.rag.gate import DISCLAIMER, decide
from app.rag.intent import Intent
from app.search.query import MATCH_EXACT, MATCH_VECTOR, Hit


def _hit(ref_type, match, score, ref_id=1):
    return Hit(ref_type, ref_id, f"{ref_type}{ref_id}", "", score, match, "")


def test_entity_intent_requires_exact_match():
    assert decide(Intent.formula, [_hit("formula", MATCH_VECTOR, 0.99)]).reason == "no_exact_entity"
    assert not decide(Intent.formula, [_hit("formula", MATCH_EXACT, 1.0)]).refused


def test_resolved_mention_satisfies_entity_intent():
    # 「桂枝汤怎么用」：整句不相等，但 mentions 已解析出实体，不应拒答
    assert not decide(Intent.formula, [], entity_found=True).refused


def test_symptom_intent_uses_threshold():
    assert decide(Intent.syndrome, [], threshold=0.3).refused
    assert decide(Intent.syndrome, [_hit("case", MATCH_VECTOR, 0.29)], threshold=0.3).refused
    assert not decide(Intent.syndrome, [_hit("case", MATCH_VECTOR, 0.31)], threshold=0.3).refused


def test_refusal_keeps_at_most_three_candidates():
    d = decide(Intent.syndrome, [_hit("case", MATCH_VECTOR, 0.1, i) for i in range(5)])
    assert d.refused and len(d.candidates) == 3


def test_disclaimer_is_the_prd_text():
    assert DISCLAIMER == "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。"
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_rag_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: app.rag.gate`

- [x] **Step 3: 最小实现**

```python
"""FR-3 门禁：实体类问题必须精确命中；其余按可配置阈值拒答。阈值来源是 D2 回归调参，不在此拍板。"""

from dataclasses import dataclass, field

from app.config import settings
from app.rag.intent import Intent
from app.search.query import MATCH_EXACT, Hit

DISCLAIMER = "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。"
REFUSAL_HEADLINE = "本地库未收录该问题对应的方/药/穴证据。"

_EXACT_REQUIRED = {Intent.formula: "formula", Intent.herb: "herb"}
_MAX_CANDIDATES = 3


@dataclass
class GateDecision:
    refused: bool
    reason: str = ""
    candidates: list[Hit] = field(default_factory=list)


def decide(intent: Intent, hits: list[Hit], *, threshold: float | None = None,
           entity_found: bool = False) -> GateDecision:
    threshold = settings.refusal_threshold if threshold is None else threshold
    if entity_found:
        return GateDecision(False)
    wanted = _EXACT_REQUIRED.get(intent)
    if wanted:
        ok = any(h.ref_type == wanted and h.match == MATCH_EXACT for h in hits)
        return GateDecision(not ok, "" if ok else "no_exact_entity",
                            [] if ok else hits[:_MAX_CANDIDATES])
    ok = bool(hits) and max(h.score for h in hits) >= threshold
    return GateDecision(not ok, "" if ok else "below_threshold",
                        [] if ok else hits[:_MAX_CANDIDATES])
```

`backend/app/config.py` 增加：

```python
    refusal_threshold: float = 0.30   # D2：先用占位值，M5 由问答日志回归
```

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_rag_gate.py -q`
Expected: PASS（5 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/rag/gate.py backend/app/config.py backend/tests/unit/test_rag_gate.py
git commit -m "feat(m3): 证据门禁与拒答判定（FR-3/D2）"
```

---

### Task 3: 回答 Schema + 方剂/中药构建（FR-4）

**Files:**
- Create: `backend/app/rag/schemas.py`
- Create: `backend/app/rag/builders.py`
- Test: `backend/tests/db/test_rag_builders.py`

**Interfaces:**
- Produces:
  - `Citation(ref_type, ref_id, title, anchor, snippet)`
  - `Section(title, lines)`
  - `Answer(intent, status, headline, sections, citations, dose_complete, candidates, followup, disclaimer, prose, top_score)`
  - `DoseLine(herb, herb_name, g, ancient, dose_state)`
  - `citation_from_hit(h) -> Citation`
  - `build_formula(session, formula_id) -> Answer`
  - `build_herb(session, herb_id) -> Answer`
  - `compose_dose_lines(session, formula_id) -> tuple[list[DoseLine], bool | None]`
  - `_top_score(*hit_groups) -> float | None`（内部工具，后续任务的 Answer 用它填 `top_score`）
- 后续任务复用 `compose_dose_lines` 给辨证/医案/综合链。

- [x] **Step 1: 写失败测试**

```python
from sqlalchemy import select

from app.admin.reindex import run_reindex
from app.db.models import Formula, Herb
from app.rag import builders
from app.rag.gate import DISCLAIMER


def test_formula_answer_uses_grams_with_ancient_trace(db_session):
    run_reindex(db_session)
    # 甘草汤的古制变体只有一味且 state=exact；桂枝汤含「大枣 十二枚」故 dose_complete=False
    fid = db_session.scalar(select(Formula.id).where(Formula.canonical_name == "甘草汤"))
    ans = builders.build_formula(db_session, fid)

    assert ans.status == "answered" and ans.intent == "B"
    assert ans.headline == "甘草汤"
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "g（" in body and "两" in body          # 只出克 + 古制括号留痕
    assert ans.dose_complete is True
    assert ans.citations and all(c.anchor for c in ans.citations)
    assert ans.disclaimer == DISCLAIMER


def test_formula_with_non_exact_dose_is_marked_incomplete(db_session):
    run_reindex(db_session)
    fid = db_session.scalar(select(Formula.id).where(Formula.canonical_name == "五苓散"))
    ans = builders.build_formula(db_session, fid)
    assert ans.dose_complete is False
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "十八铢" in body or "铢" in body        # 未知单位原样保留，不得造克数


def test_herb_answer_declares_missing_flavor(db_session):
    run_reindex(db_session)
    hid = db_session.scalar(select(Herb.id).where(Herb.name == "丹砂"))
    ans = builders.build_herb(db_session, hid)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "本经未载性味" in body
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_builders.py -q`
Expected: FAIL — `ModuleNotFoundError: app.rag.schemas`

- [x] **Step 3: 最小实现**

`backend/app/rag/schemas.py`:

```python
from pydantic import BaseModel, Field


class Citation(BaseModel):
    ref_type: str
    ref_id: int
    title: str
    anchor: str
    snippet: str = ""


class Section(BaseModel):
    title: str
    lines: list[str]


class DoseLine(BaseModel):
    herb: str
    herb_name: str | None = None
    g: float | None = None
    ancient: str | None = None
    dose_state: str


class Answer(BaseModel):
    intent: str
    status: str = "answered"          # answered | refused | needs_more_info
    headline: str
    sections: list[Section] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    dose_complete: bool | None = None
    candidates: list[Citation] = Field(default_factory=list)
    followup: list[str] = Field(default_factory=list)
    general_note: str | None = None    # D1：非本库内容只允许进此字段，M3 恒为 None
    disclaimer: str = ""
    prose: str = ""
    top_score: float | None = None


def citation_from_hit(h) -> Citation:
    return Citation(ref_type=h.ref_type, ref_id=h.ref_id, title=h.title,
                    anchor=h.anchor, snippet=h.snippet)
```

`backend/app/rag/builders.py` 第一批：

```python
"""FR-4 结构化回答：字段全部由 DB 事实拼装；LLM 只写 prose。"""

from sqlalchemy import select

from app.db.models import (
    Case, Formula, FormulaDoseVariant, FormulaEvidence, FormulaItem, Herb,
)
from app.rag.gate import DISCLAIMER
from app.rag.schemas import Answer, Citation, DoseLine, Section, citation_from_hit
from app.search import anchors as anchor_mod


def compose_dose_lines(session, formula_id: int) -> tuple[list[DoseLine], bool | None]:
    variants = list(session.scalars(
        select(FormulaDoseVariant).where(FormulaDoseVariant.formula_id == formula_id)
        .order_by(FormulaDoseVariant.id)))
    if not variants:
        return [], None
    chosen = min(variants, key=lambda v: (v.dose_basis != "ancient", v.id))
    herb_names = dict(session.execute(select(Herb.id, Herb.name)).all())
    lines = []
    for item in session.scalars(
            select(FormulaItem).where(FormulaItem.variant_id == chosen.id)
            .order_by(FormulaItem.ordinal)):
        lines.append(DoseLine(
            herb=item.herb_text,
            herb_name=herb_names.get(item.herb_id) if item.herb_id else None,
            g=item.dose_g, ancient=item.dose_text, dose_state=item.dose_state))
    return lines, all(line.dose_state == "exact" for line in lines)


def format_dose(line: DoseLine) -> str:
    if line.g is not None:
        return f"{line.herb} {line.g:g}g（{line.ancient}）"
    return f"{line.herb} {line.ancient or '剂量未记载'}（{line.dose_state}）"


def _top_score(*groups) -> float | None:
    """日志/前端排序用的检索最高分；没有 hit 就留空，不编造。"""
    scores = [h.score for group in groups for h in group]
    return max(scores) if scores else None


def _formula_citations(session, formula: Formula) -> list[Citation]:
    anchor = anchor_mod.formula_anchors(session, {formula.id}).get(formula.id, "")
    evidence = list(session.scalars(
        select(FormulaEvidence).where(FormulaEvidence.formula_id == formula.id)
        .order_by(FormulaEvidence.id).limit(3)))
    cites = [Citation(ref_type="formula", ref_id=formula.id, title=formula.canonical_name,
                      anchor=anchor)]
    for e in evidence:
        cites.append(Citation(
            ref_type="evidence", ref_id=e.id,
            title=f"{formula.canonical_name}（{e.six_jing or e.bing_duan or '出处未标'}）",
            anchor=anchor_mod.evidence_anchor(e.source_doc, e.six_jing, e.bing_duan,
                                              e.clause_no, e.formula_no),
            snippet=(e.original_text or "")[:80]))
    return cites


def build_formula(session, formula_id: int) -> Answer:
    formula = session.get(Formula, formula_id)
    doses, complete = compose_dose_lines(session, formula_id)
    sections = [Section(title="组成", lines=[format_dose(d) for d in doses] or ["本方无组成记录"])]
    if complete is False:
        sections.append(Section(title="提示", lines=["本方剂量不完全可执行（含非 exact 药味）"]))
    return Answer(intent="B", headline=formula.canonical_name, sections=sections,
                  citations=_formula_citations(session, formula), dose_complete=complete,
                  disclaimer=DISCLAIMER)


def build_herb(session, herb_id: int) -> Answer:
    herb = session.get(Herb, herb_id)
    taste = herb.flavor if herb.flavor else "本经未载性味"
    sections = [Section(title="性味", lines=[taste])]
    if herb.alias:
        sections.append(Section(title="别名", lines=["、".join(herb.alias)]))
    if herb.taste_group:
        sections.append(Section(title="五味归经", lines=[herb.taste_group]))
    if herb.effects:
        sections.append(Section(title="功效主治", lines=[herb.effects]))
    if herb.indications:
        sections.append(Section(title="主治", lines=[herb.indications]))
    if herb.dosage_note:
        sections.append(Section(title="用量", lines=[herb.dosage_note]))
    if herb.taboo:
        sections.append(Section(title="禁忌", lines=[herb.taboo]))
    return Answer(intent="C", headline=herb.name, sections=sections,
                  citations=[Citation(ref_type="herb", ref_id=herb.id, title=herb.name,
                                      anchor=anchor_mod.herb_anchor(herb.name))],
                  disclaimer=DISCLAIMER)
```

注意：`Herb` 的 `taste_group/indications/dosage_note/taboo` 已核对存在于 `backend/app/db/models.py`，按上述字段输出；`flavor` 是空串时统一显示「本经未载性味」，不补推测值。

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_builders.py -q`
Expected: PASS（3 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/rag/schemas.py backend/app/rag/builders.py backend/tests/db/test_rag_builders.py
git commit -m "feat(m3): 结构化回答与方/药构建（FR-4）"
```

---

### Task 4: 取穴链与医案链（FR-1 D/E，FR-9 咳喘特例）

**Files:**
- Modify: `backend/app/rag/builders.py`
- Test: `backend/tests/db/test_rag_builders.py`（追加）

**Interfaces:**
- Produces: `build_acupoints(session, query, hits) -> Answer`、`build_case(session, case_id) -> Answer`。
- `build_acupoints` 的 `hits` 是 `list[app.search.query.Hit]`；空列表时仍可走症状表/咳喘特例。

- [x] **Step 1: 写失败测试（追加）**

```python
from app.db.models import Case
from app.search import retriever


def test_acupoints_from_symptom_table(db_session):
    run_reindex(db_session)
    hits = retriever.search(db_session, "头痛", kinds={"acupoint"}, top=10).hits
    ans = builders.build_acupoints(db_session, "头痛", hits)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert "风池" in body and "后溪" in body


def test_cough_has_no_symptom_section_so_special_branch_is_mandatory(db_session):
    run_reindex(db_session)
    hits = retriever.search(db_session, "咳嗽气喘按什么穴", kinds={"acupoint"}, top=10).hits
    ans = builders.build_acupoints(db_session, "咳嗽气喘按什么穴", hits)
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert {"列缺", "照海", "肺俞", "中府"} <= {n for n in ["列缺", "照海", "肺俞", "中府"] if n in body}
    assert ans.sections[0].title == "取穴"


def test_case_answer_follows_question_answer_treatment_format(db_session):
    run_reindex(db_session)
    cid = db_session.scalar(select(Case.id).where(Case.no == "问11"))
    ans = builders.build_case(db_session, cid)
    assert [s.title for s in ans.sections] == ["问", "答", "治", "要诀"]
    assert ans.headline.startswith("问11")
    assert "射干麻黄汤" in " ".join(line for s in ans.sections for line in s.lines)
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_builders.py -q`
Expected: FAIL — `AttributeError: module 'app.rag.builders' has no attribute 'build_acupoints'`

- [x] **Step 3: 最小实现（追加到 builders.py）**

```python
import re

from app.db.models import Acupoint, AcupointSymptom
from app.search.query import Hit

_COUGH = re.compile(r"咳|喘")
_COUGH_POINTS = ("列缺", "照海", "肺俞", "中府")
_ACUPOINT_NOISE = re.compile(r"按什么穴|取穴|配穴|穴位|针灸|扎针|针哪|什么穴|怎么|如何|[？?，,。\s]")


def clean_symptom_query(query: str) -> str:
    """检索用：去掉「按什么穴」这类问句噪声，只留症状词。"""
    return " ".join(t for t in _ACUPOINT_NOISE.sub(" ", query).split() if t)


def _symptom_terms(query: str) -> list[str]:
    return [t for t in clean_symptom_query(query).split() if len(t) >= 2]


def _acupoint_rows(session, names: list[str]) -> dict[str, Acupoint]:
    if not names:
        return {}
    return {a.name: a for a in session.scalars(
        select(Acupoint).where(Acupoint.name.in_(names)).order_by(Acupoint.id))}


def _acupoint_lines(rows: dict[str, Acupoint], names: list[str]) -> list[str]:
    lines = []
    for name in names:
        a = rows.get(name)
        if a is None:
            continue
        roles = f"；角色 {a.role}" if a.role else ""
        location = f"；定位 {a.location[:40]}" if a.location else ""
        actions = (a.actions or "")[:60]
        lines.append(f"{a.name}（{a.meridian or '经外奇穴'}）{roles}{location}；主治：{actions}")
    return lines


def build_acupoints(session, query: str, hits: list[Hit]) -> Answer:
    terms = _symptom_terms(query)
    names: list[str] = []
    if terms:
        rows = session.execute(
            select(AcupointSymptom.acupoint_id, Acupoint.name)
            .join(Acupoint, Acupoint.id == AcupointSymptom.acupoint_id)
            .where(*[AcupointSymptom.symptom.contains(t) for t in terms])
            .order_by(Acupoint.id)).all()
        names = [name for _, name in rows]
    table_matched = bool(names)
    used_special = False
    if not names and _COUGH.search(query):
        names = list(_COUGH_POINTS)
        used_special = True
    if not names:
        names = [h.title for h in hits if h.ref_type == "acupoint"][:5]

    logic = ("治症取穴无咳/喘专节，按 §4.4 特例走十二经穴位库（列缺/照海）+ 俞募（肺俞/中府）。"
             if used_special else
             "按症状命中治症取穴表。" if table_matched else
             "未匹配到症状条目，按检索命中穴位兜底。")
    points = _acupoint_rows(session, names)
    citations = [
        Citation(ref_type="acupoint", ref_id=a.id, title=a.name,
                 anchor=anchor_mod.acupoint_anchor(a.name, a.meridian))
        for a in points.values()
    ]
    return Answer(intent="D", headline=f"{query} 取穴", sections=[
        Section(title="取穴", lines=_acupoint_lines(points, names) or ["本地库未收录对应穴位"]),
        Section(title="依据", lines=[logic]),
    ], citations=citations, disclaimer=DISCLAIMER, top_score=_top_score(hits))


def build_case(session, case_id: int) -> Answer:
    case = session.get(Case, case_id)
    sections = [
        Section(title="问", lines=[case.chief_complaint or "主诉未载"]),
        Section(title="答", lines=[case.pathogenesis or "病机未载"]),
        Section(title="治", lines=[case.treatment or "本条未出方"]),
        Section(title="要诀", lines=[case.tips or "本条无要诀"]),
    ]
    doses: list[str] = []
    for fid in case.treatment_formula_ids or []:
        lines, _ = compose_dose_lines(session, fid)
        doses.extend(format_dose(d) for d in lines)
    if doses:
        sections.append(Section(title="剂量", lines=doses))
    return Answer(intent="E", headline=f"{case.no}（{case.category or '未分类'}）",
                  sections=sections,
                  citations=[Citation(ref_type="case", ref_id=case.id, title=case.no,
                                      anchor=anchor_mod.case_anchor(case.no))],
                  disclaimer=DISCLAIMER)
```

注意：如果 `Case.treatment_formula_ids` 为空但 `treatment` 文本含「射干麻黄汤」，`build_case` 仍会通过 `treatment` 行满足测试；不要为此加正则解析。

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_builders.py -q`
Expected: PASS（6 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/rag/builders.py backend/tests/db/test_rag_builders.py
git commit -m "feat(m3): 取穴链咳喘特例与医案四段式（FR-9/E）"
```

---

### Task 5: 辨证/综合链 + LLM 适配器（FR-4 / D1）

**Files:**
- Create: `backend/app/rag/llm.py`
- Modify: `backend/app/rag/builders.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/db/test_rag_syndrome.py`
- Test: `backend/tests/unit/test_rag_llm.py`

**Interfaces:**
- Produces:
  - `build_syndrome(session, query, hits, case_hits) -> Answer`
  - `build_composite(session, query, hits, case_hits, found=None) -> Answer`（`found` 来自 `intent.mentions`；为 `None` 时自解析）
  - `build_followup(query) -> list[str]`（FR-5：主诉笼统时返回追问，不猜病名）
  - `LlmClient` Protocol `compose(answer: Answer) -> str`
  - `FakeLlm.compose(answer) -> str`
  - `OpenAiCompatibleLlm(base_url, model, api_key)`
  - `get_llm() -> LlmClient`（未配置 key 时返回 FakeLlm）

- [x] **Step 1: 写失败测试**

`backend/tests/db/test_rag_syndrome.py`:

```python
from app.admin.reindex import run_reindex
from app.rag import builders
from app.search import retriever


def _hits(session, q, kinds):
    return retriever.search(session, q, kinds=kinds, top=10).hits


def test_syndrome_pipeline_sample_lands_case_11_and_formula(db_session):
    run_reindex(db_session)
    q = "咳嗽气喘痰白不能平躺"
    ans = builders.build_syndrome(db_session, q, _hits(db_session, q, {"framework", "evidence", "formula"}),
                                  _hits(db_session, q, {"case"}))
    body = " ".join(line for s in ans.sections for line in s.lines)
    assert ans.intent == "A"
    assert "射干麻黄汤" in body
    assert any(c.ref_type == "case" for c in ans.citations)


def test_composite_has_syndrome_formula_and_acupoint_sections(db_session):
    run_reindex(db_session)
    q = "桂枝汤配合风池穴怎么用"
    ans = builders.build_composite(db_session, q, _hits(db_session, q, {"formula", "framework", "evidence"}),
                                   _hits(db_session, q, {"case"}))
    titles = [s.title for s in ans.sections]
    assert "辨证" in titles and "组成" in titles and "取穴" in titles


def test_vague_complaint_asks_instead_of_guessing():
    assert builders.build_followup("我不舒服")
    assert builders.build_followup("有点难受，怎么办")
    assert builders.build_followup("咳嗽气喘痰白不能平躺") == []
    assert builders.build_followup("头痛") == []      # 具体症状词不拦，交给检索/门禁
    assert builders.build_followup("咳嗽怎么办") == []  # 「怎么办」只在整句无主诉时算空问
```

`backend/tests/unit/test_rag_llm.py`:

```python
import pytest

from app.rag.gate import DISCLAIMER
from app.rag.llm import FakeLlm, OpenAiCompatibleLlm, get_llm
from app.rag.schemas import Answer, Section


def _answer():
    return Answer(intent="B", headline="桂枝汤",
                  sections=[Section(title="组成", lines=["桂枝 45g（三两）"])],
                  disclaimer=DISCLAIMER)


def test_fake_llm_is_deterministic_and_offline():
    llm = FakeLlm()
    assert llm.compose(_answer()) == llm.compose(_answer())
    assert "桂枝" in llm.compose(_answer())


def test_real_adapter_refuses_without_key(monkeypatch):
    from app.config import settings

    with pytest.raises(RuntimeError):
        OpenAiCompatibleLlm(base_url="https://example.invalid", model="x", api_key="")
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert isinstance(get_llm(), FakeLlm)
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_rag_llm.py tests/db/test_rag_syndrome.py -q`
Expected: FAIL — `ModuleNotFoundError: app.rag.llm`

- [x] **Step 3: 最小实现**

`backend/app/rag/llm.py`:

```python
"""LLM 只写 prose。结构化字段、剂量、引用、拒答、免责已由 Python 定稿。"""

from typing import Protocol

import httpx

from app.config import settings
from app.rag.schemas import Answer


class LlmClient(Protocol):
    def compose(self, answer: Answer) -> str: ...


class FakeLlm:
    """确定性替身：不联网、不下载模型，输出严格来自结构化字段。"""

    def compose(self, answer: Answer) -> str:
        return "；".join(f"{s.title}：{' '.join(s.lines)}" for s in answer.sections)


class OpenAiCompatibleLlm:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 30.0):
        if not api_key:
            raise RuntimeError("未配置 LLM API Key：保持 FakeLlm，不要在测试/默认路径联网")
        self.base_url, self.model, self.api_key = base_url, model, api_key
        self.timeout = timeout

    def compose(self, answer: Answer) -> str:
        prompt = ("你是中医经方库的整理助手。只能复述下列结构化结论，不得新增任何方名、药名、"
                  "穴位、剂量或疗效；保持克数与古制留痕。\n" + answer.model_dump_json())
        resp = httpx.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "temperature": 0,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def get_llm() -> LlmClient:
    if settings.llm_api_key:
        return OpenAiCompatibleLlm(settings.llm_base_url, settings.llm_model,
                                   settings.llm_api_key)
    return FakeLlm()
```

`backend/app/config.py` 追加：

```python
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
```

`backend/app/rag/builders.py` 追加（顶部补 `import re`、`from app.rag import intent as intent_mod`、`from app.search import query as qmod`）：

```python
_VAGUE = re.compile(r"不舒服|难受|不适|不好|看看|怎么回事|什么问题")
_EMPTY_ASK = re.compile(r"^(怎么办|我该怎么办|咋办|帮帮我)$")
_FILLER = re.compile(r"[\s，,。？?！!、]")


def build_followup(query: str) -> list[str]:
    """FR-5：只有泛泛主诉（「不舒服/难受」）或空问句才追问；具体症状词不拦。"""
    core = _FILLER.sub("", qmod.normalize_query(query))
    if core and not _VAGUE.search(core) and not _EMPTY_ASK.search(core):
        return []
    return ["主要不适在哪个部位？（头项/胸胁/脘腹/四肢/全身）",
            "有无恶寒发热、汗出、口渴？大便、小便与平时相比如何？",
            "睡眠、胃口、精神怎样？起病多久了？"]


def _treatment_section(session, formula_ids: list[int]) -> Section | None:
    names, doses = [], []
    for fid in formula_ids:
        formula = session.get(Formula, fid)
        if formula is None:
            continue
        names.append(formula.canonical_name)
        lines, _ = compose_dose_lines(session, fid)
        doses.extend(format_dose(d) for d in lines)
    if not names:
        return None
    return Section(title="定方", lines=[f"治：{'、'.join(names)}"] + doses)


def build_syndrome(session, query: str, hits, case_hits) -> Answer:
    case_hit = next((h for h in case_hits if h.ref_type == "case" and h.score >= 0.30), None)
    sections = [Section(title="辨证", lines=[f"{h.title}：{h.snippet}" for h in hits[:3]]
                        or ["本地库未检索到对应条文"])]
    citations = [citation_from_hit(h) for h in hits[:3]]
    treatment = None
    if case_hit is not None:
        case = session.get(Case, case_hit.ref_id)
        treatment = _treatment_section(session, list(case.treatment_formula_ids or []))
        citations.insert(0, Citation(ref_type="case", ref_id=case.id, title=case.no,
                                     anchor=anchor_mod.case_anchor(case.no)))
        if case.tips:
            sections.append(Section(title="调护", lines=[case.tips]))
    else:
        # 没有够分的医案时，只认整名精确的方剂 hit；向量近邻不能当作定方依据
        formula_hit = next((h for h in hits if h.ref_type == "formula"
                            and h.match == "exact"), None)
        if formula_hit is not None:
            treatment = _treatment_section(session, [formula_hit.ref_id])
    if treatment is None:
        # 语料事实：部分医案只写方名不给结构化 formula_id 时不造方
        treatment = Section(title="定方", lines=["本条未落到结构化方剂"])
    sections.insert(1, treatment)
    return Answer(intent="A", headline=query, sections=sections, citations=citations,
                  disclaimer=DISCLAIMER, top_score=_top_score(hits, case_hits))


def build_composite(session, query: str, hits, case_hits, found=None) -> Answer:
    """组合问句：实体用 mentions 解析（整句检索命中不了「桂枝汤配合风池穴」里的正名）。"""
    found = intent_mod.mentions(session, query) if found is None else found
    syndrome = build_syndrome(session, query, hits, case_hits)
    sections = [Section(title="辨证", lines=syndrome.sections[0].lines)]
    citations = list(syndrome.citations)

    if "formula" in found:
        built = build_formula(session, found["formula"][0])
        sections.append(Section(title="组成", lines=built.sections[0].lines))
        citations.extend(built.citations)

    if "acupoint" in found:
        point = session.get(Acupoint, found["acupoint"][0])
        sections.append(Section(title="取穴",
                                lines=_acupoint_lines({point.name: point}, [point.name])))
        citations.append(Citation(
            ref_type="acupoint", ref_id=point.id, title=point.name,
            anchor=anchor_mod.acupoint_anchor(point.name, point.meridian)))
    else:
        acupoints = build_acupoints(session, query, hits)
        sections.append(Section(title="取穴", lines=acupoints.sections[0].lines))
        citations.extend(acupoints.citations)

    return Answer(intent="F", headline=query, sections=sections, citations=citations,
                  disclaimer=DISCLAIMER, top_score=_top_score(hits, case_hits))
```

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_rag_llm.py tests/db/test_rag_syndrome.py -q`
Expected: PASS（5 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/rag/llm.py backend/app/rag/builders.py backend/app/config.py backend/tests/unit/test_rag_llm.py backend/tests/db/test_rag_syndrome.py
git commit -m "feat(m3): 辨证/综合链与 LLM 适配器（FR-4/D1）"
```

---

### Task 6: 会话、问答日志与 `POST /api/chat`（FR-6/FR-15）

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/rag/service.py`
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/db/test_chat_api.py`

**Interfaces:**
- Consumes: `classify`、`mentions`、`build_followup`、`gate.decide`、`build_*`、`get_llm`、`retriever.search`。
- Produces:
  - `answer_question(session, question, *, session_id=None, llm=None) -> ChatResponse`
  - `ChatRequest(question, session_id)`、`ChatResponse(session_id, message_id, answer)`
  - `GET /api/chat/{session_id}` → `{session_id, messages: [{role, content, created_at}]}`
  - 表：`chat_session`、`chat_message`、`qa_log`。

- [x] **Step 1: 写失败测试**

```python
from sqlalchemy import func, select

from app.api.chat import router  # noqa: F401  （导入即证明路由模块存在）
from app.db.models import QaLog
from app.main import create_app
from app.db.session import get_session


def test_chat_answers_formula_and_logs(indexed_client, db_session):
    resp = indexed_client.post("/api/chat", json={"question": "桂枝汤"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"]["intent"] == "B"
    assert data["answer"]["status"] == "answered"
    assert "桂枝" in data["answer"]["prose"]
    sid = data["session_id"]
    assert sid and data["message_id"]

    logs = list(db_session.scalars(select(QaLog)))
    assert len(logs) == 1 and logs[0].intent == "B" and logs[0].refused is False
    assert logs[0].query == "桂枝汤"
    assert logs[0].top_score == 1.0


def test_chat_refuses_without_fabricating(indexed_client, db_session):
    resp = indexed_client.post("/api/chat", json={"question": "乳腺癌靶向药有哪些"})
    data = resp.json()
    assert data["answer"]["status"] == "refused"
    assert data["answer"]["sections"] == []
    assert "靶向" not in data["answer"]["prose"]
    assert db_session.scalar(select(func.count()).select_from(QaLog)) == 1


def test_chat_asks_followup_for_vague_question(indexed_client):
    data = indexed_client.post("/api/chat", json={"question": "我不舒服"}).json()
    assert data["answer"]["status"] == "needs_more_info"
    assert data["answer"]["sections"] == []
    assert len(data["answer"]["followup"]) == 3


def test_session_history_keeps_both_turns(indexed_client):
    first = indexed_client.post("/api/chat", json={"question": "桂枝汤"}).json()
    sid = first["session_id"]
    indexed_client.post("/api/chat", json={"question": "风池", "session_id": sid})
    hist = indexed_client.get(f"/api/chat/{sid}").json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant", "user", "assistant"]
    assert hist["messages"][0]["content"]["text"] == "桂枝汤"
```

在 `tests/db/test_chat_api.py` 顶部加 fixture（复用现有模式）：

```python
import pytest
from fastapi.testclient import TestClient

from app.admin.reindex import run_reindex
from app.db.session import get_session
from app.main import create_app


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """约束：测试永不联网；即使本地 .env 配了 key 也强制 FakeLlm。"""
    from app.rag.llm import FakeLlm

    monkeypatch.setattr("app.rag.llm.get_llm", lambda: FakeLlm())


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def indexed_client(client, db_session):
    run_reindex(db_session)
    return client
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_chat_api.py -q`
Expected: FAIL — `ModuleNotFoundError: app.api.chat`

- [x] **Step 3: 最小实现**

`backend/app/db/models.py` 追加（文件末尾）：

```python
class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.id"), index=True)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())


class QaLog(Base):
    __tablename__ = "qa_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_session.id"), nullable=True)
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(Text)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
```

`Boolean` 需加入 `sqlalchemy` 导入列表。

`backend/app/rag/service.py`:

```python
"""编排入口：意图 → 检索 → 门禁 → 构建 → prose → 落库。"""

import re

from sqlalchemy import select

from app.admin.reindex import indexer_default_embedder
from app.db.models import ChatMessage, ChatSession, Case, QaLog
from app.rag import builders, gate, intent as intent_mod, llm as llm_mod
from app.rag.schemas import Answer, ChatRequest, ChatResponse
from app.search import retriever

_KINDS = {
    intent_mod.Intent.syndrome: {"framework", "case", "evidence", "formula"},
    intent_mod.Intent.formula: {"formula", "evidence"},
    intent_mod.Intent.herb: {"herb"},
    intent_mod.Intent.acupoint: {"acupoint", "framework"},
    intent_mod.Intent.composite: {"formula", "herb", "acupoint", "framework", "case", "evidence"},
}
_ENTITY_KIND = {intent_mod.Intent.formula: "formula", intent_mod.Intent.herb: "herb"}
_CASE_NO_DIGITS = re.compile(r"问\s*(\d+)")


def _refusal(hits) -> Answer:
    return Answer(intent="", status="refused", headline=gate.REFUSAL_HEADLINE,
                  candidates=[builders.citation_from_hit(h) for h in hits[:3]],
                  disclaimer=gate.DISCLAIMER,
                  top_score=max((h.score for h in hits), default=None))


def _case_by_number(session, question: str):
    match = _CASE_NO_DIGITS.search(question)
    if not match:
        return None
    return session.scalar(select(Case).where(Case.no == f"问{match.group(1)}"))


def _answer_struct(session, question: str, kind: intent_mod.Intent, embedder) -> Answer:
    if kind == intent_mod.Intent.case:
        case = _case_by_number(session, question)
        return builders.build_case(session, case.id) if case else _refusal([])

    if kind == intent_mod.Intent.syndrome:
        followup = builders.build_followup(question)
        if followup:
            return Answer(intent=kind.value, status="needs_more_info",
                          headline="信息还不够，先按十问补充：",
                          followup=followup, disclaimer=gate.DISCLAIMER)

    found = intent_mod.mentions(session, question)
    kinds = _KINDS[kind]
    hits = retriever.search(session, question, kinds=kinds, top=10,
                            embedder=embedder).hits
    if kind == intent_mod.Intent.syndrome:
        case_hits = retriever.search(session, question, kinds={"case"}, top=3,
                                     embedder=embedder).hits
        decision = gate.decide(kind, hits + case_hits)
        if decision.refused:
            return _refusal(decision.candidates or case_hits)
        return builders.build_syndrome(session, question, hits, case_hits)

    decision = gate.decide(kind, hits, entity_found=_ENTITY_KIND.get(kind) in found)
    if decision.refused:
        return _refusal(decision.candidates)
    if kind == intent_mod.Intent.formula:
        answer = builders.build_formula(session, found["formula"][0])
        answer.top_score = max((h.score for h in hits), default=None)
        return answer
    if kind == intent_mod.Intent.herb:
        answer = builders.build_herb(session, found["herb"][0])
        answer.top_score = max((h.score for h in hits), default=None)
        return answer
    if kind == intent_mod.Intent.acupoint:
        return builders.build_acupoints(session, builders.clean_symptom_query(question), hits)
    case_hits = retriever.search(session, question, kinds={"case"}, top=3,
                                 embedder=embedder).hits
    return builders.build_composite(session, question, hits, case_hits, found=found)


def answer_question(session, question: str, *, session_id: int | None = None,
                    llm=None) -> ChatResponse:
    chat = session.get(ChatSession, session_id) if session_id else None
    if chat is None:
        chat = ChatSession()
        session.add(chat)
        session.flush()

    kind = intent_mod.classify(session, question)
    answer = _answer_struct(session, question, kind, indexer_default_embedder())
    answer.intent = answer.intent or kind.value
    answer.prose = (llm or llm_mod.get_llm()).compose(answer)

    session.add(ChatMessage(session_id=chat.id, role="user", content={"text": question}))
    msg = ChatMessage(session_id=chat.id, role="assistant", content=answer.model_dump())
    session.add(msg)
    session.add(QaLog(session_id=chat.id, query=question, intent=kind.value,
                      refused=answer.status == "refused",
                      top_score=answer.top_score, hit_count=len(answer.citations)))
    session.flush()
    return ChatResponse(session_id=chat.id, message_id=msg.id, answer=answer)
```

注意：`_refusal` 的 `sections` 必须为空（测试约束）。`top_score` 一律来自真实 hit（`Answer.top_score`），无命中则为 `None`，不要编造分数；`needs_more_info` 不做检索，因此日志里 `top_score` 为空、`refused=False`。

`backend/app/rag/schemas.py` 追加：

```python
class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: int | None = None


class ChatResponse(BaseModel):
    session_id: int
    message_id: int
    answer: Answer
```

`backend/app/api/chat.py`:

```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatMessage, ChatSession
from app.db.session import get_session
from app.rag.schemas import ChatRequest, ChatResponse
from app.rag.service import answer_question

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MessageOut(BaseModel):
    role: str
    content: dict
    created_at: datetime


class ChatHistory(BaseModel):
    session_id: int
    messages: list[MessageOut]


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, session: Session = Depends(get_session)):
    resp = answer_question(session, payload.question, session_id=payload.session_id)
    session.commit()
    return resp


@router.get("/{session_id}", response_model=ChatHistory)
def history(session_id: int, session: Session = Depends(get_session)):
    if session.get(ChatSession, session_id) is None:
        raise HTTPException(404, detail={"code": "session_not_found", "id": session_id})
    rows = list(session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)))
    return ChatHistory(session_id=session_id, messages=[
        MessageOut(role=m.role, content=m.content, created_at=m.created_at) for m in rows])
```

`backend/app/main.py` 的 `create_app()` 中 include：

```python
    from app.api import chat as chat_api
    ...
    app.include_router(chat_api.router)
```

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_chat_api.py -q`
Expected: PASS（4 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/db/models.py backend/app/rag/service.py backend/app/rag/schemas.py backend/app/api/chat.py backend/app/main.py backend/tests/db/test_chat_api.py
git commit -m "feat(m3): 会话/问答日志与 POST /api/chat（FR-6/15）"
```

---

### Task 7: SSE 流式输出（FR-3 / §6）

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/rag/service.py`
- Test: `backend/tests/db/test_chat_api.py`（追加）

**Interfaces:**
- Produces: `POST /api/chat/stream`，事件序列 `meta → citation* → token* → done`；`done` 的 `data` 是完整 `ChatResponse` JSON。
- `stream_events(session, question, *, session_id=None, llm=None, chunk_size=20) -> iterator[str]`（在 service 中，便于单测）。

- [x] **Step 1: 写失败测试**

```python
def test_sse_stream_emits_meta_citations_tokens_done(indexed_client):
    with indexed_client.stream("POST", "/api/chat/stream", json={"question": "桂枝汤"}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())

    events = [line[7:] for line in text.splitlines() if line.startswith("event: ")]
    assert events[0] == "meta"
    assert "citation" in events
    assert events[-1] == "done"
    assert "桂枝" in text
    assert text.count("event: token") >= 1
```

- [x] **Step 2: 运行并确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_chat_api.py::test_sse_stream_emits_meta_citations_tokens_done -q`
Expected: FAIL — 404（路由不存在）

- [x] **Step 3: 最小实现**

`backend/app/rag/service.py` 追加：

```python
import json


def stream_events(session, question: str, *, session_id: int | None = None,
                  llm=None, chunk_size: int = 20):
    resp = answer_question(session, question, session_id=session_id, llm=llm)
    answer = resp.answer
    yield f"event: meta\ndata: {json.dumps({'session_id': resp.session_id, 'intent': answer.intent, 'status': answer.status}, ensure_ascii=False)}\n\n"
    for citation in answer.citations:
        yield f"event: citation\ndata: {citation.model_dump_json()}\n\n"
    for start in range(0, len(answer.prose), chunk_size):
        yield f"event: token\ndata: {json.dumps({'text': answer.prose[start:start + chunk_size]}, ensure_ascii=False)}\n\n"
    yield f"event: done\ndata: {resp.model_dump_json()}\n\n"
```

`backend/app/api/chat.py` 追加：

```python
from fastapi.responses import StreamingResponse

from app.rag.service import stream_events


@router.post("/stream")
def chat_stream(payload: ChatRequest, session: Session = Depends(get_session)):
    def gen():
        yield from stream_events(session, payload.question, session_id=payload.session_id)
        session.commit()

    return StreamingResponse(gen(), media_type="text/event-stream")
```

- [x] **Step 4: 运行并确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_chat_api.py -q`
Expected: PASS（5 passed）

- [x] **Step 5: 提交**

```bash
git add backend/app/api/chat.py backend/app/rag/service.py backend/tests/db/test_chat_api.py
git commit -m "feat(m3): SSE 流式回答（meta/citation/token/done）"
```

---

### Task 8: 验收、边界与文档（PIPELINE §6 / PRD）

**Files:**
- Create: `backend/tests/db/test_rag_acceptance.py`
- Modify: `docs/需求文档-RAG系统.md`
- Modify: `docs/superpowers/plans/2026-10-30-m3-rag-orchestration.md`（勾选 + 实测记录）

**Interfaces:**
- 无新接口；只锁定前 7 个任务的联合行为。

- [x] **Step 1: 写失败验收测试**

```python
import pytest

from app.admin.reindex import run_reindex
from app.db.session import get_session
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    from app.rag.llm import FakeLlm

    monkeypatch.setattr("app.rag.llm.get_llm", lambda: FakeLlm())


@pytest.fixture
def client(db_session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def indexed(client, db_session):
    run_reindex(db_session)
    return client


def _answer(client, q):
    return client.post("/api/chat", json={"question": q}).json()["answer"]


def test_pipeline_case_1_lands_case_11_with_doses(indexed):
    ans = _answer(indexed, "咳嗽气喘痰白不能平躺")
    assert ans["status"] == "answered"
    body = " ".join(line for s in ans["sections"] for line in s["lines"])
    assert "射干麻黄汤" in body
    assert any(c["ref_type"] == "case" for c in ans["citations"])


def test_case_2_acupoints_are_covered(indexed):
    ans = _answer(indexed, "发烧怕冷头痛颈项强急脉浮按什么穴")
    body = " ".join(line for s in ans["sections"] for line in s["lines"])
    assert {"风池", "后溪", "天柱"} <= {n for n in ["风池", "后溪", "天柱"] if n in body}


def test_refusal_is_clean_and_disclaimed(indexed):
    ans = _answer(indexed, "乳腺癌靶向药有哪些")
    assert ans["status"] == "refused"
    assert ans["sections"] == [] and len(ans["candidates"]) <= 3
    assert ans["disclaimer"].startswith("本回答基于本地蒸馏语料")


def test_every_answer_has_server_side_disclaimer(indexed):
    for q in ("桂枝汤", "桂枝", "风池", "问11", "咳嗽气喘痰白不能平躺"):
        ans = _answer(indexed, q)
        assert ans["disclaimer"].endswith("执业中医师面诊决定。")


def test_dose_states_are_never_silently_filled(indexed):
    ans = _answer(indexed, "五苓散")
    body = " ".join(line for s in ans["sections"] for line in s["lines"])
    assert "g" not in body or "（" in body   # 有克必有古制留痕
    assert "十八铢" in body


def test_low_score_is_refused_not_answered(indexed):
    ans = _answer(indexed, "乳腺癌靶向药有哪些")
    assert ans["status"] == "refused"
```

- [x] **Step 2: 运行并确认失败/暴露缺口**

Run: `cd backend && .venv/bin/python -m pytest tests/db/test_rag_acceptance.py -q`
Expected: 允许部分失败；逐条修到全绿（失败原因只能是编排缺口，不允许改断言迁就实现）。

- [x] **Step 3: 修缺口（按失败项，最小改动）**

常见缺口与处置：
- 取穴特例没命中 → 检查 `_symptom_terms` 是否把「按什么穴」剥干净；咳喘分支必须优先于 hits 兜底。
- 组合问句缺「组成」→ 确认 classify 走了 composite，且 `mentions` 命中 formula/acupoint（整句精确检索命中不了句中正名，这是设计使然）。
- 医案没落到问11 → 调 `build_syndrome` 的 `case_hits` 阈值（0.30），或把 `case_hits` 的 top 从 3 提到 5；**不新增关键词表**。
- 五苓散没有「铢」→ 确认 `compose_dose_lines` 选的是 `dose_basis="ancient"` 变体。
- 拒答候选为空 → 允许为空（语料无近邻时），不要把随机 hit 硬塞进候选。

- [x] **Step 4: 全量回归**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 全部通过；若既有用例失败，先判定是行为变更还是回归，行为变更须同步改断言并在提交信息里说明。

- [x] **Step 5: 更新文档**

PRD §8 M3 行改为「已落地（日期）+ 验收命令 + 诚实边界」；在本文档末尾追加「实测记录」：通过/未通过用例、拒答样本、已知边界（无真实 LLM/AI 语义、阈值未校准、实体解析是子串最长匹配而非分词、E2 未做）。

- [x] **Step 6: 提交**

```bash
git add backend/tests/db/test_rag_acceptance.py docs/需求文档-RAG系统.md docs/superpowers/plans/2026-10-30-m3-rag-orchestration.md
git commit -m "test(m3): PIPELINE §6 验收与拒答/剂量边界"
```

---

## 明确不做（M3 边界）

- FR-4 的分型 JSON 不逐键复刻：M3 用统一 `Answer`（`sections` + `citations` + `dose_complete` + `followup`）承载同一批 DB 事实；前端精确字段契约在 UI 里程碑映射，事实来源不变。
- 不接真实 LLM provider 的联网测试：`OpenAiCompatibleLlm` 只在配置 key 后由部署方使用。
- 不做意图分类的 LLM few-shot：规则先行，日志（FR-15）积累后再评估。
- FR-5 只交付「A 类主诉笼统 → 结构化追问」的服务端部分；问诊卡 UI、十问三态表单、答案回填属前端里程碑。F 类必有精确实体，不做追问。
- 不做前端对话页/拒答卡：M3 只交付 API 与 SSE，UI 属后续里程碑。
- 不调 D2 阈值：`refusal_threshold=0.30` 是占位值，必须在 M5 用 `qa_log` 回归。
- 不引入繁简/错字归一：E3 已登记为独立边界。
- 取穴症状表仍是「整词/长句精确包含」匹配；散文式主诉靠向量召回兜底（E3 acupoint R@10 1.000），不在此自造分词器。
- `mentions` 每次请求全表读约 1.1k 条正名/别名（实测单次毫秒级）；M3 不建倒排/缓存，性能优化留待压测里程碑。

---

## 实测记录（2026-10-30，Task 8 收尾；数字为终审修复后复核）

### 命令与结果

工作目录 `backend`：

```
$ .venv/bin/python -m pytest tests/db/test_rag_acceptance.py -q
6 passed, 1 warning in 11.37s

$ .venv/bin/python -m pytest -q
313 passed, 1 deselected, 1 xfailed, 1 warning in 274.49s (0:04:34)
```

Task 8 收尾时的基线是 295 passed / 1 deselected / 1 xfailed；该任务只新增 6 条验收用例，既有断言零改动，6 条首轮即全绿、未改任何编排代码。终审修复轮（见「终审修复」）再新增 12 条用例（5 条为 `test_classify` 参数化行，另 7 条新用例），并把唯一一处 `unknown_unit` 断言的状态文案改为中文标签，全量因此为 313 passed：

| 用例 | 断言 | 实测 |
|---|---|---|
| `test_pipeline_case_1_lands_case_11_with_doses` | answered、含射干麻黄汤、有 case 引用 | 通过：走辨证链，sections 为 辨证/定方/提示；定方列出 射干麻黄汤、乌梅丸、厚朴三物汤 及古制剂量（射干 45g（三两）、麻黄 60g（四两）…），因含 approx/count_only 药味追加「提示」段 |
| `test_case_2_acupoints_are_covered` | 风池/后溪/天柱 全部出现 | 通过 |
| `test_refusal_is_clean_and_disclaimed` | refused、sections 空、候选 ≤3、免责开头 | 通过 |
| `test_every_answer_has_server_side_disclaimer` | 5 类问句免责结尾一致 | 通过 |
| `test_dose_states_are_never_silently_filled` | 有克必有古制括号、含「十八铢」 | 通过 |
| `test_low_score_is_refused_not_answered` | 低分只拒答 | 通过 |

### 拒答样本（`POST /api/chat` 实测输出，`FakeLlm`）

| query | status | intent | 候选数 | top_score |
|---|---|---|---|---|
| 乳腺癌靶向药有哪些 | refused | A | 3（06-医案/临床问答对.md｜重症/癌症类、问2（重症/癌症类）、02-伤寒论/临证诊断与治则补充.md｜药简力专，敢用毒药） | 0.1739 |
| 量子针灸能治癌症吗 | refused | D | 3 | 0.2807 |

两者 `sections=[]`、`prose` 为空串、`disclaimer` 以「本回答基于本地蒸馏语料」开头。对照：同轮「咳嗽气喘痰白不能平躺」为 answered，top_score 0.3967，sections 为 辨证/定方/提示（终审修复后补上「提示」段）。

### 与计划片段的偏差（以落地代码为准）

a. **Task 4**：医案回答实际为 5 段（问/答/治/要诀/剂量）——问11 的 `treatment_formula_ids` 是 射干麻黄汤/乌梅丸/厚朴三物汤 三首，`compose_dose_lines` 均有古制剂量，非空即补「剂量」段；测试写 `titles[:4] == ["问", "答", "治", "要诀"]` 且 `"剂量" in titles`，非计划里的四段等值断言。
b. **Task 5**：`build_followup` 落地为「剥离虚词/问句/软化词后仍有实质内容则不追问」，替代计划里的整句 `_VAGUE` 正则；后者会把「咳嗽老不好」「头痛不适」这类具体主诉误拦成 `needs_more_info`。
c. **Task 6**：`POST /api/chat` 把 `IndexNotReady / EmbeddingMismatch / ValueError` 映射为 409（`index_not_ready`）/ 503（`embedding_mismatch`）/ 422（`bad_request`），与 `/api/search` 对齐，并有 `test_chat_returns_coded_error_when_index_missing` 回归。

### 终审修复（2026-10-30）

整分支终审（BASE `3495a23` → HEAD `09293a0`）报出两项阻塞缺陷，本轮一次修完，提交 `fix(m3): 医案号句首锚定与近似剂量诚实标注`（基线 `09293a0`；提交哈希记录在本轮 `final-fix-report.md`——文档与代码同一提交，无法自指自身哈希）：

- **C1 医案号未锚定**：原 `_CASE_NO = re.compile(r"问\s*\d+")` 不锚定句首，任何「问+数字」子串都会路由到医案链——「请问11岁小孩发烧怎么办」曾直接输出问11 的剂量（「麻黄 60g（四两）」）。这正是 Task 1 留下、台账 defer 却始终没写进「已知边界」的问题。现改为 `^问\s*(\d+)(?=$|[\s，,。？?！!：:的号案是])`，判定集中到 `intent.case_no`，`service._case_by_number` 复用它（不再保留第二份正则）；语法合法但不存在的号（「问999」）按医案类拒答，返回至多 3 条真实医案候选。
- **I1 近似剂量与完整性丢失**：approx 行此前与 exact 同样式输出克数，且 `build_case`/`_treatment_section` 丢弃 `compose_dose_lines` 的 completeness。现 approx 渲染为「克数（古制，近似）」，无克数行用中文状态（未换算/仅计数/未记载）；`build_case`/`build_syndrome`/`build_composite` 聚合 `dose_complete`，为 `false` 时追加「本方剂量不完全可执行（含非 exact 药味）」提示。
- 测试：新增 12 条用例（5 条 `test_classify` 参数化行 + 7 条新用例）；唯一改动的既有断言是 `unknown_unit` 的状态文案由 `（unknown_unit）` 改为 `（未换算）`。

### 已知边界

- 无真实 LLM/AI 语义：默认 `FakeLlm`，`prose` 是结构化字段拼接；`OpenAiCompatibleLlm` 只在配置 key 后由部署方使用，测试不联网、不下载模型。
- `refusal_threshold=0.30` 是占位值，未用真实日志校准；M5 必须用 `qa_log` 回归（本轮未调阈值）。
- 实体解析（`intent.mentions`）是库内正名/别名对 query 的**子串最长匹配**，不是分词；不做繁简/错字归一（E3 已登记）。
- E2 管理端鉴权未做；本里程碑不改鉴权。
- 剂量渲染（`builders.format_dose`）：exact 行为「克数（古制）」（如 `泽泻 15g（一两）`）；approx 行有克数，必须在古制后标「近似」（如 `附子 15g（一枚(炮)，近似)`、问11 `半夏 25g（半升，近似）`），不得与精确值同样式；无 `dose_g` 的行（absent/count_only/unknown_unit）原样输出古制并括注中文状态（`未换算`/`仅计数`/`未记载`，如五苓散 `茯苓 十八铢（未换算）`、问11 `大枣 七枚（仅计数）`），不造克数。`build_case`/`build_syndrome`/`build_composite` 聚合所展示方剂的 `dose_complete`（忽略 `None`，无方时为 `None`），为 `false` 时追加「本方剂量不完全可执行（含非 exact 药味）」提示并随 `Answer.dose_complete` 下发；组合链只算「组成」段点名的方（辨证链的定方剂量不在组合段展示）。`formula_item.dose_state` 实测分布：exact 1795 / absent 219 / count_only 123 / approx 119 / unknown_unit 26。
- `formula_item.conversion_note` 全库 **0 条**非空（2282 行）——这不是语料缺失，而是 ETL 装载缺口：解析器 `app/etl/parse_formulas.py:76,85` 逐味调 `dose.convert` 并把结果写进 `conversion_note`（真实探针：1197 条非空解析结果，噪声过滤后 1194 条），而 `app/etl/loaders.py:174` 在写 `formula_item` 时把 `conversion_note` 与 `preparation` 一并硬编码为 `None`，注记因此全部未落库；`app/api/evidence.py:101` 仍在输出该字段，说明字段本应被填充。后果是回答里给不出「1两≈15g」这类换算注记，古制只作原文留痕。**这只是第一道阻塞**：即便修好 `loaders.py:174`，回答文本仍打不出该注记——`DoseLine`（`app/rag/schemas.py:17-22`）没有 `conversion_note` 字段，`format_dose` 也从不读取它，须先扩 schema 与构建链。该缺口已登记为已知缺陷（ETL 装载缺口 + schema 缺口），未修复前 2282 行仍为 0 条非空；不要把它当作语料局限。
- 症状→穴位映射未引用 `AcupointSymptom.source_doc`（49/49 有值但未写进引用或「依据」），引用只到穴位锚点。
- 医案号只认**句首** `问N`（`intent._CASE_NO`，允许 `问 11` 与「的/是/号/案」后缀，统一由 `intent.case_no` 判定）：前缀式「第11问」「你好，问11」不再路由到医案链；句中的「问+数字」（如「请问11岁…」「请问3天前…」）不会被当成医案号。
- 逐味 `dose_state` 未上 wire：`Answer` 不新增 `doses` 字段（计划「明确不做」把逐字段前端契约留给 UI 里程碑），M3 只在文本里用「近似/仅计数/未换算/未记载」与 `dose_complete` 呈现状态。
- 新增会话/日志表（`chat_session`/`chat_message`/`qa_log`）的生产建表路径未提供：目前只有测试夹具 `backend/tests/conftest.py` 调 `Base.metadata.create_all`，生产/开发库初始化留待 M5 部署。
- 医案多首方的剂量行合并进同一个「剂量」段，无逐方归属标注（问11 即三首合并）。
- SSE：响应头 200 在检索完成前已发出，中途检索异常没有 coded error frame；客户端断开则不执行 `session.commit()`。
- 拒答 `prose` 为空只在 `FakeLlm` 下成立；真实 LLM 的「不得新增内容」靠提示词约束，服务端保证的是 `sections`/`candidates`/`disclaimer` 已定稿。
