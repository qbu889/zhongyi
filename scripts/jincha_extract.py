import re,sys
def norm(s):
    o=""
    for ch in s:
        n=ord(ch)
        if 0xFF01<=n<=0xFF5E: o+=chr(n-0xFEE0)
        elif n==0x3000: o+=" "
        else: o+=ch
    return o
F=re.compile(r"「?([一-鿿]{2,8}(汤|丸|散))方」?(?![.～—]*\d)")
def toc(ln): return bool(re.search(r"[.～—]{2,}\s*\d", ln))
# 口语前缀会污染篇名:如"接下来呢，我们介绍痰饮咳嗽病脉证并治第十二"会被误抓成
# "辨我们介绍痰饮咳嗽病"。剥离这类前缀还原真实篇名(第十九/第九篇等)。
PROSE_PREFIX=re.compile(r'^(?:我们|接下来|然后|大家|所谓|下面)?(?:介绍|讲解|说说?|提到|回到)')
# 两版本对同一篇措辞不同 → 归一到规范篇名,避免一章被拆成两段。
CANON={'手指臂肿转筋狐疝蚘虫病':'手指臂肿转筋阴狐疝蚘虫病',
       '指臂肿转筋阴狐疝蚘虫病':'手指臂肿转筋阴狐疝蚘虫病'}
def sec(ln):
    if toc(ln): return None
    m=re.search(r"([一-鿿]{2,10}病)(?:脉证治|脉证并治)",ln)
    if not m: return None
    name=PROSE_PREFIX.sub('',m.group(1))
    if len(name)<3 or not name.endswith('病'):   # 剥离后须仍是合法篇名
        return None
    return CANON.get(name,name)
base="/Users/linziwang/PycharmProjects/zhongyi/text/"
files=[base+"倪海厦人纪系列之金匮要略.txt", base+"《金匮要略》——倪海厦人纪教程简体整理稿.txt"]
note=norm("".join(open(f,encoding="utf-8").read() for f in files))
note=re.sub(r"\n第[0-9]+页\n","\n",note)
cur="概论"; L=["# 《金匮要略》方剂库(倪海厦人纪版,两版本合并) — 原文节选","> 按《金匮》二十二篇及倪氏文中'辨XX病'分段,列出经方名与主证要点。"]
for ln in note.split("\n"):
    if toc(ln): continue
    sd=sec(ln)
    if sd: cur="辨"+sd+"脉证治"
    for fm in F.finditer(ln):
        name=fm.group(1).rstrip("方"); i=fm.start(); s2=max(0,i-42); e3=min(len(ln),i+48)
        L.append("| %s | 「%s」 | %s |"%(cur,name,ln[s2:e3].strip()))
open(sys.argv[1],"w",encoding="utf-8").write("\n".join(L))
print("方剂条数:",len(L)-3)
