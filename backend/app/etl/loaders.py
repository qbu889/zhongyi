"""解析记录 → 数据库（幂等 upsert）。

幂等靠**数据库唯一约束 + ON CONFLICT**，不靠「先 select 再 insert」：后者在并发 reindex 下
有竞态，「跑两次行数不变」会变成偶然成立而不是保证。

三条语义规则（PRD §5.6）：
- `formula.status` 只进不退：已 confirmed 的方不因某轮抽取置信度低而回到 candidate；
- `pending_formula_name` 的 `decision/decided_by/decided_at` 是人工资产，重跑只刷新置信度；
- 一行多方的组成**不摊派给任何一个方名**（方#28），只登记候选，宁缺勿滥。
"""

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import models


@dataclass
class LoadSummary:
    counts: dict[str, int] = field(default_factory=dict)
    noise_tokens: int = 0
    dangling_herb_items: int = 0
    skipped: dict[str, int] = field(default_factory=dict)   # 所有"静默跳过"都必须在此申报


def _insert(session: Session, model, rows: list[dict], conflict: list[str],
            update: Callable | None = None) -> None:
    if not rows:
        return
    stmt = pg_insert(model).values(rows)
    if update is None:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict)
    else:
        stmt = stmt.on_conflict_do_update(index_elements=conflict, set_=update(stmt.excluded))
    session.execute(stmt)


def _key_map(session: Session, model, key_cols: list[str]) -> dict:
    cols = [getattr(model, c) for c in key_cols] + [model.id]
    rows = session.execute(select(*cols)).all()
    if len(key_cols) == 1:
        return {r[0]: r[1] for r in rows}
    return {tuple(r[:-1]): r[-1] for r in rows}


def _no_downgrade(excluded):
    """status 只进不退：confirmed 是终态，不被后续 reindex 覆盖。"""
    return {
        "status": case((models.Formula.status == "confirmed", "confirmed"),
                       else_=excluded.status)
    }


def _formula_rows(corpus) -> dict[str, dict[str, Any]]:
    """汇总所有出现过的方名，按「confirmed 优先、pair 标记」合并。"""
    by_name: dict[str, dict[str, Any]] = {}

    def touch(name, *, anchor=None, status=None, kind=None):
        cur = by_name.setdefault(name, {"canonical_name": name, "anchor": "candidate",
                                        "status": "candidate", "kind": "single"})
        if anchor == "jingfang_zucheng":
            cur["anchor"], cur["status"] = anchor, "confirmed"
        if status == "confirmed" and cur["status"] != "confirmed":
            cur["anchor"] = anchor or cur["anchor"]
            cur["status"] = status
        if kind == "pair":
            cur["kind"] = "pair"

    for a in corpus["ancient"]:
        touch(a.name, anchor="jingfang_zucheng", status="confirmed")
    for c in corpus["classic"]:
        if c.kind == "pair":
            touch(c.names[0], kind="pair")
            for comp in c.components:
                touch(comp)
        elif len(c.names) == 1:
            touch(c.names[0])
    for e in corpus["evidence"]:
        touch(e.formula_name)
    for case_row in corpus["cases"]:
        for name in case_row.formula_names:
            touch(name)
    return by_name


