#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从伤寒/金匮原文抽取每首方的药味+剂量（v2：直接在组成段上全局正则匹配）。"""
import re, sys, json

# 药名候选（常见经方药，2-4字）
HERB_CHARS = r'[\u4e00-\u9fa5]'
# 剂量：数字+单位
DOSE = r'([一二三四五六七八九十百半\d\.]+)\s*(两|斤|枚|个|升|合|尺|寸|分|铢|粒|把|握|片|挺|茎|箇|株|斤许)'

def extract_formulas(txt_path):
    text = open(txt_path, encoding="utf-8").read()
    lines = text.splitlines()
    formulas = {}
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        m = re.match(r'^([\u4e00-\u9fa5]{2,12})(汤|丸|散|丹|膏|饮)\s*方$', ln)
        if not m:
            i += 1
            continue
        fname = m.group(1) + m.group(2)
        # 检查是否交叉引用（如"小半夏汤方（见痰饮）"）
        full_line = ln
        if '见' in full_line and '篇' in full_line:
            i += 1; continue
        if '见' in full_line and re.search(r'见[一-龥]+', full_line):
            # 方名行带括号说明，组成在别处
            i += 1; continue
        # 往下读组成段
        seg_lines = []
        j = i + 1
        while j < len(lines) and j < i + 25:
            seg = lines[j].strip()
            if not seg:
                j += 1; continue
            # 组成段的真正结尾是"上X味/右X味"
            if re.match(r'^[右上]\s*[一二三四五六七八九十百\d]+\s*(味|物|株|个|枚)', seg):
                break
            # 遇到讲解标志词就停
            if any(k in seg for k in ['这里讲', '就是说', '诸位到', '我们常常', '张仲景为', '这个时候', '所以我们', '如果病人', '第一：', '第二：']):
                break
            # 煎服法行跳过（不读入组成）
            if any(k in seg for k in ['以水', '煮取', '去滓', '温服', '空心服', '日三服', '日再服', '日二服', '分温三服', '分温再服']):
                j += 1; continue
            seg_lines.append(seg)
            j += 1

        # 第一遍：在整段里找所有 "药名+剂量" 的位置
        # 同时记录每行内容
        herbs = []  # (name, dose, process)
        pending_named = []  # 单列成行的药名（等"各"字补剂量）

        for seg in seg_lines:
            # 找这一行里所有"药名+剂量"
            pattern = re.compile(rf'([\u4e00-\u9fa5]{{2,4}}?)([一二三四五六七八九十百半\d\.]+)\s*(两|斤|枚|个|升|合|尺|寸|分|铢|粒|把|握|片|挺|茎|箇|株)')
            matches = list(pattern.finditer(seg))
            if matches:
                # 这一行有剂量
                for idx, mm in enumerate(matches):
                    h = mm.group(1)
                    if h[0] in '右上水煮取温分再三日若将将先更加此当用慎忌':
                        continue
                    # 药名不能含"方"字（避免把"XX方"误识别成药名）
                    if '方' in h:
                        continue
                    # 药名不能完全等于方名（如"桂枝汤"不能作为自己的药味）
                    if h == fname:
                        continue
                    dose = mm.group(2) + mm.group(3)
                    proc_end = matches[idx+1].start() if idx+1 < len(matches) else len(seg)
                    proc = seg[mm.end():proc_end].strip()
                    if any(u in proc for u in ['两','斤','枚','升','合','铢','个']):
                        proc = ''
                    # 检查是否含"各"字：说明前面 pending_named 共享这个剂量
                    if '各' in proc or seg.count('各') > 0:
                        # 前面的 pending_named 都用这个剂量
                        for pn in pending_named:
                            herbs.append((pn, dose, ''))
                        pending_named = []
                    herbs.append((h, dose, proc))
            else:
                # 这一行没有剂量，可能是单列药名
                clean = seg.strip('，,。 \t')
                # 逗号后全是炮制描述，去掉
                clean = re.split(r'[，,]', clean)[0]
                # 去掉常见炮制后缀
                clean = re.sub(r'(炙|洗|熬|去节|去皮|破|水渍|炙干|切|劈|碎|绵裹|黑|炮)$', '', clean)
                clean = re.sub(r'^[，,。\s]+', '', clean)
                if re.match(r'^[\u4e00-\u9fa5]{2,6}$', clean) and clean[0] not in '右上水煮取温分再三日若将将先更加此当用慎忌':
                    # 过滤页脚/页眉
                    if clean in {'勤求古訓', '博采眾方', '倪注', '倪海厦', '人紀', '定稿'}:
                        continue
                    pending_named.append(clean)

        # 把没匹配上的 pending_named 也加进来（剂量未知）
        for pn in pending_named:
            herbs.append((pn, '（剂量见原书）', ''))

        if herbs:
            # 清洗 + 去重
            cleaned = []
            # 常见非药名词（OCR噪声）
            noise_words = {
                '小便','大便','上右','右一','右二','右三','上一','上二','上三',
                '话就是','如鸡子','月八日','月七日','手指大','草如指',
                '别做脂','一本作','严重的用','肉桂用','汤加桂枝','四两','煎去',
                '出乌头','沸草','葱十','去皮破','去皮','去节','一本','次方',
                '牡蛎用','大者','去皮破八片','冬去心','猪苓去皮','麻黄去节',
            }
            # 别名归一（OCR/古今字）
            alias = {
                '白朮': '白术', '桅子': '栀子', '桂技': '桂枝',
                '牡丹': '牡丹皮', '胶饴': '饴糖', '麻仁': '麻子仁',
                '生石膏': '石膏', '芎藭': '川芎', '葳蕤': '玉竹',
                '赤石脂': '赤石脂', '代赭石': '代赭',
            }
            # 炮制字（不能出现在药名里）
            process_chars = set('炙洗熬去劈切碎炮渍')
            seen = set()
            for h, d, p in herbs:
                # 1. 去掉末尾的"各"
                h = h.rstrip('各')
                # 2. 去掉"方"字结尾
                if h.endswith('方'):
                    h = h[:-1]
                # 3. 别名归一
                h = alias.get(h, h)
                # 4. 过滤噪声
                if h in noise_words: continue
                if '方' in h: continue
                if h == fname: continue
                if len(h) < 2: continue
                # 5. 药名不能以炮制字结尾
                if h[-1] in process_chars: continue
                # 6. 药名里不能包含"各/去/采/大者"
                if '各' in h or '去' in h or '采' in h or '大者' in h: continue
                # 7. 去重
                if h in seen: continue
                seen.add(h)
                cleaned.append((h, d, p))
            formulas[fname] = cleaned
        i = j
    return formulas

if __name__ == "__main__":
    for path in sys.argv[1:]:
        fs = extract_formulas(path)
        print(f"\n=== {path} ===")
        print(f"共抽取 {len(fs)} 首方")
        for name in ['桂枝汤', '麻黄汤', '小柴胡汤', '白虎汤', '四逆汤', '葛根汤', '五苓散', '炙甘草汤', '大承气汤']:
            if name in fs:
                print(f"\n【{name}】")
                for h, d, p in fs[name]:
                    extra = f" ({p})" if p else ""
                    print(f"  {h} {d}{extra}")
