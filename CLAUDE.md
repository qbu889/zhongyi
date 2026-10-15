# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## What this repo is
A pipeline that distills Traditional Chinese Medicine (中医) books — the 倪海厦 (Ni Haixia) "人纪"
series plus related volumes — from PDFs into searchable Markdown knowledge bases.

- `*.pdf` at repo root = source books (do not edit).
- `text/` = plain-text extracted from each PDF (~17 files, ~4.4M chars). Regenerate with
  `pdftotext "<pdf>" "text/<name>.txt"` (stdlib-free; needs the `poppler-utils` `pdftotext`).
- `scripts/` = 6 pure-stdlib-Python extractors (`re`, `sys` only; no deps, no `requirements.txt`).
- `distilled/` = Markdown outputs (方剂库 经方、中药库、辨证框架、医案问答、针灸穴位) — the deliverables.

Data flow: `PDF → text/ (pdftotext) → scripts/* .py → distilled/*.md`.

## Claude Code Skills (``.claude/skills/``)
Five project skills turn `distilled/` into reusable clinical capabilities. Each encodes
**data sources + retrieval anchors + hard rules + output format** so answers stay strictly local.
They auto-trigger on the `description` keywords, or call by `shortcut`.

| skill (shortcut) | does | primary `distilled/` data |
|---|---|---|
| `formula-lookup` (`formula`) | 查方剂组成/剂量/出处/克数 | `方剂库-经典配方.md`、`方剂库-经方组成.md`、`03-金匮/金匮方剂库.md`、`02-伤寒论/伤寒六经方库.md` |
| `syndrome-differentiation` (`bianzheng`) | 六经辨证 / 问诊基准 / 定制定方 | `02-伤寒论/六经辨证框架.md`、`02-伤寒论/临证诊断与治则补充.md`、`06-医案/临床问答对.md` |
| `herb-lookup` (`herb`) | 中药性味功效 / 按五味五脏 / 古名对照 | `04-神农本草经/中药库.md`（379味）、`04-神农本草经/药物按味归类.md` |
| `acupoint-selection` (`xuewei`) | 穴位角色 / 按症取穴 | `05-针灸/十二经穴位库.md`、`05-针灸/针灸治症取穴.md` |
| `clinical-case` (`anyi`) | 生成/整理经方医案问答对 | `06-医案/临床问答对.md` |

Shared hard rules (all skills): name/herb/acupoint/pathology must be `grep`-able in `distilled/`
(or `text/`); never invent; doses only in grams (古制 `1两≈15g`, keep original in a parenthetical);
end with the 执业中医师面诊 disclaimer. **Symptom note:** `05-针灸/针灸治症取穴.md` has **no**
咳嗽/喘 section (咳·喘 count = 0) — respiratory acupoints come from `十二经穴位库.md` (列缺、照海)
and 俞募 (肺俞＋中府) in `06-医案/临床问答对.md`.

Validate everything with `bash scripts/skills_validate.sh` (add `demo <query>` to also run a
sample retrieval, e.g. `bash scripts/skills_validate.sh demo 射干麻黄汤`).

> ⚠️ Shell note: in this repo `grep` is wrapped as a function that calls the claude binary and
> errors out ("claude native binary not installed"). Use `command grep` to bypass (skills and the
> validate script already do).

## Run the extractors
Arg conventions vary by script — read each command below; paths are referenced from repo root.
`shaohan_index.py` uses `-o <out>` + one or more `text/` inputs; `fx_extract.py` and `herb_extract.py`
write to **stdout** (redirect with `>`); `taste_group.py` takes 3 args; the rest take output `.md` path(s).

