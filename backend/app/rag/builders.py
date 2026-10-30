"""FR-4 结构化回答：字段全部由 DB 事实拼装；LLM 只写 prose。"""

import re

from sqlalchemy import select

from app.db.models import (
    Acupoint, AcupointSymptom, Case, Formula, FormulaDoseVariant, FormulaEvidence,
    FormulaItem, Herb,
)
from app.rag import intent as intent_mod
from app.rag.gate import DISCLAIMER
from app.rag.schemas import Answer, Citation, DoseLine, Section, citation_from_hit
from app.search import anchors as anchor_mod
from app.search import query as qmod
from app.search.query import MATCH_EXACT, Hit

_INCOMPLETE_HINT = "本方剂量不完全可执行（含非 exact 药味）"
_DOSE_STATE_LABELS = {"approx": "近似", "count_only": "仅计数",
                      "absent": "未记载", "unknown_unit": "未换算"}


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
    complete = all(line.dose_state == "exact" for line in lines) if lines else None
    return lines, complete


def format_dose(line: DoseLine) -> str:
    if line.g is not None:
        # 近似值不得与精确值同样式呈现（NFR-4）：古制留痕后必须带「近似」。
        if line.dose_state == "approx":
            trace = f"（{line.ancient}，近似）" if line.ancient else "（近似）"
        else:
            trace = f"（{line.ancient}）" if line.ancient else ""
        return f"{line.herb} {line.g:g}g{trace}"
    label = _DOSE_STATE_LABELS.get(line.dose_state, line.dose_state)
    return f"{line.herb} {line.ancient or '剂量未记载'}（{label}）"


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
        sections.append(Section(title="提示", lines=[_INCOMPLETE_HINT]))
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
    flags: list[bool] = []
    for fid in case.treatment_formula_ids or []:
        lines, complete = compose_dose_lines(session, fid)
        doses.extend(format_dose(d) for d in lines)
        if complete is not None:
            flags.append(complete)
    if doses:
        sections.append(Section(title="剂量", lines=doses))
    dose_complete = all(flags) if flags else None
    if dose_complete is False:
        sections.append(Section(title="提示", lines=[_INCOMPLETE_HINT]))
    return Answer(intent="E", headline=f"{case.no}（{case.category or '未分类'}）",
                  sections=sections,
                  citations=[Citation(ref_type="case", ref_id=case.id, title=case.no,
                                      anchor=anchor_mod.case_anchor(case.no))],
                  dose_complete=dose_complete, disclaimer=DISCLAIMER)


_VAGUE_WORDS = re.compile(
    r"我该怎么办|怎么回事|什么问题|不舒服|难受|不适|不好|看看|怎么办|咋办|帮帮我"
    r"|有点|有些|老是|总是|觉得|感觉|就是|真的|特别|最近|一直|很|老|太|我|了|啊|呀|呢")
_FILLER = re.compile(r"[\s，,。？?！!、]")


def build_followup(query: str) -> list[str]:
    """FR-5：只有泛泛主诉（「不舒服/难受」）或空问句才追问；具体症状词不拦。"""
    core = _FILLER.sub("", qmod.normalize_query(query))
    if core and _VAGUE_WORDS.sub("", core):
        return []
    return ["主要不适在哪个部位？（头项/胸胁/脘腹/四肢/全身）",
            "有无恶寒发热、汗出、口渴？大便、小便与平时相比如何？",
            "睡眠、胃口、精神怎样？起病多久了？"]


def _treatment_section(session, formula_ids: list[int]) -> tuple[Section | None, bool | None]:
    names, doses, flags = [], [], []
    for fid in formula_ids:
        formula = session.get(Formula, fid)
        if formula is None:
            continue
        names.append(formula.canonical_name)
        lines, complete = compose_dose_lines(session, fid)
        doses.extend(format_dose(d) for d in lines)
        if complete is not None:
            flags.append(complete)
    if not names:
        return None, None
    section = Section(title="定方", lines=[f"治：{'、'.join(names)}"] + doses)
    return section, (all(flags) if flags else None)


def build_syndrome(session, query: str, hits, case_hits) -> Answer:
    case_hit = next((h for h in case_hits if h.ref_type == "case" and h.score >= 0.30), None)
    sections = [Section(title="辨证", lines=[f"{h.title}：{h.snippet}" for h in hits[:3]]
                        or ["本地库未检索到对应条文"])]
    citations = [citation_from_hit(h) for h in hits[:3]]
    treatment = None
    dose_complete = None
    if case_hit is not None:
        case = session.get(Case, case_hit.ref_id)
        treatment, dose_complete = _treatment_section(
            session, list(case.treatment_formula_ids or []))
        citations.insert(0, Citation(ref_type="case", ref_id=case.id, title=case.no,
                                     anchor=anchor_mod.case_anchor(case.no)))
        if case.tips:
            sections.append(Section(title="调护", lines=[case.tips]))
    else:
        # 没有够分的医案时，只认整名精确的方剂 hit；向量近邻不能当作定方依据
        formula_hit = next((h for h in hits if h.ref_type == "formula"
                            and h.match == MATCH_EXACT), None)
        if formula_hit is not None:
            treatment, dose_complete = _treatment_section(session, [formula_hit.ref_id])
    if treatment is None:
        # 语料事实：部分医案只写方名不给结构化 formula_id 时不造方
        treatment = Section(title="定方", lines=["本条未落到结构化方剂"])
    sections.insert(1, treatment)
    if dose_complete is False:
        sections.append(Section(title="提示", lines=[_INCOMPLETE_HINT]))
    return Answer(intent="A", headline=query, sections=sections, citations=citations,
                  dose_complete=dose_complete, disclaimer=DISCLAIMER,
                  top_score=_top_score(hits, case_hits))


def build_composite(session, query: str, hits, case_hits, found=None) -> Answer:
    """组合问句：实体用 mentions 解析（整句检索命中不了「桂枝汤配合风池穴」里的正名）。"""
    found = intent_mod.mentions(session, query) if found is None else found
    syndrome = build_syndrome(session, query, hits, case_hits)
    sections = [Section(title="辨证", lines=syndrome.sections[0].lines)]
    citations = list(syndrome.citations)

    dose_complete = None
    # 辨证链的定方剂量不在组合段展示，只有「组成」里点名的方参与 dose_complete。
    if "formula" in found:
        built = build_formula(session, found["formula"][0])
        sections.append(Section(title="组成", lines=built.sections[0].lines))
        citations.extend(built.citations)
        dose_complete = built.dose_complete

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

    if dose_complete is False:
        sections.append(Section(title="提示", lines=[_INCOMPLETE_HINT]))
    return Answer(intent="F", headline=query, sections=sections, citations=citations,
                  dose_complete=dose_complete, disclaimer=DISCLAIMER,
                  top_score=_top_score(hits, case_hits))
