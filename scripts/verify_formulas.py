#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐首验证：对照原文'右N味'标注，看抽到的药味数是否一致。"""
import re, sys
sys.path.insert(0, 'scripts')
from formula_extract import extract_formulas

def expected_count(txt_path):
    """返回 {方名: 原文声明的药味数}"""
    text = open(txt_path, encoding="utf-8").read()
    lines = text.splitlines()
    result = {}
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        m = re.match(r'^([\u4e00-\u9fa5]{2,12})(汤|丸|散|丹|膏|饮)\s*方$', ln)
        if not m:
            i += 1; continue
        fname = m.group(1) + m.group(2)
        # 往后找"右N味/上N味"
        for j in range(i+1, min(i+25, len(lines))):
            seg = lines[j].strip()
            em = re.match(r'^[右上]\s*([一二三四五六七八九十百\d]+)\s*味', seg)
            if em:
                num_str = em.group(1)
                # 中文数字转阿拉伯
                cn = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
                if num_str.isdigit():
                    n = int(num_str)
                elif num_str == '十':
                    n = 10
                elif '十' in num_str:
                    parts = num_str.split('十')
                    tens = cn.get(parts[0], 1) if parts[0] else 1
                    ones = cn.get(parts[1], 0) if len(parts)>1 and parts[1] else 0
                    n = tens*10 + ones
                else:
                    n = cn.get(num_str, 0)
                result[fname] = n
                break
            if re.match(r'^[右上]\s*[一二三四五六七八九十百\d]+\s*(物|株|个|枚)', seg):
                break
        i += 1
    return result

sh_extracted = extract_formulas("text/倪海厦人纪系列之伤寒论.txt")
jg_extracted = extract_formulas("text/倪海厦人纪系列之金匮要略.txt")
sh_expected = expected_count("text/倪海厦人纪系列之伤寒论.txt")
jg_expected = expected_count("text/倪海厦人纪系列之金匮要略.txt")

# 合并
all_ext = {}
for k, v in sh_extracted.items():
    all_ext[k] = {'herbs': v, 'src': '伤寒'}
for k, v in jg_extracted.items():
    if k in all_ext:
        existing = {h[0] for h in all_ext[k]['herbs']}
        for h in v:
            if h[0] not in existing:
                all_ext[k]['herbs'].append(h)
        all_ext[k]['src'] = '伤寒+金匮'
    else:
        all_ext[k] = {'herbs': v, 'src': '金匮'}

all_exp = {}
all_exp.update(sh_expected)
all_exp.update(jg_expected)

# 验证
ok, mismatch, missing, no_expected = [], [], [], []
for name, info in sorted(all_ext.items()):
    actual = len(info['herbs'])
    if name in all_exp:
        expected = all_exp[name]
        if actual == expected:
            ok.append((name, actual))
        else:
            mismatch.append((name, expected, actual, info['herbs']))
    else:
        no_expected.append((name, actual))

print(f"总方数: {len(all_ext)}")
print(f"有原文'N味'标注: {len(all_exp)}")
print(f"\n=== ✅ 完全一致: {len(ok)} 首 ===")
for n, c in ok[:10]:
    print(f"  {n} ({c}味)")
print(f"  ...共{len(ok)}首")

print(f"\n=== ⚠️ 味数不符: {len(mismatch)} 首 ===")
for n, exp, act, herbs in mismatch:
    names = [h[0] for h in herbs]
    print(f"  {n}: 原文{exp}味, 抽到{act}味 → {names}")

print(f"\n=== ❓ 原文无'N味'标注: {len(no_expected)} 首 ===")
for n, c in no_expected[:15]:
    print(f"  {n} ({c}味)")
print(f"  ...共{len(no_expected)}首")