```bash
# 伤寒六经方库 — quoted「...汤」names grouped by 六经 (太阳/阳明/太阴/少阳/少阴/厥阴)
python3 scripts/shaohan_index.py -o distilled/02-伤寒论/伤寒六经方库.md "text/倪海厦人纪系列之伤寒论.txt"

# 金匮方剂库 — hardcodes BOTH 《金匮》txts, groups by「辨XX病脉证」sections (719条)
python3 scripts/jincha_extract.py "distilled/03-金匮/金匮方剂库.md"

# 中药库 — args are the 《神农本草经》 txts to merge (dedup keep-first field); writes table to stdout.
#   All three version files exist in text/; pass whichever you want merged:
python3 scripts/herb_extract.py \
    "text/倪海厦人纪系列之神农本草经.txt" \
    "text/倪海夏-人纪-简体横版神农本草经.txt" \
    "text/倪海夏《神农本草经》完整版——可直接打印.txt" > distilled/04-神农本草经/中药库.md

# 经典配方 — arg is the INPUT text (not an output path); writes to stdout → redirect.
python3 scripts/fx_extract.py "text/经典配方.txt" > distilled/方剂库-经典配方.md

# 药物按味归类 — READS the 中药库 table (arg1) + 《本经》原文 txt (arg2, for 「味X」 lookup);
#   must run after herb_extract. Three args: <中药库.md> <本经原文.txt> <输出.md>.
python3 scripts/taste_group.py "distilled/04-神农本草经/中药库.md" \
                               "text/倪海厦人纪系列之神农本草经.txt" \
                               "distilled/04-神农本草经/药物按味归类.md"

# 针灸穴位 — reads two HARDCODED sources (`text/倪海厦人纪系列之针灸教程.txt` +
#   `text/倪海夏-人纪-简体针灸教程.txt`; no input arg). Point roles (五输/原/络/郄/募) come from a
#   hardcoded 十四经 CHANNELS table in the script (《针灸学》教材正经底表), so only standard
#   acupoint names that actually appear in the source are emitted — loose prose like "俞原经"
#   "在脏取" is never output. argv[1]/argv[2] are the two OUTPUT paths (default: committed).
python3 scripts/acupoint_extract.py \
    "distilled/05-针灸/十二经穴位库.md" \
    "distilled/05-针灸/针灸治症取穴.md"
```

Produce the reference run via `distilled/README.md` (authoritative inventory).

## Dependency ordering matters
`taste_group.py` parses table rows, so `herb_extract.py` (which writes the 中药库 table) must run
first. Jincha/haohan/fx are independent of each other.

## Common script internals (read once)
Every extractor shares a `norm()` that folds full-width ASCII (`U+FF01–U+FF5E`→half) and the full-width
space (`U+3000`) to a normal space, then strips `第N页` header lines. Extraction is regex-driven on:
quoted classical formula names `「...汤」`, herb+dose pairs (`([一-鿿]{1,4})<num><枚两钱帖分位>`),
and `【气味】【主治】…` field markers. Regexes are deliberately strict (CJK class + negative lookahead on
unit chars) — loosen them only if extraction is too sparse, never by dropping the unit-character guard.

## ⚠️ Known state: duplicate outputs (bracketed vs numbered)
`distilled/` contains two copies of several deliverables from an early session: top-level files with a
full-width paren in the name (e.g. `02-伤寒论(经方库.md`, `03-金匮(方剂库.md`,
`04-神农本草经(中药库.md`) **and** their correct numbered-subdirectory versions
(`02-伤寒论/伤寒六经方库.md`, `03-金匮/金匮方剂库.md`, `04-神农本草经/中药库.md`).

Use the **numbered-subdirectory** versions (they match `distilled/README.md`); the top-level bracketed
files are stale duplicates. Clean them up with `rm "distilled/02-伤寒论(经方库.md" ...` (quote the paths
with the full-width parenthesis) when consolidating.

## Domain note
This is 经方 (classical-formula) medicine material. Understand the `六经辨证` framework
(太阳→阳明/少阳/太阴/少阴/厥阴) and 《金匮》's 二十二篇病 grouping before editing extraction regexes —
they define which lines a formula belongs to. See `distilled/02-伤寒论/六经辨证框架.md`.

## ⚠️ DIAGNOSIS MUST BE STRICTLY LOCAL (临床诊断强制规则)
When asked to diagnose / 辨证 / give a 医案 or 问诊 reply, **every claim must be grounded in the
local distillate** (`distilled/*.md` and `text/*.txt`). No generic TCM knowledge may be asserted as if
it came from these books.

