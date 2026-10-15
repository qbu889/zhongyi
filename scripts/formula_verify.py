#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经方组成(古制) vs 经典配方(现成克数版) 交叉校验。

用法：
  python3 scripts/formula_verify.py \
      distilled/方剂库-经方组成.md \
      distilled/方剂库-经典配方.md \
      distilled/03-金匮/方剂交叉校验.md

背景说明：
  - 经方组成库 = 张仲景原书汉制剂量（大，如半夏125g）
  - 经典配方库 = 现代临床克数版（小，如半夏15g），且同名方常有多行(多版本)
  - 故"剂量偏差>30%"多为两套体系差异，非错误；重点看【药材差异】。

逻辑：
  1. 两库同名方 → 归一化药材名(去炮制前缀+同义词)后比较集合。
  2. 对每个共有方，在经典配方所有版本中选取**最接近经方组成剂量**的版本为基准对比。
  3. 输出:药材差异 / 剂量偏差>50%的项 + 仅单库存在的方。

汉制换算: 1两=15g, 1斤=8两=120g (来源 distilled/方剂库-经方组成.md)。
"""
import re, sys

JIN = 120.0; LIANG = 15.0
CN = {'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,
      '七':7,'八':8,'九':9,'十':10,'百':100}

# 药材同义词归一化
SYNONYM = {'白芍':'芍药','赤芍':'芍药','生地黄':'地黄','干地黄':'地黄',
           '炙甘草':'甘草','甘草':'甘草','川芎':'川芎','制附子':'附子'}

def cn_to_num(s):
    s = s.strip(); half = 0.0
    if '半' in s: half = 0.5; s = s.replace('半', '')
    s = s.replace('两', '二')
    total, cur = 0, 0
    for ch in s:
        v = CN.get(ch)
        if v is None: continue
        if v >= 10:
            if cur == 0: cur = 1
            total = (total + cur) * v; cur = 0
        else: cur += v
    return total + cur + half

def ancient_to_g(dose):
    s = re.sub(r'[（(].*?[）)]', '', dose).strip()
    for unit, factor in [('斤', JIN), ('两', LIANG)]:
        if unit in s:
            n = cn_to_num(re.sub(re.escape(unit), '', s))
            return round(n * factor, 1)
    return None

def normalize(name):
    name = re.sub(r'^(炮|炙|炒|洗|去皮|劈|擘|去足|去节|研)', '', name.strip())
    name = re.sub(r'[（(].*?[）)]', '', name).strip()
    return SYNONYM.get(name, name)

def parse_ancient(path):
    """经方组成库 -> {方名: {药材: 古剂量文本}}"""
    src = open(path, encoding='utf-8').read()
    out = {}
    for ln in src.split('\n'):
        if not ln.startswith('|') or '方名' in ln[:6]: continue
        parts = [p.strip() for p in ln.strip('|').split('|')]
        if len(parts) < 3: continue
        name, comp = parts[0], parts[2]
        herbs = {}
        for nm, dose in re.findall(r'\*\*([^*]+?)\*\*\s*(.+?)(?=；|$)', comp):
            nrm = normalize(nm)
            if '剂量见原书' in dose or re.match(r'^[（(]', dose): continue
            herbs[nrm] = dose.strip()
        out[name] = herbs
    return out

def parse_gram(path):
    """经典配方库 -> {方名: [版本列表]}，每版本={药材: 克数}"""
    src = open(path, encoding='utf-8').read()
    out = {}
    for ln in src.split('\n'):
        if not ln.startswith('|') or '# |' in ln[:6]: continue
        parts = [p.strip() for p in ln.strip('|').split('|')]
        if len(parts) < 3: continue
        name_field, comp = parts[1], parts[2]
        m = re.search(r'([一-鿿]{2,8}汤方?|瓜蒌薤白.*半夏汤)', name_field)
        base = m.group(1) if m else name_field.split('·')[-1].strip()
        # 按逗号分割，精确提取 [药材][数字/半]
        herbs = {}
        for seg in comp.split(','):
            mm = re.match(r'\s*([一-鿿]{2,4})\s*(半|[0-9]+(?:\.[0-9]+)?)', seg)
            if mm:
                nm = normalize(mm.group(1))
                num = cn_to_num(mm.group(2)) if mm.group(2) == '半' else float(mm.group(2))
                herbs[nm] = round(num, 1)
        if herbs: out.setdefault(base, []).append(herbs)
    return out

def best_match(anc_herbs, gram_versions):
    """在经典配方版本中选药材集合最接近的作为对比基准。"""
    a_keys = set(anc_herbs)
    best, best_score = None, -1
    for ver in gram_versions:
        g_keys = set(ver)
        inter = len(a_keys & g_keys)
        union = len(a_keys | g_keys) or 1
        score = inter / union   # Jaccard相似度
        if score > best_score:
            best, best_score = ver, score
    return best

def verify(a_path, g_path):
    anc = parse_ancient(a_path); gram = parse_gram(g_path)
    common = set(anc) & set(gram)
    only_a = set(anc) - set(gram); only_g = set(gram) - set(anc)
    diffs = []
    for name in sorted(common):
        a_h, versions = anc[name], gram[name]
        base = best_match(a_h, versions) or {}
        a_keys, g_keys = set(a_h), set(base)
        miss_in_g = a_keys - g_keys
        miss_in_a = g_keys - a_keys
        if miss_in_g or miss_in_a:
            diffs.append((name, '药材差异', f'古制有/经典无:{sorted(miss_in_g)}; 经典有/古制无:{sorted(miss_in_a)}'))
        for herb in sorted(a_keys & g_keys):
            ag = ancient_to_g(a_h[herb])
            gg = base.get(herb)
            if ag is None or gg is None: continue
            dev = abs(ag / gg - 1) * 100
            if dev > 50:
                diffs.append((name, '剂量偏差>50%', f'{herb}: 古制{ag}g vs 经典{gg}g (偏差{dev:.0f}%)'))
    return common, only_a, only_g, diffs

def write_report(common, only_a, only_g, diffs, out_path):
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("# 经方交叉校验（古制 vs 现成克数版）\n\n")
        f.write("> 口径：经方组成按 1两≈15g 转克数；经典配方同名方取**最接近版本**对比。")
        f.write("药材名去炮制前缀+同义词归一化。\n")
        f.write("> ⚠️ 两套剂量体系不同（汉制原书大剂量 vs 现代临床小剂量），剂量偏差>50%多为正常，重点看【药材差异】。\n\n")
        f.write(f"- 两库共有方：**{len(common)}** 首\n")
        f.write(f"- 仅经方组成有：**{len(only_a)}**；仅经典配方有：**{len(only_g)}**\n")
        f.write(f"- 差异项（药材/剂量>50%）：**{len(diffs)}**\n\n")
        if diffs:
            f.write("## 差异明细\n")
            for name, kind, detail in diffs:
                f.write(f"- **{name}** [{kind}]：{detail}\n")
        else:
            f.write("## 无显著差异\n")
    print(f"[formula_verify] 共有{len(common)}首, 差异{len(diffs)}项 → {out_path}")

if __name__ == '__main__':
    a, g = sys.argv[1], sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else 'distilled/03-金匮/方剂交叉校验.md'
    common, only_a, only_g, diffs = verify(a, g)
    write_report(common, only_a, only_g, diffs, out)
