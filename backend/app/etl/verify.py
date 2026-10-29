"""变体配对物化（PRD §5.6 D8）：古制版 ↔ 克数版的对照结果。

这一步在 ETL 里算完并落 `formula_variant_pair`，不在请求路径跑 Jaccard——
运行时算不可复现，同一个方在不同时刻可能给出不同黄牌，直接撞 NFR-4/NFR-6。

算法仍不在 backend 重写：归一用 `scripts/formula_verify.normalize`、古制转克用 `ancient_to_g`、
版本优选沿用 `best_match` 的「严格大于」语义（平分时取语料行序靠前的版本），本模块只负责编排。
"""

from dataclasses import dataclass, field

from app.etl.scripts_loader import LOADER

ALGORITHM_VERSION = "pair-2026.10"
DEVIATION_THRESHOLD_PCT = 50.0


@dataclass
class VariantPairRecord:
    formula_name: str
    variant_a_source_row_no: int | None
    variant_b_source_row_no: int | None
    pairing_method: str = "algorithmic"
    herb_diff: dict[str, list[str]] = field(default_factory=dict)
    dose_dev: dict[str, dict[str, float]] = field(default_factory=dict)
    score: float | None = None
    algorithm_version: str = ALGORITHM_VERSION


@dataclass
class PairingResult:
    pairs: list[VariantPairRecord] = field(default_factory=list)
    only_ancient: list[str] = field(default_factory=list)
    only_gram: list[str] = field(default_factory=list)


def _normalized(text: str) -> str:
    return LOADER.verify.normalize(text)


def _herb_set(pairs, vocab=None, noise_sink: list[str] | None = None) -> set[str]:
    """归一后的药味集合。给了词表就把解析噪声剔出去并记录：
    实测 克数版的正则会把「取乌头/水煮成/每次/加工成/段糯米」当药味，
    不过滤的话 FR-13 ① 与黄牌会被垃圾主导。"""
    out: set[str] = set()
    for name, _ in pairs:
        normalized = _normalized(name)
        if vocab is not None and vocab.resolve(name).status == "noise":
            if noise_sink is not None:
                noise_sink.append(name)
            continue
        out.add(normalized)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _index_gram(classic) -> dict[str, list]:
    """克数版索引。D9：`kind=pair` 的合方行不参与对照；无方名或无药味的行也不入。"""
    by_name: dict[str, list] = {}
    for row in classic:
        if row.kind == "pair" or not row.herbs or not row.names:
            continue
        for name in row.names:
            by_name.setdefault(name, []).append(row)
    return by_name


def _pick_best(ancient_herbs: set[str], versions: list) -> tuple:
    """沿用脚本 `best_match` 的严格大于语义：平分时保留语料行序靠前者，保证可复现。"""
    best, best_score = None, -1.0
    for row in versions:
        score = _jaccard(ancient_herbs, _herb_set(row.herbs))
        if score > best_score:
            best, best_score = row, score
    return best, best_score


def _dose_deviations(ancient, gram_row, vocab=None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    gram_by_herb: dict[str, float] = {}
    for name, grams in gram_row.herbs:
        gram_by_herb.setdefault(_normalized(name), grams)
    for item in ancient.herbs:
        # 只有拿到可比克数才算偏差：count_only/absent/unknown_unit 无基数（实测占 31%）
        if item.dose_g is None:
            continue
        if vocab is not None and vocab.resolve(item.herb_text).status == "noise":
            continue
        gram_g = gram_by_herb.get(_normalized(item.herb_text))
        if not gram_g:
            continue
        deviation = abs(item.dose_g / gram_g - 1) * 100
        if deviation > DEVIATION_THRESHOLD_PCT:
            out[item.herb_text] = {"ancient_g": item.dose_g, "gram_g": gram_g,
                                   "deviation_pct": round(deviation, 1)}
    return out


def build_variant_pairs(ancient, classic, vocab=None) -> PairingResult:
    """vocab: `herb_vocab.HerbVocab`，用于剔除解析噪声；不传则保持原始集合语义。"""
    gram_by_name = _index_gram(classic)
    ancient_names = {a.name for a in ancient}
    result = PairingResult()

    for formula in ancient:
        versions = gram_by_name.get(formula.name)
        if not versions:
            result.only_ancient.append(formula.name)
            continue
        ancient_set = _herb_set([(h.herb_text, h.dose_g) for h in formula.herbs], vocab)
        best, score = _pick_best(ancient_set, versions)
        gram_set = _herb_set(best.herbs, vocab)
        result.pairs.append(VariantPairRecord(
            formula_name=formula.name,
            variant_a_source_row_no=formula.source_row_no,
            variant_b_source_row_no=best.source_row_no,
            herb_diff={"missing_in_gram": sorted(ancient_set - gram_set),
                       "missing_in_ancient": sorted(gram_set - ancient_set)},
            dose_dev=_dose_deviations(formula, best, vocab),
            score=round(score, 4),
        ))

    result.only_gram = sorted(n for n in gram_by_name if n not in ancient_names)
    result.only_ancient.sort()
    return result