def load_corpus(session: Session, corpus) -> LoadSummary:
    summary = LoadSummary()
    vocab = corpus["vocab"]

    # ---- herb ----
    herb_rows = [{
        "name": h.name, "alias": sorted(h.alias), "flavor": h.flavor,
        "flavor_source_state": h.flavor_source_state, "effects": h.effects,
        "indications": h.indications, "dosage_note": h.dosage_note, "taboo": h.taboo,
        "preparation": h.preparation, "raw_note": h.raw_note,
        "taste_group": h.taste_group, "organ_group": h.organ_group,
    } for h in corpus["herbs"]]
    _insert(session, models.Herb, herb_rows, ["name"],
            lambda ex: {c: getattr(ex, c) for c in
                        ("alias", "flavor", "flavor_source_state", "effects", "indications",
                         "dosage_note", "taboo", "preparation", "raw_note", "taste_group",
                         "organ_group")})
    herb_id = _key_map(session, models.Herb, ["name"])
    summary.counts["herb"] = len(herb_id)

    # ---- formula ----
    formula_rows = list(_formula_rows(corpus).values())
    _insert(session, models.Formula, formula_rows, ["canonical_name"],
            lambda ex: {**_no_downgrade(ex), "anchor": ex.anchor, "kind": ex.kind})
    formula_id = _key_map(session, models.Formula, ["canonical_name"])
    summary.counts["formula"] = len(formula_id)

    # ---- variant + item ----
    variant_rows, item_rows = [], []
    for a in corpus["ancient"]:
        fid = formula_id[a.name]
        variant_rows.append({"formula_id": fid, "source_doc": "经方组成", "dose_basis": "ancient",
                             "ordinal": 1, "source_row_no": a.source_row_no,
                             "raw_composition": "；".join(f"{h.herb_text} {h.dose_text}" for h in a.herbs),
                             "extract_rule_version": "identity-2026.10"})
    gram_by_row: dict[int, tuple[int, int]] = {}
    for c in corpus["classic"]:
        if c.kind != "single" or len(c.names) != 1 or not c.herbs:
            continue                      # 一行多方的组成不摊派给任何方名
        fid = formula_id[c.names[0]]
        variant_rows.append({"formula_id": fid, "source_doc": "经典配方", "dose_basis": "gram",
                             "ordinal": 1, "source_row_no": c.source_row_no,
                             "raw_composition": ", ".join(f"{n} {g}" for n, g in c.herbs),
                             "extract_rule_version": "identity-2026.10"})
        gram_by_row[c.source_row_no] = (fid, c.source_row_no)

    _insert(session, models.FormulaDoseVariant, variant_rows,
            ["formula_id", "source_doc", "source_row_no"],
            lambda ex: {"raw_composition": ex.raw_composition,
                        "extract_rule_version": ex.extract_rule_version})
    variant_id = _key_map(session, models.FormulaDoseVariant,
                          ["formula_id", "source_doc", "source_row_no"])

    def add_items(key, herbs):
        vid = variant_id.get(key)
        if vid is None:
            summary.skipped["item_orphan_variant"] = summary.skipped.get("item_orphan_variant", 0) + len(herbs)
            return
        for ordinal, (text, dose_text, g, state) in enumerate(herbs, start=1):
            resolution = vocab.resolve(text)
            if resolution.status == "noise":
                summary.noise_tokens += 1
                continue
            if resolution.canonical and resolution.canonical in herb_id:
                hid = herb_id[resolution.canonical]
            else:
                hid = None
                summary.dangling_herb_items += 1
            item_rows.append({"variant_id": vid, "herb_id": hid, "herb_text": text,
                              "dose_text": dose_text, "dose_g": g, "dose_state": state,
                              "ordinal": ordinal, "preparation": None, "conversion_note": None})

    for a in corpus["ancient"]:
        key = (formula_id[a.name], "经方组成", a.source_row_no)
        add_items(key, [(h.herb_text, h.dose_text, h.dose_g, h.dose_state) for h in a.herbs])
    for c in corpus["classic"]:
        if c.kind != "single" or len(c.names) != 1 or not c.herbs:
            continue
        key = (formula_id[c.names[0]], "经典配方", c.source_row_no)
        add_items(key, [(n, f"{g:g}克", g, "exact") for n, g in c.herbs])

    _insert(session, models.FormulaItem, item_rows,
            ["variant_id", "herb_text", "dose_text", "ordinal"],
            lambda ex: {"herb_id": ex.herb_id, "dose_g": ex.dose_g,
                        "dose_state": ex.dose_state})
    summary.counts["item"] = len(item_rows)

    # ---- evidence ----
    evidence_rows = [{"formula_id": formula_id[e.formula_name], "source_doc": e.source_doc,
                      "six_jing": e.six_jing, "bing_duan": e.bing_duan, "clause_no": e.clause_no,
                      "formula_no": None, "original_text": e.original_text,
                      "source_row_no": e.source_row_no} for e in corpus["evidence"]]
    _insert(session, models.FormulaEvidence, evidence_rows,
            ["source_doc", "source_row_no", "formula_id"],
            lambda ex: {"original_text": ex.original_text, "six_jing": ex.six_jing,
                        "bing_duan": ex.bing_duan, "clause_no": ex.clause_no})
    summary.counts["evidence"] = len(evidence_rows)

    # ---- component（合方边）----
    component_rows = []
    for c in corpus["classic"]:
        if c.kind != "pair" or not c.names:
            continue
        pair_id = formula_id[c.names[0]]
        for ordinal, comp in enumerate(c.components, start=1):
            if comp in formula_id:
                component_rows.append({"pair_formula_id": pair_id,
                                       "component_formula_id": formula_id[comp],
                                       "ordinal": ordinal})
    _insert(session, models.FormulaComponent, component_rows,
            ["pair_formula_id", "component_formula_id", "ordinal"])
    summary.counts["component"] = len(component_rows)

    # ---- variant_pair（D8 物化）----
    pair_rows = []
    for p in corpus["pairs"].pairs:
        fid = formula_id.get(p.formula_name)
        if fid is None:
            continue
        va = variant_id.get((fid, "经方组成", p.variant_a_source_row_no))
        vb = variant_id.get((fid, "经典配方", p.variant_b_source_row_no))
        if va is None or vb is None:
            # 克数版该行无可解析药味 → 没有 variant 可指。跳过必须申报，不能静默：
            # 实测 verify 产出 81 对、可落库 77 对，差的 4 对就藏在这里
            summary.skipped["pair_missing_variant"] = summary.skipped.get("pair_missing_variant", 0) + 1
            continue
        pair_rows.append({"formula_id": fid, "variant_a": va, "variant_b": vb,
                          "pairing_method": "algorithmic", "herb_diff": p.herb_diff,
                          "dose_dev": p.dose_dev, "score": p.score,
                          "algorithm_version": p.algorithm_version})
    _insert(session, models.FormulaVariantPair, pair_rows,
            ["formula_id", "variant_a", "variant_b"],
            lambda ex: {"herb_diff": ex.herb_diff, "dose_dev": ex.dose_dev,
                        "score": ex.score, "algorithm_version": ex.algorithm_version})
    summary.counts["pair"] = len(pair_rows)

    # ---- pending（人工判定不覆盖）----
    pending_rows = [{"raw_name": c.raw_name_field[:500], "doc": "方剂库-经典配方.md",
                     "source_row_no": c.source_row_no, "suggested_parent": None,
                     "confidence": 0.0, "evidence_text": c.remark[:500],
                     "decision": "pending"}
                    for c in corpus["classic"] if not c.names]
    _insert(session, models.PendingFormulaName, pending_rows,
            ["raw_name", "doc", "source_row_no"],
            lambda ex: {"confidence": ex.confidence, "evidence_text": ex.evidence_text,
                        "suggested_parent": ex.suggested_parent})
    summary.counts["pending"] = len(pending_rows)

    # ---- case ----
    case_rows = [{"no": cs.no, "category": cs.category, "chief_complaint": cs.chief_complaint,
                  "pathogenesis": cs.pathogenesis,
                  "treatment_formula_ids": [formula_id[n] for n in cs.formula_names if n in formula_id],
                  "added_herbs": cs.added_herbs, "tips": cs.tips, "raw_md": cs.raw_md}
                 for cs in corpus["cases"]]
    _insert(session, models.Case, case_rows, ["no"],
            lambda ex: {c: getattr(ex, c) for c in
                        ("category", "chief_complaint", "pathogenesis", "treatment_formula_ids",
                         "added_herbs", "tips", "raw_md")})
    summary.counts["case"] = len(case_rows)

    # ---- acupoint（症状表引用的穴名若不在穴位库，补 meridian=None 的行，不丢数据）----
    acupoint_rows = [{"name": p.name, "meridian": p.meridian, "role": "·".join(p.roles),
                      "location": p.location, "actions": p.actions} for p in corpus["acupoints"]]
    known = {p["name"] for p in acupoint_rows}
    for s in corpus["acupoint_symptoms"]:
        if s.point not in known:
            acupoint_rows.append({"name": s.point, "meridian": None, "role": "",
                                  "location": "", "actions": ""})
            known.add(s.point)
    _insert(session, models.Acupoint, acupoint_rows, ["name", "meridian"],
            lambda ex: {"role": ex.role, "location": ex.location, "actions": ex.actions})
    acupoint_id = _key_map(session, models.Acupoint, ["name"])
    summary.counts["acupoint"] = len(acupoint_id)

    symptom_rows = [{"acupoint_id": acupoint_id[s.point], "symptom": s.symptom,
                     "source_doc": s.source_doc} for s in corpus["acupoint_symptoms"]
                    if s.point in acupoint_id]
    skipped_symptoms = len(corpus["acupoint_symptoms"]) - len(symptom_rows)
    if skipped_symptoms:
        summary.skipped["acupoint_symptom"] = skipped_symptoms
    _insert(session, models.AcupointSymptom, symptom_rows,
            ["acupoint_id", "symptom", "source_doc"])
    summary.counts["acupoint_symptom"] = len(symptom_rows)

    # ---- framework_chunk ----
    chunk_rows = [{"doc": c.doc, "section": c.section, "content": c.content,
                   "chunk_order": c.chunk_order} for c in corpus["framework"]]
    _insert(session, models.FrameworkChunk, chunk_rows, ["doc", "chunk_order"],
            lambda ex: {"content": ex.content, "section": ex.section})
    summary.counts["framework_chunk"] = len(chunk_rows)

    return summary
