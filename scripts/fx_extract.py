import re, sys

def norm(s):
    out=[]
    for ch in s:
        o=ord(ch)
        if 0xFF01<=o<=0xFF5E: out.append(chr(o-0xFEE0))
        elif o==0x3000: out.append(' ')
        else: out.append(ch)
    return ''.join(out)

def extract(path):
    src=norm(open(path,encoding='utf-8').read())
    src=re.sub(r'\n第[0-9]+页\n','\n',src)
    lines=src.split('\n')
    # entry header: line containing 处方/基础方/验方, or mentioning 出自
    hdr=re.compile(r'(治疗|主[治]?[用语]?)?.{0,40}(处方|基础方|验方)|出自')
    idxs=[i for i,l in enumerate(lines) if hdr.search(l)]
    entries=[]
    for a,b in zip(idxs, idxs[1:]+[len(lines)]):
        seg=lines[a:b]
        header=seg[0].strip()
        formula=re.search(r'--\s*《?([^《》)(]+)',header)
        formula=(formula.group(1).strip('《》') if formula else '').rstrip(')')
        body=' '.join(seg[1:])
        notes=[l for l in seg[1:] if re.match(r'注:',l)]
        # herb + dose : name(<=4 CJK, not a unit char) + number(s) + optional unit
        pairs=re.findall(r'([一-鿿]{1,3})(?![|克枚两钱帖分位])\s*([0-9]+(?:\.[0-9]+)?)\s*(克|枚|两|钱|帖|分|位)?', body)
        # keep valid pairs (must have a number; drop pure notes like 煎/服)
        valid=[p for p in pairs if p[1]]
        if not valid:
            # some herbs lack dose -> grab (name)(unit) only
            alt=re.findall(r'([一-鿿]{2,3})(?![|克枚两钱帖分位])(克|枚|两|钱|帖|分|位)', body)
            valid=[(n,'?',u) for n,u in alt]
        # de-dup consecutive identical herbs (OCR line repeats) and fix stray unit prefix
        clean=[]; last=''
        for n,d,u in valid:
            if n==last: continue
            clean.append((n.lstrip('枚两钱帖分'),'?',u) if (d=='' and u) else (n,d,u))
            last=n
        ing=', '.join(f'{n} {d}{u}' for (n,d,u) in valid[:12])
        entries.append((header,formula,ing,'; '.join(notes).strip('注:')))
    print(f'# 《经典配方》蒸馏 — 方剂库\n')
    print('| # | 病证/方名 | 组成(药材·剂量) | 备注 |')
    print('|---|---|---|---|')
    for i,(h,f,ing,nt) in enumerate(entries,1):
        usage=re.sub(r'\s+','',h).rstrip(')').replace('(出自', ' — 出自')
        print(f'| {i} | {usage} · {f or "—"} | {ing} | {nt} |')
    return entries

if __name__=='__main__':
    extract(sys.argv[1])
