#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""古剂量转现代克数（汉制换算 1两≈15g，出处 distilled/方剂库-经方组成.md）。

用法：
  1) 单味剂量换算：
       python3 scripts/dose_convert.py "半夏 半斤"
       python3 scripts/dose_convert.py "附子 一枚"
       python3 scripts/dose_convert.py "黄芩 一两半"
  2) 批量解析经方组成库并输出克数表：
       python3 scripts/dose_convert.py --batch \
           distilled/方剂库-经方组成.md \
           distilled/03-金匮/方剂剂量换算.md

汉制换算（库内标准）：
  1两 = 15g        1斤 = 8两 = 120g   半=0.5  二分=0.25
  枚(参考)：附子≈15g/枚，余枚数保留"X枚"并标注（库内真武汤炮附子1枚→15g）
  升/合/铢/分/个/尺/茎：近似或保留数量，均标注假设——临床以医生为准。
"""
import re, sys

# ---- 单位换算表 ----
LIANG = 15.0          # 1两 = 15g (库内标准)
JIN   = LIANG * 8     # 1斤 = 8两 = 120g (汉制)
MEI_REF = {"附子": 15.0, "山茱萸": 15.0}   # 枚→克参考值（库内真武汤附子1枚=15g）

# 中文数字 -> 浮点
CN = {'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,
      '七':7,'八':8,'九':9,'十':10,'百':100}

def cn_to_num(s):
    """把'一两半''十二''半斤'里的数字部分转成浮点。"""
    s = s.strip()
    half = 0.0
    if '半' in s:
        half = 0.5; s = s.replace('半', '')
    s = s.replace('两', '二')  # '两'作数词时=2
    total, cur = 0, 0
    for ch in s:
        v = CN.get(ch)
        if v is None: continue
        if v >= 10:
            if cur == 0: cur = 1   # "十"单独=10（处理"十几"）
            total = (total + cur) * v; cur = 0
        else:
            cur += v
    return total + cur + half

def convert(dose_str, name=''):
    """把单段剂量文本(如'半斤(洗)''一两半''一枚(炮)')转成 (克数, 说明)。"""
    s = dose_str.strip()
    combined = f"{name} {s}" if name else s   # 枚参考值需结合药材名
    clean = re.sub(r'[（(].*?[）)]', '', s).strip()   # 去掉炮制括号
    unit_map = [('斤', JIN), ('两', LIANG), ('钱', LIANG / 10), ('分', None)]
    for unit, factor in unit_map:
        if unit in clean:
            num_part = re.sub(re.escape(unit), '', clean).strip()
            if factor is None:  # 分=重量比(等分)，不转克
                return (None, f"{s}（分=比例，非绝对剂量）")
            n = cn_to_num(num_part)
            g = round(n * factor, 1)
            return (g, f"{s} → {n}{unit}×{int(factor)}g={g}g")
    for unit in ('枚', '个', '茎', '片'):
        if unit in clean:
            num_part = re.sub(re.escape(unit), '', clean).strip()
            n = cn_to_num(num_part)
            hint = next((k for k in MEI_REF if k in combined), None)
            if hint and unit == '枚':
                g = round(MEI_REF[hint] * n, 1)
                return (g, f"{s} → {n}×{MEI_REF[hint]}g={g}g（枚参考值）")
            return (None, f"{s} → {int(n)}{unit}（枚/个按物而异，保留数量）")
    for unit in ('升', '合'):
        if unit in clean:
            num_part = re.sub(re.escape(unit), '', clean).strip()
            n = cn_to_num(num_part)
            g = round(n * 50, 1)  # 近似：1升≈50g（临床以医生为准）
            return (g, f"{s} → {n}×~50g≈{g}g（升近似）")
    if clean in ('等分',):
        return (None, f"{s}（各取等量，无绝对剂量）")
    if '如' in s or '原书' in s or '手掌' in s:
        return (None, f"{s}（形态量词/见原书，按临床）")
    return (None, f"{s}（无可识别单位，保留原文）")

def parse_formula_line(line):
    """从经方组成库一行解析出 [方名, 来源]；返回 None 若非数据行。"""
    if not line.startswith('|') or '方名' in line[:6]:
        return None
    parts = [p.strip() for p in line.strip('|').split('|')]
    if len(parts) < 3: return None
    # 跳过分隔行 |---|---|---|
    if all(set(p.strip()) <= set('-:') for p in parts): return None
    name, src = parts[0], parts[1]
    comp = parts[2]
    return name, src, comp

def extract_doses(comp):
    """从组成字段提取 [(药材, 剂量文本)]。"""
    items = re.findall(r'\*\*([^*]+?)\*\*\s*(.+?)(?=；|$)', comp)
    out = []
    for name, dose in items:
        name = name.strip()
        # 过滤掉"剂量见原书""以重用到"等噪声
        if '剂量见原书' in dose or re.match(r'^[（(]', dose): continue
        if len(name) < 2 or any(c in name for c in '的是的了和与而'): 
            # 粗略过滤，保留含药材特征的
            pass
        out.append((name, dose.strip()))
    return out

def batch(in_path, out_path):
    src = open(in_path, encoding='utf-8').read()
    lines = [l for l in src.split('\n') if l.startswith('|')]
    rows = []
    for line in lines:
        parsed = parse_formula_line(line)
        if not parsed: continue
        name, comp = parsed[0], parsed[2]
        doses = extract_doses(comp)
        converted = []
        for nm, ds in doses:
            g, note = convert(ds, nm)
            converted.append((nm, ds, g, note))
        rows.append((name, converted))
    # 写表
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("# 经方剂量换算（古制 → 现代克数）\n\n")
        f.write("> 汉制换算：1两≈15g、1斤=8两=120g；枚/升等近似，临床以医生为准。\n")
        f.write(f"> 来源：`distilled/方剂库-经方组成.md` → 本文件。共 {len(rows)} 首方。\n\n")
        for name, conv in rows:
            f.write(f"## {name}\n")
            f.write("| 药材 | 古剂量 | 克数 | 换算说明 |\n|---|---|---|---|\n")
            for nm, ds, g, note in conv:
                f.write(f"| {nm} | {ds} | {g if g is not None else '—'} | {note} |\n")
            f.write("\n")
    print(f"[dose_convert] 已转换 {len(rows)} 首方 → {out_path}")

if __name__ == '__main__':
    args = sys.argv[1:]
    if '--batch' in args:
        i = args.index('--batch')
        inp, outp = args[i+1], args[i+2]
        batch(inp, outp)
    else:
        for arg in args:
            g, note = convert(arg)
            print(f"{arg}  →  {note}")