### Workflow (do this for every diagnosis)
1. **Locate sources first.** Search before answering:
   - 六经辨证框架 → `distilled/02-伤寒论/六经辨证框架.md`
   - 方剂(经方组成 / 经典配方) → `distilled/03-金匮/金匮方剂库.md`, `distilled/方剂库-经方组成.md`, `distilled/方剂库-经典配方.md`
   - 中药 → `distilled/04-神农本草经/中药库.md`
   - 针灸取穴 → `distilled/05-针灸/*.md`
   - 原文 / 医案 → `text/*.txt` (grep for the exact formula or symptom)
2. **Map each symptom to a local line/formula.** For every formula you recommend, cite where it lives
   (`金匮方剂库.md` section e.g. 「辨水气病脉证治」; `伤寒六经方库.md` 六经 grouping).
3. **State the source explicitly** in the reply (e.g. "苓桂术甘汤 —《金匮》辨水气病篇").

### Hard rules
- **No formula, herb, acupoint or 治则 may be named unless it exists in `distilled/` or `text/`.** If a
  candidate is not found by grep, do NOT recommend it.
- **Separate the two tiers of knowledge explicitly.** Anything that comes from local distillate = cite
  its file/section; anything that is general framework (六经/八纲 logic) must be labeled as such and may
  only *organize* the local findings, never replace them.
- **Never invent doses** unless a dose appears in `经典配方.md` / `方剂库-经方组成.md`. Otherwise give
  direction + "须医师辨证定剂量".
- End with the standard disclaimer (执业中医师面诊) — it is part of the house style, not filler.

### Output format (match `distilled/06-医案/临床问答对.md`)
问(主诉脉舌) → 答(病机，逐条对应本地条文) → 治(经方 + 出处) → 要诀/调护(仅列库内穴位与法).
When the user approves, save the case as a new entry under `distilled/06-医案/`.

### ⚠️ DOSE MUST BE CONVERTED TO GRAMS (强制·古剂量转现代克数)
**Every formula dose in any diagnosis/output must end in modern grams (克). No bare 两/枚/升/合/分/铢 may be emitted as a final answer.**

#### Conversion logic (use the local library's own standard first)
Run `python3 scripts/dose_convert.py --batch distilled/方剂库-经方组成.md <out>.md` to auto-generate a gram table for every formula, or use it single-dose: `python3 scripts/dose_convert.py "半夏 半斤"`. The script encodes the local standard and shows each conversion.
2. **Cross-check both library versions** when recommending a formula (古制 vs 现成克数版):
   `python3 scripts/formula_verify.py distilled/方剂库-经方组成.md distilled/方剂库-经典配方.md distilled/03-金匮/方剂交叉校验.md`
   → flags 药材差异 and 剂量偏差>50%. Note: two dose systems exist (汉制原书大剂量 vs 现代临床小剂量); 大柴胡汤/射干麻黄汤 etc. show >50% deviation by design — inspect 药材差异, not raw 剂量偏差.
1. **Prefer the ready-made gram version** already in `distilled/方剂库-经典配方.md` when it exists — use it verbatim, cite its 方# number.
2. When only an ancient dose is available (`distilled/方剂库-经方组成.md` / `text/*.txt`), convert with the **local standard**:
   - **汉制换算：1两 ≈ 15g** (source: `distilled/方剂库-经方组成.md` line 3).
   - Derived: 半两 = 7.5g；一两半 = 22.5g；半斤(=4两) = 60g；一斤(=8两) = 120g；四两 = 60g。
   - **枚**：附子 1枚 ≈ 15g (reverse-derived from `经典配方.md` 真武汤·炮附子15克); 大枣 12枚 → per-library gram version.
   - **升/合/铢/分**: the library has no single unified factor — convert with a stated assumption and mark "临床以医生为准", or fall back to the `经典配方.md` gram version of the same formula.
3. **Show the conversion** for ancient doses, e.g. `茯苓 三两 → 45g (1两≈15g)`.

#### Hard rules
- Final output table = grams only; keep the original ancient dose in a parenthetical or note so the math is auditable.
- If a formula has BOTH versions in the library, use the gram version and note the source 方#.
- Never invent a conversion factor that contradicts the local `1两≈15g` standard without explicitly flagging it as an assumption.
