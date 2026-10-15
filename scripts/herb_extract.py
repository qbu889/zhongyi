import re, sys

def norm(s):
    out=[]
    for ch in s:
        o=ord(ch)
        if 0xFF01<=o<=0xFF5E: out.append(chr(o-0xFEE0))
        elif o==0x3000: out.append(' ')
        else: out.append(ch)
    return ''.join(out)

# herb heading: "一、丹砂" / "二六三、青琅玕。" / "二、诃黎勒（诃子）" / "三、红花——本经无记载"
# 药名=1~4个汉字;其后须是边界(空白/行尾/括号/破折号U+2014/句读)。
# 关键:真药注用 U+2014(——),而章节头"八、六淫主治──…"用 U+2500(──),据此区分,避免把概念章节当成药。
HEADING=re.compile(r'^\s*(?:\d+|[一二三四五六七八九十百千〇零两○Ｏ]+)[、.．]\s*《?([（(]?[一-鿿][）)]?[一-鿿]{0,4})(?=\s|$|（|\(|—|[。．.])')
# field markers "【气味】value up to next 【" ; value may span lines (multi-line 主治)
FMARK=re.compile(r'【(本经原文|气味|主治|产地|用量|禁忌|药征|别录|甄藏|权|隐娘|志|孟诜|居敬)】', re.S)

# OCR异体/别名 → 规范名:不同版本对同一味药用字不同,若不去重会各占一行。
# (最子=栀子、马儀=马刀,内容逐字相同,见《神农本草经》第208/335条 vs 规范条目)
ALIAS={'最子':'栀子','马儀':'马刀'}

def parse(path):
    src=norm(open(path,encoding='utf-8').read())
    src=re.sub(r'\n第[0-9]+页\n','\n',src)
    entries=[]; cur=None
    for ln in src.split('\n'):
        if '药物索引' in ln or re.search(r'[·．.]{5,}\s*\d+\s*$', ln):
            # 索引页/页码行，停止正文抽取
            if cur is not None:
                # 清掉当前条目里被追加的索引残留
                for k in list(cur['fields'].keys()):
                    cur['fields'][k]=re.sub(r'\s*V100415\.01.*$','',cur['fields'][k],flags=re.S).strip()
            cur=None
            continue
        m=HEADING.search(ln)
        if m:
            name=re.sub(r'[。．.、,，;；:：\s]+$','',m.group(1))   # 去尾部标点(如"青琅玕。")
            name=ALIAS.get(name,name)                              # OCR异体归一(最子→栀子等)
            if cur is None or name!=cur['name']:
                entries.append({'name':name,'fields':{}}); cur=entries[-1]
            continue
        if cur is None: continue
        fv=FIELD_RE.search(ln)
        if not fv:
            keys=list(cur['fields'].keys())
            if keys: cur['fields'][keys[-1]]+=' '+ln.strip()
            continue
        k,v=fv.group(1),fv.group(2).strip()
        if k not in cur['fields']: cur['fields'][k]=v
    return entries

# rebuild FIELD_RE to capture value lazily until next field marker (like FMARK) or end of entry
def build_field_re():
    keys='本经原文|气味|主治|产地|用量|禁忌|药征|别录|甄藏|权|隐娘|志|孟诜|居敬'
    return re.compile(r'【(%s)】(.*?)(?=FMARK_PLACEHOLDER|\Z)' % keys, re.S).pattern
FIELD_RE=re.compile(build_field_re().replace('FMARK_PLACEHOLDER', r'【(本经原文|气味|主治|产地|用量|禁忌|药征|别录|甄藏|权|隐娘|志|孟诜|居敬)】'))

def render_all(files):
    merged={}; order=[]; skip={'五味','五色','六气','脏气法时','序'}
    for path in files:
        for e in parse(path):
            n=e['name']
            if n in skip: continue
            if n not in merged: merged[n]=dict(e['fields']); order.append(n)
            else:
                for k,v in e['fields'].items():
                    if not merged[n].get(k): merged[n][k]=v
    print('# 中药库(《神农本草经》三版本合并) — 共 %d 味' % len(merged))
    print()
    # 常用现代名→本经古名对照(搜不到现代名时按此查);随脚本一并产出,保证重跑可复现。
    print('> **常用现代名 → 本经古名对照**（搜不到现代名时按此查）：')
    print('> 柴胡=茈胡(29) · 桂枝=牡桂(89) · 肉桂=菌桂(90) · 山药=署豫(19) · 菖蒲=昌蒲(10) · 川芎=芎䓖(25) · 玉竹=葳蕤(15) · 天花粉=瓜蒌根(64) · 瓜蒌=瓜蒌实(64) · 陈皮=橘柚(46) · 桂心/官桂=牡桂/菌桂(89/90)')
    print()
    print('| # | 药名 | 气味 | 功效·主治 | 产地 | 用量/禁忌 |')
    print('|---|---|---|---|---|---|')
    for i,n in enumerate(order,1):
        f=merged[n]
        def clean(v): return re.sub(r'\s+',' ',(v or '—')).strip()
        dose=clean(f.get("用量","")); contra=clean(f.get("禁忌",""))
        note=("·禁忌:"+contra) if (dose and contra) else contra
        print('| %d | %s | %s | %s | %s | %s·用量:%s |' % (i,n,clean(f.get("气味","—")),clean(f.get("主治",f.get("本经原文","—"))),clean(f.get("产地","—")),note,dose))

if __name__=='__main__':
    render_all(sys.argv[1:])
