import re, sys

def norm(s):
    out=[]
    for ch in s:
        o=ord(ch)
        if 0xFF01<=o<=0xFF5E: out.append(chr(o-0xFEE0))
        elif o==0x3000: out.append(' ')
        else: out.append(ch)
    return ''.join(out)

# 六经传变顺序(有序列表)——用 set 迭代会随进程哈希种子改变输出段序,导致不可复现。
SECTIONS=['太阳','阳明','少阳','太阴','少阴','厥阴']
# only quoted classical formula names: 「桂枝汤」「承气汤」
FORMULA=re.compile(r'「([一-鿿]{2,8}(汤|方|丸|散))」')

def clause_around(line, idx):
    s=max(0,idx-40); e=min(len(line),idx+45)
    return line[s:e].strip()

def index(path):
    src=norm(open(path,encoding='utf-8').read())
    result={s:[] for s in SECTIONS}
    cur=None
    for ln in src.split('\n'):
        h=re.search(r'辨(太阳|阳明|太阴|少阳|少阴|厥阴)病脉证',ln)
        if h: cur=h.group(1)
        if cur and ln.strip()!='':
            for fm in FORMULA.finditer(ln):
                name=fm.group(1)
                result[cur].append((name, clause_around(ln.strip(), fm.start()))[:60])
    out=[]
    for s in SECTIONS:
        d={}
        for name,ctx in result[s]:
            if name not in d: d[name]=ctx
        out.append((s,d))
    return out

if __name__=='__main__':
    out=None; args=sys.argv[1:]
    while args and args[0].startswith('-o'): out=args[1]; args=args[2:]
    if out:
        L=['# 《伤寒论》六经经方库(倪海厦人纪版) — 原文节选\n']
        for path in args:
            L.append('\n## %s\n'%path.split('/')[-1])
            for s,d in index(path):
                L.append('### %s病\n'%s)
                for i,(name,ctx) in enumerate(sorted(d.items()),1):
                    L.append('| %d | 「%s」 | %s |\n'%(i,name,ctx))
        open(out,'w',encoding='utf-8').write('\n'.join(L))
        print('WROTE',out)
    else:
        for path in args:
            print('### FILE %s'%path.split('/')[-1])
            for s,d in index(path):
                print('\n== %s病脉证 ==  (共%d方)'%(s,len(d)))
