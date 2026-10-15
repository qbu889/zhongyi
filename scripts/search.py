#!/usr/bin/env python3
"""Query the distilled 中医 knowledge base by symptom/description or by name.

Usage:
  python3 scripts/search.py "发烧怕冷头痛颈项强急脉浮"   # description -> ranked hits
  python3 scripts/search.py "咳嗽气喘痰多" --section 05   # limit to 针灸
  python3 scripts/search.py "桂枝汤" --name              # by formula name
  python3 scripts/search.py "丹砂"   --name --section 04  # by herb name (中药库)
  python3 scripts/search.py "腹泻腹痛水肿" --top 6 --json

Parses all distilled/*.md tables into (name/symptom, 主治/主证原文) records and maps a
description to the most relevant formula / herb / acupoint entry.
"""
import re, sys, os, json, argparse
from difflib import SequenceMatcher

REPO = "/Users/linziwang/PycharmProjects/zhongyi"
DIST = os.path.join(REPO, "distilled")

def norm(s):
    s = re.sub(r'[！-～]', lambda m: chr(ord(m.group(0)) - 0xFEE0), s)
    out = re.sub(r'(第|.*[Pp]age)\d*[页]', '', s).replace('Page', '')
    # OCR/版本 running-heads that leak into distilled tables (PDF page-break artifacts),
    # e.g. "V100415.01 7 倪注神农本草经" — strip the whole head, then any bare version stamp.
    out = re.sub(r'V\d+\.\d+\s*\d*\s*倪注神农本草经', '', out)
    out = re.sub(r'V\d+\.\d+', '', out)
    return out

CJK = re.compile(r'[一-鿿]')
RUN = re.compile(r'[一-鿿]{2,}')
SHORTC = re.compile(r'^[一-鿿]{1,4}$')
SEP = re.compile(r'^-{2,}$')
KIND_BY_DIR = {'01': '理论', '02': '伤寒方', '03': '金匮方',
               '04': '中药', '05': '针灸', '06': '医案'}

def table_rows(text):
    rows = []
    for line in text.split('\n'):
        if not line.lstrip().startswith('|'):
            continue
        inner = line.strip().strip('|')
        cells = [c.strip() for c in inner.split('|')]
        if not cells or all(SEP.match(c) for c in cells):
            continue
        rows.append(cells)
    return rows

def parse_cases(rel, text):
    """Parse the free-form 临床问答对 (问NN｜病名：主诉... / 答：辨证治法)."""
    out = []
    for piece in re.split(r'\*\*问\d*[｜|]', text)[1:]:
        nm = re.search(r'｜([^**】]{1,20})', piece)
        name = nm.group(1).strip() if nm else ''
        sm = re.search(r'[：:]\s*(.*?)(?:如何辨|怎么辨|辨)', piece, re.S)
        symptom = sm.group(1).strip() if sm else ''
        am = re.search(r'答[：:]\s*(.*?)(?=\*\*问|\Z)', piece, re.S)
        answer = am.group(0).strip() if am else ''
        body = norm('%s，%s' % (symptom, answer)).strip()
        out.append({'path': rel, 'kind': '医案',
                    'name': name or (symptom[:4] or '医案'), 'text': body})
    return out

def build_records():
    recs = []
    for root, _, files in os.walk(DIST):
        for fn in sorted(files):
            if not (fn.endswith('.md') and 'README' not in fn):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, DIST)
            kind = KIND_BY_DIR.get(rel.split(os.sep)[0][:2], '文档')
            text = norm(open(path, encoding='utf-8').read())
            if '医案' in rel:
                recs.extend(parse_cases(rel, text))
                continue
            for cells in table_rows(text):
                joined = ' '.join(cells)
                name = None
                mbr = re.search(r'\u300c([^\u300d]{2,8})\u300d', joined)  # 「桂枝汤」
                if mbr:
                    name = mbr.group(1)
                else:
                    for c in cells:
                        cc = re.sub(r'\u300c|\u300d|《|》', '', c)  # strip brackets
                        if SHORTC.match(cc) and not re.fullmatch(r'\d+', cc):
                            name = cc
                            break
                body = norm(joined)
                if name:
                    # 先删带「」括号的整段,再删裸名,避免留下空「」括号。
                    body = body.replace('「' + name + '」', '').replace(name, '')
                recs.append({'path': rel, 'kind': kind, 'name': name or '', 'text': body})
    return recs

