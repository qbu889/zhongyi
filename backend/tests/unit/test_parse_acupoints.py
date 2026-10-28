from app.etl import parse_acupoints

TWELVE = """
## 四、各经详细穴位(按循行顺序,仅收原文出现者)

### 手太阴肺经(出现 11 穴)

| 穴位 | 角色 | 原文主治摘录 |
|---|---|---|
| 中府 | 募穴 |  |
| 云门 | — |  |
| 尺泽 | 合穴 | 咳唾,上气 |
| 孔最 | 郄穴 |  |
| 列缺 | 络穴 |  |
| 经渠 | 经穴 |  |
| 太渊 | 输穴·原穴 |  |
| 少商 | 井穴 |  |

### 手阳明大肠经(出现 17 穴)

| 穴位 | 角色 | 原文主治摘录 |
|---|---|---|
| 商阳 | 井穴 |  |
| 合谷 | 原穴 |  |

## 五、常用奇穴(经外奇穴)

| 穴位 | 定位/主治 |
|---|---|
| 十宣 | 十指尖端,急救放血 |
| 安眠 | 治失眠 |
"""

SYMPTOM = """
## 一、编号临床方(原文目录级)

| # | 病症/主题 | 取穴 | 原文摘录 |
|---|---|---|---|
| 1 | 全身脉络之主管 | 大包 | 大包穴（...） |

## 二、按症状归类常用穴

### 头痛/头项强痛

| 穴位 | 主治 | 原文摘录 |
|---|---|---|
| 风池 | 头痛·项强 | 风池为头痛必用 |
| 后溪 | 项强 | 申脉别通 |

### 咳嗽/喘

| 穴位 | 主治 | 原文摘录 |
|---|---|---|
| 列缺 | 咳嗽 | 列缺任脉行肺系 |
"""


def test_parse_roles_splits_multi_and_drops_placeholder():
    recs = {r.name: r for r in parse_acupoints.parse_acupoints(TWELVE)}
    assert recs["太渊"].roles == ["输", "原"]      # 一穴双角色（输穴·原穴）
    assert recs["中府"].roles == ["募"]
    assert recs["云门"].roles == []                # `—` 是占位符，不是角色
    assert recs["尺泽"].actions == "咳唾,上气"


def test_parse_meridian_from_section():
    by_name = {r.name: r for r in parse_acupoints.parse_acupoints(TWELVE)}
    assert by_name["列缺"].meridian == "手太阴肺经"
    assert by_name["合谷"].meridian == "手阳明大肠经"



def test_extra_points_are_flagged_not_dropped():
    extras = {r.name: r for r in parse_acupoints.parse_acupoints(TWELVE)}
    assert extras["十宣"].kind == "奇穴" and extras["十宣"].meridian is None
    assert extras["少商"].kind == "经穴"


def test_parse_symptoms_keeps_section_as_theme():
    syms = parse_acupoints.parse_symptoms(SYMPTOM)
    pairs = {(s.symptom, s.point) for s in syms}
    assert ("全身脉络之主管", "大包") in pairs
    assert ("头痛/头项强痛", "风池") in pairs      # 二、按症状归类以 ### 小节为主题
    assert ("咳嗽/喘", "列缺") in pairs


def test_real_acupoint_corpus_counts():
    from app.config import settings
    text = (settings.distilled_dir / "05-针灸" / "十二经穴位库.md").read_text(encoding="utf-8")
    recs = parse_acupoints.parse_acupoints(text)
    经穴 = [r for r in recs if r.kind == "经穴"]
    奇穴 = [r for r in recs if r.kind == "奇穴"]
    # 四节 335 行，与各小节「出现 N 穴」声明合计完全一致——这是语料自身的 integrity 校验
    assert len(经穴) == 335
    assert len({r.name for r in 经穴}) == 335
    assert len(奇穴) == 11 and len(recs) == 346
    roles = {role for r in recs for role in r.roles}
    assert {"井", "荥", "输", "经", "合", "原", "络", "郄", "募"} <= roles


def test_real_symptom_corpus_and_the_cough_gap():
    from app.config import settings
    text = (settings.distilled_dir / "05-针灸" / "针灸治症取穴.md").read_text(encoding="utf-8")
    syms = parse_acupoints.parse_symptoms(text)
    # 一(3) + 二(41 行→43 条，含一穴多主题) + 三(8 行八脉交会) = 54
    assert len(syms) == 54
    # PIPELINE §4.4 的硬事实：治症取穴里没有咳/喘专节 → D 类必须走特例分支
    assert not [s for s in syms if s.symptom in ("咳", "喘", "咳嗽", "气喘")]
