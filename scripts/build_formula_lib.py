#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并伤寒+金匮方组成，生成经方组成速查库。"""
import re, sys
sys.path.insert(0, 'scripts')
from formula_extract import extract_formulas
from formula_override import OVERRIDE

sh = extract_formulas("text/倪海厦人纪系列之伤寒论.txt")
jg = extract_formulas("text/倪海厦人纪系列之金匮要略.txt")

# 合并：金匮优先（同方名金匮方更完整），伤寒补充
all_f = {}
for k, v in sh.items():
    all_f[k] = {'source': '伤寒', 'herbs': v}
for k, v in jg.items():
    if k in all_f:
        existing = {h[0] for h in all_f[k]['herbs']}
        for h in v:
            if h[0] not in existing:
                all_f[k]['herbs'].append(h)
        all_f[k]['source'] = '伤寒+金匮'
    else:
        all_f[k] = {'source': '金匮', 'herbs': v}

# 应用 override（对照原文/教材标准修正44首偏差方）
for k, v in OVERRIDE.items():
    src = all_f[k]['source'] if k in all_f else '金匮'
    all_f[k] = {'source': src, 'herbs': v}

# 按方名排序
names = sorted(all_f.keys())

L = [
    "# 经方组成速查库（伤寒+金匮合并）",
    "> 从原文「XX汤方」后自动抽取药味+剂量+炮制，44首偏差方已对照原文修正。",
    f"> 共 {len(all_f)} 首方。汉制换算：1两≈15g（临床以医生为准）。",
    ">",
    "| 方名 | 来源 | 组成（药味·剂量·炮制） |",
    "|---|---|---|",
]
for name in names:
    info = all_f[name]
    cleaned = []
    # 常见噪声词（非药名）
    noise = {'小便','大便','上右','右一','右二','右三','上一','上二','上三','水一','水二','水三'}
    for h, d, p in info['herbs']:
        h = re.sub(r'[各第页]$', '', h)
        h = re.sub(r'^(第|页)', '', h)
        p = re.sub(r'第\s*\d+\s*页?', '', p)
        p = p.strip('，,。 ')
        # 过滤噪声
        if '方' in h or h in noise or len(h) < 1:
            continue
        if h == name:
            continue
        cleaned.append((h, d, p))
    herbs_str = "；".join(f"**{h}** {d}" + (f"（{p}）" if p else "") for h, d, p in cleaned)
    L.append(f"| {name} | {info['source']} | {herbs_str} |")

open("distilled/方剂库-经方组成.md", "w", encoding="utf-8").write("\n".join(L))
print(f"共 {len(all_f)} 首方")
print(f"伤寒 {len(sh)}，金匮 {len(jg)}，合并去重后 {len(all_f)}")
