#!/usr/bin/env python3
"""Emit candidate acupoint names from the 针灸 source as a whitelist.

Usage:
    python3 scripts/cand_to_whitelist.py "text/倪海厦人纪系列之针灸教程.txt" > scripts/acupoint_whitelist.txt

Strategy: take 2–4 char CJK tokens that sit next to a five-shu role word
(井荣俞经合原络郄募) or a channel/syndrome name (太阳/少阴…经/任/督), strip
trailing punctuation/suffixes, dedup keeping first. This is the curated base
from which `acupoint_extract.py` matches only names present in the source.
"""
import re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "text/倪海厦人纪系列之针灸教程.txt"
text = open(SRC, encoding='utf-8').read()

# fold full-width ASCII / space; strip 第N页 headers
def norm(s):
    s = re.sub(r'[！-～]', lambda m: chr(ord(m.group(0))-0xFEE0), s)
    s = s.replace('　', ' ')
    return re.sub(r'(第|.*页)\d*[页]', '', s)
text = norm(text)

ROLES = '井荣俞经合原络郄募'
CH = re.compile(r'(手|足)(太|少|明)[^，。；\n]{0,6}(经|脉)')   # 手太阴肺经 …
ROLEM = re.compile(r'([一-鿿]{2,4})[的地之]?([%s])穴' % ROLES)    # 尺泽合穴 / 肺经井穴
POINTS = set()

# role-anchored: <2–4char CJK> + (井荣俞经合原络郄) + 穴
for m in ROLEM.finditer(text):
    name = m.group(1)
    if 2 <= len(name) <= 4 and re.fullmatch(r'[一-鿿]+', name):
        # drop obvious non-points (channel/syndrome names)
        if any(k in name for k in ('太阳','少阳','阳明','太阴','少阴','厥阴','经','脉')):
            continue
        if len(name) >= 3 and name[-1] in ROLES:   # "肺经" style trailing role char
            continue
        POINTS.add(name)

# channel-name head points (肺经/大肠经/…经) — first named point per channel line if any
for c in CH.finditer(text):
    head = c.group(0).replace('经','').replace('脉','')
    if 2 <= len(head) <= 3 and re.fullmatch(r'[一-鿿]+', head):
        POINTS.add(head)

# emit deduped, sorted by length then name, one per line
out = sorted((p for p in POINTS if re.fullmatch(r'[一-鿿]{2,4}', p)),
             key=lambda x: (len(x), x))
sys.stdout.write('\n'.join(out) + '\n')
print('[%d candidates]' % len(out), file=sys.stderr)