def score(rec, qtokens, as_name):
    """Return (primary, secondary) scores.

    --name mode: primary = match to the item's own name (方名/药名),
                 secondary = body/text mentions.
    otherwise:   primary = text (主治/主证) matches,
                 secondary = name hint.
    """
    t = rec['text']
    name = rec['name']
    bodyScore = 0.0
    for tok in qtokens:
        if not tok or len(tok) < 2:
            continue
        idx = t.find(tok)
        if idx >= 0:
            bodyScore += 4.0 * len(tok)
        else:
            bodyScore += 1.5 * len(tok) * SequenceMatcher(None, tok, t).ratio()
        if 1 <= len(name) <= 3 and (tok.find(name) >= 0 or name.find(tok) >= 0):
            bodyScore += 2.5 * len(name)
    nameScore = 0.0
    if name and qtokens:
        r = SequenceMatcher(None, qtokens[0], name).ratio()
        if r > 0.3:
            nameScore = 20.0 * r
    if as_name:
        return (nameScore, bodyScore)
    return (bodyScore, 2.0 * nameScore)

def tokenize(q):
    toks = []
    for run in RUN.findall(norm(q)):
        if not re.fullmatch(r'\d+', run) and run not in toks:
            toks.append(run)
    grams = [q[i:i + 2] for i in range(len(q) - 1) if CJK.match(q[i]) and CJK.match(q[i + 1])]
    for g in grams:
        if g not in toks:
            toks.append(g)
    return toks

def search(query, section=None, top=12, as_name=False):
    qtokens = tokenize(query)
    scored = []
    for rec in build_records():
        if section and not rec['path'].startswith(section):
            continue
        sc = score(rec, qtokens, as_name)   # (primary, secondary)
        if sc[0] > 0:
            scored.append((sc, rec))
    scored.sort(key=lambda x: (-x[0][0], -x[0][1]))
    out = []
    for sc, rec in scored[:top]:
        snip = norm(rec['text']).replace(' ', ' ')
        if len(snip) > 120:
            snip = snip[:120] + '...'
        out.append({'score': round(sc[0], 2), 'kind': rec['kind'],
                    'name': rec['name'] or 'none', 'path': rec['path'], 'text': snip})
    return out

def main():
    ap = argparse.ArgumentParser(description="Query the distilled 中医 knowledge base.")
    ap.add_argument('query', nargs='*')
    ap.add_argument('--name', action='store_true')
    ap.add_argument('--section', help="path prefix, e.g. 04 / 05")
    ap.add_argument('--top', type=int, default=12)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    q = ' '.join(args.query).strip()
    if not q:
        ap.error("provide a query (symptom description, or formula/herb name with --name).")

    section = args.section or None   # raw prefix, matches '02-伤寒论/...'
    results = search(q, section=section, top=args.top, as_name=args.name)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print('(no match)')
        return
    by_kind = {}
    for r in results:
        by_kind.setdefault(r['kind'], []).append(r)
    order = ['伤寒方', '金匮方', '中药', '针灸', '医案', '理论']
    order = [k for k in order if k in by_kind] + [k for k in sorted(by_kind) if k not in order]
    label = '(by name)' if args.name else ''
    print('query: %s  %s' % (q, label))
    print()
    for kind in order:
        print('-- %s --' % kind)
        for r in by_kind[kind]:
            tag = ('[%s]' % r['name']) if r['name'] != 'none' else '(no name)'
            score = '%.1f' % r['score']
            print('  [%s] %s %s' % (score, tag, r['path']))
            print('      %s' % r['text'])
        print()

if __name__ == '__main__':
    main()
