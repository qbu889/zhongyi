#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新生成五味归类 —— 从《本经》原文「味X」标注自动匹配中药库全部药物。"""
import re, sys

# 用法: python3 scripts/taste_group.py <中药库.md> <本经原文.txt> <输出.md>
herb_md = sys.argv[1]
source_txt = sys.argv[2]
out_md = sys.argv[3]

rows = open(herb_md, encoding="utf-8").read().splitlines()
herb_names = []
for ln in rows:
    m = re.match(r'^\| \d+ \| ([^|]+) \|', ln)
    if m:
        herb_names.append(m.group(1).strip())

text = open(source_txt, encoding="utf-8").read().replace("\n", " ")

taste_map = {}
for name in herb_names:
    for m in re.finditer(re.escape(name), text):
        window = text[m.start():m.start()+300]
        tm = re.search(r'味(酸|苦|甘|辛|咸)', window)
        if tm:
            taste_map[name] = tm.group(1)
            break

groups = {"酸": [], "苦": [], "甘": [], "辛": [], "咸": []}
for name in herb_names:
    t = taste_map.get(name)
    if t:
        groups[t].append(name)

L = [
    f"# 中药库·按五味归类（《神农本草经》{len(herb_names)}味全量）",
    "> 酸入肝、苦入心、甘入脾、辛入肺、咸入肾。",
    "> 味别据《本经》原文「味X」标注自动匹配。",
    "",
]
organ = {"酸": "肝", "苦": "心", "甘": "脾", "辛": "肺", "咸": "肾"}
for t in ["酸", "苦", "甘", "辛", "咸"]:
    L.append(f"## {organ[t]}经 · {t}味（{len(groups[t])}味）")
    L.append("")
    for i in range(0, len(groups[t]), 5):
        chunk = groups[t][i:i+5]
        L.append("、".join(f"**{n}**" for n in chunk))
    L.append("")

open(out_md, "w", encoding="utf-8").write("\n".join(L))
for t in ["酸", "苦", "甘", "辛", "咸"]:
    print(f"  {t}味({organ[t]}): {len(groups[t])}")
print(f"共匹配 {sum(len(v) for v in groups.values())}/{len(herb_names)} 味")
