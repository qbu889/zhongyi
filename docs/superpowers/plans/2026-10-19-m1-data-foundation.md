# M1 数据底座 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `distilled/` 蒸馏库通过 ETL 解析入 PostgreSQL+pgvector，建成结构化表（方/药/穴/案/框架）与向量切片，并提供一键重建索引（FR-12）与数据质量报告（FR-13）API。

**Architecture:** 后端 Python FastAPI，直接 `importlib` 复用仓库内 `scripts/search.py`（表格解析/norm）、`scripts/dose_convert.py`（古制→克）、`scripts/formula_verify.py`（交叉校验）三个纯 stdlib 脚本作为 ETL 内核；SQLAlchemy 2.x 建模，pgvector 存切片向量（BGE-M3，1024 维）；一条 reindex 流水线串起「解析→切片→embedding→入库→校验」，索引版本绑定 `distilled/` 的 git commit hash。

**Tech Stack:** Python 3.11 · FastAPI · SQLAlchemy 2.x · psycopg3 · pgvector · sentence-transformers (BAAI/bge-m3) · pytest · Docker Compose（Postgres 16 + pgvector）。

**Spec:** `docs/需求文档-RAG系统.md`（§5.1 选型、§5.3 数据模型、§5.4 API、§8 M1、FR-12/13/14、NFR-6）。本计划实现 M1，M2（检索+CRUD）与 M3（编排链）另立计划。

## Global Constraints

> **2026-10-28 修订**：原计划基于 PRD §5.3 单层 `formula` 模型；现 PRD **§5.6 已定稿三层非对称模型**（D6/D7/D8），
> Task 2/5/6 的 Interfaces 已按 §5.6 重写，**其中保留的旧代码块若与 Interfaces 冲突，一律以 Interfaces 为准**。
> 同日实测的环境与脚本缺陷已并入下方约束。

- Python 版本 **3.11**（sentence-transformers/torch 要求）。实测宿主默认 `python3` = **3.13.3**（不是原写的 3.9.6），
  `3.11` 在 `/opt/homebrew/bin/python3.11`；venv 显式用它创建，禁止依赖 `python3` 解析结果。
- 数据库 **PostgreSQL 16 + pgvector**。**2026-10-28 决策**：本机已有 Homebrew `postgresql@16` 16.15 且运行于 `5432`，
  **本地开发直接使用它**（`pg_isready` 已确认可连）；`docker-compose.yml` **仍按 NFR-7 交付**（部署产物 / CI 用），
  但本地任务不得因容器不可用而阻塞——实测 Docker CLI 存在而 daemon 与容器运行时均缺失。
  测试库 `zhongyi_test`，连接串走 `DATABASE_URL` 环境变量。
  ⚠️ **pgvector 安装实测记录**：`brew install pgvector`（0.8.7）的 bottle **只带 postgresql@17/@18 产物**，
  给 PG16 装不上（`CREATE EXTENSION vector` 报 not available）。已改为**源码编译 0.8.0**：
  `git clone --depth 1 --branch v0.8.0 https://github.com/pgvector/pgvector` →
  `make PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config -j4` → 同参 `make install`（无需 sudo，/opt/homebrew 为用户所有）。
  写入且 **brew 不跟踪**的文件（回滚即删这些）：`lib/postgresql/vector.dylib`、
  `share/postgresql@16/extension/vector.control` + 35 个 `vector--*.sql`、`include/postgresql/server/extension/vector/*.h`。
  验收：`CREATE EXTENSION vector` 成功、`vector(4)` 列 + `USING hnsw (emb vector_cosine_ops)` + `<=>` 查询实测通过。

- 语料 `distilled/` **只读**，ETL 不得写回 `distilled/`；索引版本绑定其 git commit hash（NFR-6）。
  ⚠️ M0 前置仍未做：`distilled/汉唐方剂索引.md`、`distilled/02-伤寒论/临证诊断与治则补充.md` 权限为 `0600`。
- **ETL 收录清单以 PRD 附录 A 为准**（13 份收录 / 4 份排除，含逐文件行数与字符实测）：编号子目录 `01`~`06` 下源文档
  + 顶层 `方剂库-经典配方.md` / `方剂库-经方组成.md` / `汉唐方剂索引.md`；**排除**任意路径 `README.md`、
  `03-金匮/方剂交叉校验.md`、`03-金匮/方剂剂量换算.md`（产物非源）。全角括号副本规则已确认无匹配文件，保留为防御性兜底。
  注意 **行数 ≠ 实体数**：金匮/伤寒两库一行方名列可含多个 `「方名」`，经方组成有「一行四方」，实体数须在身份抽取后统计。
- **`scripts/` 允许修改（2026-10-28 决策，取代原「不改脚本」约束）**：`formula_verify.py` 的方名身份逻辑有已证实缺陷
  （`parse_gram` 正则 `[一-鿿]{2,8}汤方?` 只认「汤」，把加减方截断成母方；`方` 尾未剥离致 `乌梅丸`↔`乌梅丸方` 分裂；
  fallback 产生幽灵键 `—`；`parse_ancient` 未过滤分隔行致 242 行出 243 个名、含 `---`）。
  修正在 **脚本内**完成并附回归测试，backend 继续 `importlib` 复用，**保持「口径唯一来源在 scripts/」不变**。
  `distilled/03-金匮/方剂交叉校验.md` 是旧脚本的历史产物，**不得作为输入被解析**（PRD 附录 A 已判为产物非源）。
- 身份纪律（PRD §5.6 D6）：**宁可分裂，不可误合并**。加减方独立成方 + `formula_alias` 指回母方；
  抽不出方名/一行多方/低置信 → `status=candidate` 进候选队列，**禁止 fallback 造名**（D7）。
- 变体配对（D8）：配对结果 **物化为 `formula_variant_pair`**（带 `algorithm_version`），不在请求路径跑 Jaccard。
  一期实测覆盖率仅 **77/242 ≈ 32%**（脚本修正后；修正前 70 含误合并假阳性），其余显示「未交叉校验」蓝牌，属正常态。
- 剂量换算标准唯一来源 = `scripts/dose_convert.py`：`1两=15g`、`1斤=8两=120g`、`升/合≈50g(近似)`、
  `枚参考值仅 附子/山茱萸=15g`；`分`=比例、`铢` **脚本无分支** → 一律落 `dose_state`，
  非 `exact` 不得写入 `dose_g`（PRD FR-3 五态、附录 B）。实测 1197 个数据点中 31% 转不成克。
  ⚠️ 原 Task 5 断言 `半夏 半升 → 150.0g` 是错的，脚本实际 `0.5×50=25.0g`（`150.0` 属三合），已改正。
- 交叉校验口径唯一来源 = `scripts/formula_verify.py`：药材名去炮制前缀+同义词归一化；剂量偏差阈值 >50%。
- embedding 维度 **1024**（bge-m3）；`chunk_vector.embedding vector(1024)`。
- 所有单测**不得**下载/加载真实模型（用确定性 fake embedder）；真实 BGE-M3 仅在带 `@pytest.mark.integration` 的用例中加载。
- 每个 Task 结束跑 `pytest` 全绿并提交一次（frequent commits）。当前工作分支 `feat/m1-data-foundation`。


---

## File Structure

```
docker-compose.yml                 # postgres16+pgvector 服务（唯一新增基础设施）
backend/
  requirements.txt                 # 运行+测试依赖
  pytest.ini                       # 标记注册 integration，测试路径
  Dockerfile                       # backend 镜像（py3.11）
  app/
    __init__.py
    config.py                      # Settings: DATABASE_URL, DISTILLED_DIR, REPO_DIR, EMBED_MODEL
    main.py                        # create_app(); GET /healthz
    db/
      __init__.py
      session.py                   # engine/session、get_db、make_engine(url)
      models.py                    # §5.3 全部 ORM 模型 + IndexVersion
    etl/
      __init__.py
      scripts_loader.py            # importlib 载入 search/dose_convert/formula_verify
      corpus.py                    # 收录清单：iter_distilled_files()
      dose.py                      # convert(text,name) -> (g|None, note)（薄封装 scripts_loader）
      normalizers.py               # norm/table_rows（复用 search.py）
      parse_herbs.py               # 中药库 + 按味归类 -> herb 记录
      parse_formulas.py            # 经方组成 -> formula + formula_herb（含 dose）
      parse_classics.py            # 经典配方/伤寒方库/金匮方库 -> 现代剂量、source_text、方#
      parse_acupoints.py           # 十二经穴位库 + 治症取穴 -> acupoint + acupoint_symptom
      parse_cases.py               # 临床问答对 -> case
      parse_framework.py           # 框架类文档 -> framework_chunk
      verify.py                    # 封装 formula_verify.verify -> 校验标记
      loaders.py                   # 把解析记录 upsert 进 DB（幂等）
    embed/
      __init__.py
      embedder.py                  # Embedder Protocol + HashingEmbedder(fake) + BgeM3Embedder
      chunk.py                     # 结构化行/框架小节/医案条 -> Chunk(ref_type,ref_id,content)
      indexer.py                   # 切片 + embedding + 写 chunk_vector
    admin/
      __init__.py
      reindex.py                   # run_reindex(): 全流程编排 + git hash 版本
      quality.py                   # build_quality_report()
    git_utils.py                   # distilled_commit_hash()
  tests/
    conftest.py                    # settings/engine/db session fixtures（回滚隔离）
    factories.py                   # 构造最小 md 文本 / 记录 的辅助
    unit/…                          # 各 parser 单测（纯函数，不碰 DB/模型）
    db/…                            # 落库集成测试（需 Postgres）
    integration/…                   # 真实 embedding / 全量 reindex（慢，默认跳过）
```

设计原则：解析逻辑（`parse_*`）是纯函数，输入 md 文本、输出 dataclass 记录，**不碰 DB / 不 import 模型**，便于单测；`loaders.py` 只做记录→ORM upsert；`embed/` 依赖注入 embedder。文件按职责切分，parser 与源文档一一对应。

---

## Task 1: 项目脚手架与运行环境

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/requirements.txt`, `backend/pytest.ini`, `backend/Dockerfile`
- Create: `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`
- Create: `backend/app/db/__init__.py`, `backend/app/db/session.py`
- Create: `backend/app/etl/__init__.py`, `backend/app/etl/scripts_loader.py`
- Create: `backend/tests/conftest.py`, `backend/tests/unit/test_scaffold.py`

**Interfaces:**
- Produces:
  - `app.config.Settings` (pydantic-settings): `.database_url: str`, `.repo_dir: Path`, `.distilled_dir: Path`, `.embed_model: str`
  - `app.db.session.make_engine(url) -> sqlalchemy.engine.Engine`
  - `app.main.create_app() -> FastAPI`（`GET /healthz` 返回 `{"ok": true}`）
  - `app.etl.scripts_loader.LOADER` 暴露 `.search`（含 `norm`,`table_rows`,`build_records`）、`.dose`（含 `convert`）、`.verify`（含 `verify`,`normalize`）三个模块对象
- Consumes: 无（首个任务）

- [x] **Step 1: 写失败测试（脚手架 + 复用脚本可加载）**

`backend/tests/unit/test_scaffold.py`:
```python
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.etl import scripts_loader

def test_healthz():
    assert TestClient(create_app()).get("/healthz").json() == {"ok": True}

def test_dose_convert_reused_from_scripts():
    # 复用 scripts/dose_convert.convert：半夏 半斤 = 0.5 斤 = 60g（1斤=120g）
    g, note = scripts_loader.LOADER.dose.convert("半斤", "半夏")
    assert g == 60.0
    assert "120g" in note and "60.0g" in note

def test_search_norm_reused_from_scripts():
    # 全角转半角 + 去页码
    assert scripts_loader.LOADER.search.norm("第３页ＡＢＣ") == " ABC"
```

- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/unit/test_scaffold.py -v`
Expected: FAIL（ModuleNotFoundError / no app）。

- [x] **Step 3: 依赖与配置**

`backend/requirements.txt`:
```
fastapi==0.115.*
uvicorn[standard]==0.32.*
pydantic-settings==2.*
sqlalchemy==2.*
psycopg[binary]==3.*
pgvector==0.3.*
numpy==1.26.*
sentence-transformers==3.*
torch==2.4.*            # 仅集成用例需要，可在轻量环境注释掉
httpx==0.27.*
pytest==8.*
```

`backend/pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    integration: 需下载真实模型或全量语料，慢，默认 deselected
addopts = -m "not integration"
```

`backend/app/config.py`:
```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://zhongyi:zhongyi@localhost:5432/zhongyi_test"
    repo_dir: Path = Path(__file__).resolve().parents[2]      # .../zhongyi
    embed_model: str = "BAAI/bge-m3"
    @property
    def distilled_dir(self) -> Path:
        return self.repo_dir / "distilled"

settings = Settings()
```

- [x] **Step 4: app 主入口与 db session**

`backend/app/main.py`:
```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="中医经方 RAG · M1")
    @app.get("/healthz")
    def healthz():
        return {"ok": True}
    return app
```

`backend/app/db/session.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from app.config import settings

def make_engine(url: str = settings.database_url):
    return create_engine(url, future=True)

def get_sessionmaker(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True)
```

- [x] **Step 5: importlib 载入 scripts（单一事实源）**

`backend/app/etl/scripts_loader.py`:
```python
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from app.config import settings

def _load(filename: str, modname: str):
    path = settings.repo_dir / "scripts" / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

@dataclass
class _Loader:
    search: object
    dose: object
    verify: object

# search.py/dose_convert.py/formula_verify.py 顶部若引用 __main__ 才走 CLI，import 安全
LOADER = _Loader(
    search=_load("search.py", "zy_search"),
    dose=_load("dose_convert.py", "zy_dose_convert"),
    verify=_load("formula_verify.py", "zy_formula_verify"),
)
```

> 注意：`scripts/search.py` 顶部有 `REPO = "/Users/..."` 硬编码路径，但 `norm`/`table_rows`/`build_records` 中只有 `build_records` 用到 `DIST`。本任务只用到 `norm`；`build_records` 的全量遍历在 Task 7 用 `corpus.py` 取代，不改脚本。若 `import` 触发 CLI 逻辑，确认三脚本均以 `if __name__ == '__main__':` 守卫（已核实）。

- [x] **Step 6: Docker 基础设施**

`docker-compose.yml`:
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: zhongyi
      POSTGRES_PASSWORD: zhongyi
      POSTGRES_DB: zhongyi_dev
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U zhongyi"]
      interval: 5s
      timeout: 3s
      retries: 10
volumes:
  pgdata:
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [x] **Step 7: 建测试库并跑绿**

Run:
```bash
docker compose up -d db
docker compose exec -T db psql -U zhongyi -d postgres -c "CREATE DATABASE zhongyi_test;" || true
cd backend && python -m pytest tests/unit/test_scaffold.py -v
```
Expected: PASS（3 项）。

- [x] **Step 8: Commit**

```bash
git add docker-compose.yml backend
git commit -m "chore(m1): scaffold FastAPI backend, pgvector compose, importlib scripts loader"
```

---

## Task 2: 数据模型（**PRD §5.6 三层方剂模型** + 其余实体 + 索引版本）

> ⚠️ 本 Task 原有的 Step 1 测试样例与 Step 3 模型代码块按旧单层 `formula`/`formula_herb` 写就，
> **已作废**；实现时以下方 Interfaces 为准重写（不得沿用 `Formula.source_doc` / `verify_status` 单列方案）。

**Files:**
- Create: `backend/app/db/models.py`
- Create: `backend/app/git_utils.py`
- Create: `backend/tests/db/test_models_roundtrip.py`

**Interfaces:**
- Produces（SQLAlchemy 2.x `DeclarativeBase`，类名 → 表名）：
  - `Base`
  - `Formula` → `formula`：`id, canonical_name(unique), anchor ∈ {'override','jingfang_zucheng','candidate'}, status ∈ {'confirmed','candidate','split_parent'}, kind ∈ {'single','modified','pair'}, note`（D9）
  - `FormulaComponent` → `formula_component`：`id, pair_formula_id(FK), component_formula_id(FK), ordinal`；合方的两个成分边（D9），重复药味不得合并（D10）
  - `FormulaAlias` → `formula_alias`：`id, formula_id(FK), name, doc, kind ∈ {'古名','现代名','汤方尾巴','加减写法','一行多方拆分'}`；`(name, doc)` 唯一
  - `FormulaDoseVariant` → `formula_dose_variant`：`id, formula_id(FK), source_doc ∈ {'经方组成','经典配方','override'}, dose_basis ∈ {'ancient','gram'}, ordinal, source_row_no, raw_composition(Text), parse_confidence(Float|None), extract_rule_version`
  - `FormulaItem` → `formula_item`：`id, variant_id(FK), herb_id(FK nullable), herb_text, dose_text, dose_g(Float|None), dose_state ∈ {'exact','approx','count_only','absent','unknown_unit'}, preparation, conversion_note`
  - `FormulaEvidence` → `formula_evidence`：`id, formula_id(FK), source_doc ∈ {'伤寒六经方库','金匮方剂库','医案','汉唐索引'}, six_jing, bing_duan, clause_no, formula_no, original_text(Text), source_row_no`
  - `FormulaVariantPair` → `formula_variant_pair`：`id, formula_id(FK), variant_a(FK), variant_b(FK), pairing_method ∈ {'declared','algorithmic'}, herb_diff(JSONB), dose_dev(JSONB), score(Float), algorithm_version, verified_at(DateTime)`
  - `Herb` → `herb`：`id, name(本经古名, unique), alias(ARRAY|JSONB), flavor(Text|None), flavor_source_state ∈ {'extracted','missing'}, effects, indications, dosage_note, taboo, preparation, raw_note(Text), taste_group(可 NULL：实测378/379), organ_group`
  - `Acupoint` → `acupoint`：`id, name, meridian, role, location, actions`
  - `AcupointSymptom` → `acupoint_symptom`：`id, acupoint_id(FK), symptom, source_doc`
  - `Case` → `case`：`id, no, category, chief_complaint, pathogenesis, treatment_formula_ids, added_herbs(随证加味，与主方分列), tips, raw_md`
  - `FrameworkChunk` → `framework_chunk`：`id, doc, section, content, chunk_order`
  - `ChunkVector` → `chunk_vector`：`id, ref_type, ref_id, content, embedding Vector(1024)`
  - `PendingFormulaName` → `pending_formula_name`（FR-13 ⑦ 候选队列，D7 的落点）：`id, raw_name, doc, source_row_no, suggested_parent(FK→formula|None), confidence, evidence_text, decision ∈ {'pending','confirmed_new','merged','noise'}, decided_by, decided_at`
  - `IndexVersion` → `index_version`：`id, commit_hash, created_at, formula_count, herb_count, acupoint_count, case_count, chunk_count, status, embedding_model_version, chunking_version, extract_rule_version`（NFR-6 需同时锁模型与抽取规则版本）
- Consumes: `app.db.session.make_engine`
- 约束要点：`formula_item.dose_g` 仅当 `dose_state='exact'` 或 `'approx'` 可非空；`herb_id` 为空者必须能在 FR-13 ⑤ 清单里被查出（不得静默）。


- [x] **Step 1: 写失败测试（建表 + 回读）**

`backend/tests/db/test_models_roundtrip.py`:
```python
import pytest
from sqlalchemy import select
from app.db.models import Base, Formula, FormulaHerb, Herb

def test_create_all_and_roundtrip(db_session):
    db_session.add_all([
        Herb(name="麻黄", taste_group="辛", organ_group="肺"),
        Formula(name="桂枝汤", source_doc="02-伤寒论/伤寒六经方库.md",
                section="太阳", verify_status="仅单版本"),
    ])
    db_session.flush()
    f = db_session.scalar(select(Formula).where(Formula.name == "桂枝汤"))
    db_session.add(FormulaHerb(formula_id=f.id, herb_name="桂枝",
                               dose_ancient="三两（去皮）", dose_g=45.0,
                               conversion_note="三两 → 3两×15g=45.0g"))
    db_session.commit()
    fh = db_session.scalars(select(FormulaHerb)).first()
    assert fh.dose_g == 45.0 and fh.herb_name == "桂枝"
```

- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/db/test_models_roundtrip.py -v`
Expected: FAIL（ImportError `app.db.models`）。

- [x] **Step 3: 实现模型**

`backend/app/db/models.py`:
```python
from datetime import datetime
from sqlalchemy import Float, ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

class Herb(Base):
    __tablename__ = "herb"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    flavor: Mapped[str] = mapped_column(Text, default="")
    nature: Mapped[str] = mapped_column(String, default="")
    effects: Mapped[str] = mapped_column(Text, default="")
    indications: Mapped[str] = mapped_column(Text, default="")
    dosage_note: Mapped[str] = mapped_column(Text, default="")
    taboo: Mapped[str] = mapped_column(Text, default="")
    taste_group: Mapped[str] = mapped_column(String, default="")   # 酸苦甘辛咸
    organ_group: Mapped[str] = mapped_column(String, default="")   # 五脏

class Formula(Base):
    __tablename__ = "formula"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    source_doc: Mapped[str] = mapped_column(String, default="")
    section: Mapped[str] = mapped_column(String, default="")
    formula_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 经典配方 #
    indication: Mapped[str] = mapped_column(Text, default="")
    ancient_text: Mapped[str] = mapped_column(Text, default="")
    verify_status: Mapped[str] = mapped_column(String, default="仅单版本")

class FormulaHerb(Base):
    __tablename__ = "formula_herb"
    id: Mapped[int] = mapped_column(primary_key=True)
    formula_id: Mapped[int] = mapped_column(ForeignKey("formula.id"), index=True)
    herb_id: Mapped[int | None] = mapped_column(ForeignKey("herb.id"), nullable=True)
    herb_name: Mapped[str] = mapped_column(String)
    dose_ancient: Mapped[str] = mapped_column(String, default="")
    dose_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    conversion_note: Mapped[str] = mapped_column(Text, default="")

class Acupoint(Base):
    __tablename__ = "acupoint"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    meridian: Mapped[str] = mapped_column(String, default="")
    role: Mapped[str] = mapped_column(String, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    actions: Mapped[str] = mapped_column(Text, default="")

class AcupointSymptom(Base):
    __tablename__ = "acupoint_symptom"
    id: Mapped[int] = mapped_column(primary_key=True)
    acupoint_id: Mapped[int] = mapped_column(ForeignKey("acupoint.id"), index=True)
    symptom: Mapped[str] = mapped_column(String)
    source_doc: Mapped[str] = mapped_column(String, default="")

class Case(Base):
    __tablename__ = "case"
    id: Mapped[int] = mapped_column(primary_key=True)
    no: Mapped[str] = mapped_column(String, unique=True)      # 问NN
    category: Mapped[str] = mapped_column(String, default="")
    chief_complaint: Mapped[str] = mapped_column(Text, default="")
    pathogenesis: Mapped[str] = mapped_column(Text, default="")
    treatment_formula_ids: Mapped[str] = mapped_column(String, default="")  # 逗号分隔 id
    tips: Mapped[str] = mapped_column(Text, default="")
    raw_md: Mapped[str] = mapped_column(Text, default="")

class FrameworkChunk(Base):
    __tablename__ = "framework_chunk"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc: Mapped[str] = mapped_column(String)
    section: Mapped[str] = mapped_column(String, default="")
    content: Mapped[str] = mapped_column(Text)
    chunk_order: Mapped[int] = mapped_column(Integer, default=0)

class ChunkVector(Base):
    __tablename__ = "chunk_vector"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref_type: Mapped[str] = mapped_column(String, index=True)  # formula/herb/acupoint/case/framework
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(1024))

class IndexVersion(Base):
    __tablename__ = "index_version"
    id: Mapped[int] = mapped_column(primary_key=True)
    commit_hash: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    formula_count: Mapped[int] = mapped_column(Integer, default=0)
    herb_count: Mapped[int] = mapped_column(Integer, default=0)
    acupoint_count: Mapped[int] = mapped_column(Integer, default=0)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="building")  # building/ready/failed
```

`backend/app/git_utils.py`:
```python
import subprocess
from pathlib import Path

def distilled_commit_hash(distilled_dir: Path) -> str:
    """返回包含 distilled/ 的仓库当前 commit hash（NFR-6）。"""
    out = subprocess.run(
        ["git", "-C", str(distilled_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()
```

- [x] **Step 4: 补 conftest 的 db_session fixture（每次建表→回滚）**

在 `backend/tests/conftest.py` 追加：
```python
import pytest
from sqlalchemy import create_engine
from app.db.models import Base

@pytest.fixture(scope="session")
def engine():
    from app.config import settings
    eng = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)

@pytest.fixture
def db_session(engine):
    conn = engine.connect()
    trans = conn.begin()
    Session = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(bind=conn, future=True)
    s = Session()
    yield s
    s.close()
    trans.rollback()
    conn.close()
```

- [x] **Step 5: 跑绿**

Run: `docker compose up -d db && cd backend && python -m pytest tests/db/test_models_roundtrip.py -v`
Expected: PASS。

- [x] **Step 6: Commit**

```bash
git add backend/app/db/models.py backend/app/git_utils.py backend/tests
git commit -m "feat(m1): add §5.3 ORM models + index_version + db fixtures"
```

---

## Task 3: 收录清单与文本/表格规范化

**Files:**
- Create: `backend/app/etl/corpus.py`, `backend/app/etl/normalizers.py`
- Create: `backend/tests/unit/test_corpus.py`

**Interfaces:**
- Produces:
  - `corpus.distilled_files(distilled_dir) -> list[Path]`（按 Global Constraints 的收录/排除规则，返回相对仓库的 md 路径列表，稳定排序）
  - `corpus.classify(rel_path: str) -> str`（返回 `"herb"|"formula_ancient"|"formula_classic"|"acupoint"|"case"|"framework"|"index"|"skip"`）
  - `normalizers.norm(s) -> str`（转调 `LOADER.search.norm`）
  - `normalizers.table_rows(text) -> list[list[str]]`（转调 `LOADER.search.table_rows`）
- Consumes: `scripts_loader.LOADER`

- [x] **Step 1: 写失败测试**

`backend/tests/unit/test_corpus.py`:
```python
from app.etl import corpus

def test_includes_expected_and_excludes_artifacts():
    files = {p.name for p in corpus.distilled_files()}
    assert {"经方组成" if False else "方剂库-经方组成.md", "中药库.md",
            "十二经穴位库.md", "临床问答对.md", "六经辨证框架.md"} <= files
    assert "README.md" not in files
    assert "方剂交叉校验.md" not in files   # 产物非源
    assert "方剂剂量换算.md" not in files

def test_classify():
    assert corpus.classify("04-神农本草经/中药库.md") == "herb"
    assert corpus.classify("方剂库-经方组成.md") == "formula_ancient"
    assert corpus.classify("方剂库-经典配方.md") == "formula_classic"
    assert corpus.classify("05-针灸/十二经穴位库.md") == "acupoint"
    assert corpus.classify("06-医案/临床问答对.md") == "case"
    assert corpus.classify("02-伤寒论/六经辨证框架.md") == "framework"
    assert corpus.classify("汉唐方剂索引.md") == "index"

def test_norm_and_table_rows_reused():
    from app.etl import normalizers
    assert normalizers.norm("ＡＢ") == "AB"
    rows = normalizers.table_rows("| a | b |\n|---|---|\n| 1 | 2 |")
    assert rows == [["a", "b"], ["1", "2"]]   # 分隔行被丢弃
```

- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/unit/test_corpus.py -v`
Expected: FAIL。

- [x] **Step 3: 实现**

`backend/app/etl/normalizers.py`:
```python
from app.etl.scripts_loader import LOADER

norm = LOADER.search.norm
table_rows = LOADER.search.table_rows
```

`backend/app/etl/corpus.py`:
```python
from pathlib import Path
from app.config import settings

# classify 关键词（相对 distilled/ 的 posix 路径）
_ARTIFACTS = {"03-金匮/方剂交叉校验.md", "03-金匮/方剂剂量换算.md"}

_RULES = [  # (predicate(rel)->bool, kind)
    (lambda r: "中药库" in r or "药物按味归类" in r, "herb"),
    (lambda r: r == "方剂库-经方组成.md", "formula_ancient"),
    (lambda r: r == "方剂库-经典配方.md", "formula_classic"),
    (lambda r: r.startswith("02-伤寒论/伤寒六经方库") or r.startswith("03-金匮/金匮方剂库"), "formula_source"),
    (lambda r: r.startswith("05-针灸/") and "穴位" in r or "取穴" in r, "acupoint"),
    (lambda r: "医案" in r and "临床问答对" in r, "case"),
    (lambda r: r == "汉唐方剂索引.md", "index"),
    (lambda r: r.startswith(("01-内经/", "02-伤寒论/六经辨证框架",
                             "02-伤寒论/临证诊断与治则补充")), "framework"),
]

def classify(rel_path: str) -> str:
    r = Path(rel_path).as_posix()
    if r in _ARTIFACTS or r.endswith("README.md") or any(c in r for c in "（）()"):
        return "skip"
    for pred, kind in _RULES:
        if pred(r):
            return kind
    return "skip"

def distilled_files(distilled_dir: Path | None = None) -> list[Path]:
    d = distilled_dir or settings.distilled_dir
    out = []
    for p in sorted(d.rglob("*.md")):
        rel = p.relative_to(d).as_posix()
        if classify(rel) != "skip":
            out.append(p)
    return out

def read_rel(path: Path) -> tuple[str, str]:
    """返回 (相对 distilled 的 posix 路径, 全文)。"""
    d = settings.distilled_dir
    return path.relative_to(d).as_posix(), path.read_text(encoding="utf-8")
```

> `formula_source`（伤寒/金匮方库）也在收录内但 `classify` 单列，供 Task 5 采集 source_text/indication；若某路径同时命中多条规则，`_RULES` 顺序即优先级。

- [x] **Step 4: 跑绿**

Run: `cd backend && python -m pytest tests/unit/test_corpus.py -v`
Expected: PASS（注意 test_classify 未断言 formula_source，Task 5 会补）。

- [x] **Step 5: Commit**

```bash
git add backend/app/etl/corpus.py backend/app/etl/normalizers.py backend/tests/unit/test_corpus.py
git commit -m "feat(m1): distilled corpus manifest + norm/table_rows reuse"
```

---

## Task 4: 中药库 ETL（herb 记录）

**Files:**
- Create: `backend/app/etl/parse_herbs.py`
- Create: `backend/tests/unit/test_parse_herbs.py`

**Interfaces:**
- Produces:
  - `parse_herbs.HerbRecord`（dataclass: `name, flavor, nature, effects, indications, dosage_note, taboo, taste_group, organ_group`）
  - `parse_herbs.parse_zhongyao(text: str) -> list[HerbRecord]`（解析 `中药库.md` 表格：`| # | 药名 | 气味 | 功效·主治 | 产地 | 用量/禁忌 |`）
  - `parse_herbs.parse_taste_groups(text: str) -> dict[str, tuple[str, str]]`（解析 `药物按味归类.md`：药名 → (味, 脏)）
  - `parse_herbs.merge(...) -> list[HerbRecord]`（把味/脏归类合并进 herb 记录）
- Consumes: `normalizers`

- [x] **Step 1: 写失败测试（用真实样例行）**

`backend/tests/unit/test_parse_herbs.py`:
```python
from app.etl import parse_herbs

SAMPLE_ZY = """
| # | 药名 | 气味 | 功效·主治 | 产地 | 用量/禁忌 |
|---|---|---|---|---|---|
| 1 | 丹砂 | — | 丹砂为安神要药。 | 四川。 | ·禁忌:只可生研水飞用。·用量:二,三分。 |
| 2 | 云母 | — | 云母主补肺下气。 | 产四川。 【性味】味甘性平,无毒。 | ·禁忌:不可过量服食。·用量:数分起。 |
"""

SAMPLE_TASTE = """
## 肝经 · 酸味（17味）
**涅石**、**黄连**、**五味子**
## 心经 · 苦味（142味）
**黄连**、**龙胆**
"""

def test_parse_zhongyao_basic():
    recs = {r.name: r for r in parse_herbs.parse_zhongyao(SAMPLE_ZY)}
    assert set(recs) == {"丹砂", "云母"}
    assert "安神" in recs["丹砂"].effects
    assert recs["丹砂"].taboo.startswith("只可生研")
    assert recs["丹砂"].dosage_note.startswith("二")
    # 性味从文本抽取（产地列内嵌【性味】味甘性平）
    assert recs["云母"].taste == "甘" or recs["云母"].nature == "平"

def test_parse_taste_groups():
    m = parse_herbs.parse_taste_groups(SAMPLE_TASTE)
    assert m["黄连"] == ("苦", "心")   # 后出现的心经苦味覆盖（同名取后者或标注多味，见实现说明）
    assert m["五味子"] == ("酸", "肝")

def test_merge_fills_taste_group():
    zy = parse_herbs.parse_zhongyao(SAMPLE_ZY)
    tg = parse_herbs.parse_taste_groups("**黄连**")  # 无丹砂
    merged = parse_herbs.merge(zy, tg)
    assert all(isinstance(r, parse_herbs.HerbRecord) for r in merged)
```

- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/unit/test_parse_herbs.py -v`
Expected: FAIL。

- [x] **Step 3: 实现解析器**

`backend/app/etl/parse_herbs.py`:
```python
import re
from dataclasses import dataclass
from app.etl.normalizers import norm, table_rows

@dataclass
class HerbRecord:
    name: str
    flavor: str = ""
    nature: str = ""
    effects: str = ""
    indications: str = ""
    dosage_note: str = ""
    taboo: str = ""
    taste_group: str = ""
    organ_group: str = ""

_TASTE_IN_TEXT = re.compile(r'味(酸|苦|甘|辛|咸)')
_NATURE_IN_TEXT = re.compile(r'性(寒|热|温|凉|平|微寒|微温)')

def parse_zhongyao(text: str) -> list[HerbRecord]:
    out = []
    for cells in table_rows(text):
        if len(cells) < 6 or not cells[1] or cells[0] == "#":
            continue
        _no, name, qiwei, effects, origin, dose_taboo = cells[:6]
        name = name.strip()
        if not name:
            continue
        rec = HerbRecord(name=name, effects=effects.strip())
        # 气味列常为 "—"，性味藏在产地/功效文本的【性味】里
        joined = f"{qiwei} {origin} {effects}"
        m = _TASTE_IN_TEXT.search(norm(joined))
        if m:
            rec.flavor = f"味{m.group(1)}"
        m2 = _NATURE_IN_TEXT.search(norm(joined))
        if m2:
            rec.nature = m2.group(1)
        # 用量/禁忌列拆两段
        dt = norm(dose_taboo)
        taboo = re.search(r'禁忌[:：]([^·]*?)(?:·用量|$)', dt)
        dosage = re.search(r'用量[:：](.*)$', dt)
        if taboo:
            rec.taboo = taboo.group(1).strip(" ,。")
        if dosage:
            rec.dosage_note = dosage.group(1).strip(" ,。")
        out.append(rec)
    return out

def parse_taste_groups(text: str) -> dict[str, tuple[str, str]]:
    """`## 肝经 · 酸味（N味）` 段下的 `**药名**` -> (味, 脏)。同名多味：保留先出现的味。"""
    result: dict[str, tuple[str, str]] = {}
    cur = None  # (organ, taste)
    head = re.compile(r'^##\s*(\S+?)经\s*·\s*(酸|苦|甘|辛|咸)味')
    for line in text.splitlines():
        h = head.match(line.strip())
        if h:
            organ_map = {"肝": "肝", "心": "心", "脾": "脾", "肺": "肺", "肾": "肾"}
            cur = (organ_map.get(h.group(1), h.group(1)), h.group(2))
            continue
        if cur:
            for nm in re.findall(r'\*\*([^*]+)\*\*', line):
                result.setdefault(nm, (cur[1], cur[0]))
    return result

def merge(zy: list[HerbRecord], taste_map: dict[str, tuple[str, str]]) -> list[HerbRecord]:
    for r in zy:
        if r.name in taste_map:
            taste, organ = taste_map[r.name]
            r.taste_group, r.organ_group = taste, organ
    return zy
```

> 说明：`药物按味归类.md` 存在同名跨味（如"黄连"仅在苦味，测试样例把它同时写进酸/苦两段以覆盖 setdefault 语义）。真实语料每药一味，`merge` 不做多味拼接。`丹砂` 在 `中药库` 有、`药物按味归类` 未必有（按味只覆盖有明确"味X"标注者），允许 `taste_group` 为空。

- [x] **Step 4: 跑绿**

Run: `cd backend && python -m pytest tests/unit/test_parse_herbs.py -v`
Expected: PASS。若 `test_parse_zhongyao_basic` 的性味断言不稳，确认样例云母行含「味甘性平」——断言 `taste=="甘" or nature=="平"` 二者命中其一即可。

- [x] **Step 5: Commit**

```bash
git add backend/app/etl/parse_herbs.py backend/tests/unit/test_parse_herbs.py
git commit -m "feat(m1): 中药库 herb parser + 五味归类 merge"
```

---

## Task 5: 经方组成 ETL（**§5.6：formula + formula_dose_variant + formula_item** + 剂量换算）

**Files:**
- Create: `backend/app/etl/dose.py`, `backend/app/etl/parse_formulas.py`, `backend/app/etl/identity.py`
- Modify: `scripts/formula_verify.py`（`normalize` 增 `方` 尾剥离、`parse_gram`/`parse_ancient` 过滤分隔行与幽灵键）
- Create: `backend/tests/unit/test_parse_formulas.py`, `backend/tests/unit/test_identity.py`, `scripts/tests/test_formula_verify.py`

**Interfaces:**
- Produces:
  - `dose.convert(dose_text, herb="") -> (g|None, note, dose_state)` —— 在原 `(g, note)` 基础上**必须补第三项状态**，
    按 PRD FR-3/附录 B 映射：`两/斤/钱→exact`、`升/合/枚(参考值)→approx`、`枚/个/茎/片无参考值→count_only`、
    `分/等分/见原书→absent`、`无可识别单位(如 铢)→unknown_unit`。判定依据是脚本 `note` 文本，
    **不得在 backend 重算克数**。
  - `identity.extract_formula_name(field: str) -> list[NameCandidate]` —— `NameCandidate(name, confidence, kind)`；
    剂型全集正则（汤/丸/散/饮/膏/丹/酒/方）+ 剥 `方` 尾 + 优先 `·` 尾段 + **一行多方拆分**；
    全部失败 → 返回空列表（**进候选队列，不 fallback 造名**）。
  - `identity.split_parent(name) -> str|None` —— 加减方识别（`桂枝汤加葛根` → 母方 `桂枝汤`），
    供 `formula_alias(kind=加减写法)`；**加减方自身仍是独立 formula**。
  - `parse_formulas.parse_ancient(text, source_doc) -> list[AncientFormula]` ——
    `AncientFormula(name, source_claim ∈ {伤寒,金匮,伤寒+金匮}, herbs: list[Item])`，
    `Item(herb_text, dose_text, dose_g, dose_state, preparation, conversion_note)`；
    产出映射到 `formula_dose_variant(dose_basis='ancient')` + `formula_item`。
  - 幽灵键回归：`parse_ancient` 对 `|---|---|` 分隔行必须跳过（实测旧脚本 242 行出 243 名，含 `---`）。
- Consumes: `normalizers`, `dose`, `scripts_loader.LOADER.dose`/`LOADER.verify`


- [x] **Step 1: 写失败测试（真实桂枝汤/射干麻黄汤行）**

`backend/tests/unit/test_parse_formulas.py`:
```python
from app.etl import parse_formulas, dose, identity

SAMPLE = """
| 方名 | 来源 | 组成（药味·剂量·炮制） |
|---|---|---|
| 桂枝汤 | 伤寒 | **桂枝** 三两（去皮）；**芍药** 三两；**甘草** 二两（炙）；**生姜** 二两（切）；**大枣** 十二枚（劈） |
| 射干麻黄汤 | 金匮 | **射干** 三两；**麻黄** 四两；**半夏** 半升 |
"""

def test_convert_returns_state_too():
    # 旧签名 (g, note) 不够：升/枚/分/铢 必须带状态（PRD FR-3 五态）
    assert dose.convert("三两", "桂枝") == (45.0, "三两 → 3两×15g=45.0g", "exact")
    assert dose.convert("十二枚", "大枣")[2] == "count_only"
    assert dose.convert("二分", "甘草")[0] is None and dose.convert("二分", "甘草")[2] == "absent"
    assert dose.convert("十八铢", "猪苓")[2] == "unknown_unit"   # 脚本无「铢」分支

def test_parse_ancient_guizhi():
    recs = {r.name: r for r in parse_formulas.parse_ancient(SAMPLE, "方剂库-经方组成.md")}
    g = recs["桂枝汤"]
    assert g.source_claim == "伤寒"
    assert len(g.herbs) == 5
    first = g.herbs[0]
    assert first.herb_text == "桂枝"
    assert first.dose_g == 45.0 and first.dose_state == "exact"
    assert first.preparation == "去皮"
    # 大枣十二枚：不得臆造克数
    z = [h for h in g.herbs if h.herb_text == "大枣"][0]
    assert z.dose_g is None and z.dose_state == "count_only" and z.dose_text == "十二枚（劈）"

def test_parse_ancient_skips_separator_row():
    # 旧脚本缺陷：|---|---| 被当成一方 → 242 行出 243 名（含幽灵键 "---"）
    recs = parse_formulas.parse_ancient(SAMPLE, "x")
    assert all(r.name.strip("-— ") for r in recs)
    assert "---" not in {r.name for r in recs}

def test_shema_dose():
    recs = {r.name: r for r in parse_formulas.parse_ancient(SAMPLE, "x")}
    x = {h.herb_text: h for h in recs["射干麻黄汤"].herbs}
    assert x["射干"].dose_g == 45.0 and x["射干"].dose_state == "exact"   # 三两
    assert x["麻黄"].dose_g == 60.0 and x["麻黄"].dose_state == "exact"   # 四两
    # 半升 = 0.5×~50g = 25.0g（approx）。注意：原计划的 150.0 是错的，150 属「三合」；
    # 而 PRD 原 §5.4 的「半斤=180g」同样错（实为 0.5斤×120g=60g）。
    assert x["半夏"].dose_g == 25.0 and x["半夏"].dose_state == "approx"

def test_identity_extracts_all_dosage_forms():
    # 旧正则只认「汤」→ 丸/散/饮 全退化；且必须剥「方」尾，修 乌梅丸↔乌梅丸方 分裂
    # 语料真实行：#100「温经方」与 #8「温经汤」是两组不同组成，D6 下**不得自动合并**
    assert identity.extract_formula_name(
        "治疗不孕的基础方 — 出自<伤寒杂病论>--温经方 · 温经方")[0].name == "温经方"
    assert identity.extract_formula_name("… · 乌梅丸方")[0].name == "乌梅丸"
    assert identity.extract_formula_name("治疗急性乳腺炎的处方 · —") == []      # 造不出名 → 候选队列

def test_identity_splits_multi_formula_row():
    # 语料真实行：经典配方 方#28 一行连写四首
    names = [c.name for c in identity.extract_formula_name(
        "出自<伤寒杂病论>--桂枝汤,当归散,白术散,当归生姜羊肉汤 · 桂枝汤,当归散,白术散,当归生姜羊肉汤")]
    assert set(names) == {"桂枝汤", "当归散", "白术散", "当归生姜羊肉汤"}

def test_identity_split_parent():
    # 语料真实行：方#61 桂枝汤加葛根、方#72 桂枝汤加厚朴和杏仁 → 独立成方，母方指回桂枝汤
    assert identity.split_parent("桂枝汤加葛根") == "桂枝汤"
    assert identity.split_parent("桂枝汤加厚朴和杏仁") == "桂枝汤"
    assert identity.split_parent("桂枝汤") is None
```

> **回归护栏（必做）**：以上 4 个测试的输入串全部逐字取自 `distilled/方剂库-经典配方.md`
> 方#28/#61/#72/#100，改动语料后须同步；断言的克数一律来自 `python3 scripts/dose_convert.py` 的实际输出，
> 不得凭记忆填写（PRD 附录 B 已记录两处历史错误：`半斤=180g`、`半升=150g`）。


- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/unit/test_parse_formulas.py -v`
Expected: FAIL。

- [x] **Step 3: 实现 dose 与 parser**

`backend/app/etl/dose.py`:
```python
from app.etl.scripts_loader import LOADER

def convert(dose_text: str, herb: str = "") -> tuple[float | None, str]:
    return LOADER.dose.convert(dose_text, herb)
```

`backend/app/etl/parse_formulas.py`:
```python
import re
from dataclasses import dataclass, field
from app.etl.normalizers import norm
from app.etl import dose

@dataclass
class HerbDose:
    herb_name: str
    dose_ancient: str
    dose_g: float | None
    conversion_note: str

@dataclass
class FormulaRecord:
    name: str
    source_doc: str
    section: str
    composition: list[HerbDose] = field(default_factory=list)

_Herb = re.compile(r'\*\*([^*]+?)\*\*\s*(.+?)(?=；|$)')

def _split_rows(text: str):
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] == "方名":
            continue
        if all(set(c) <= set("-:") for c in cells):
            continue
        yield cells

def parse_ancient(text: str, source_doc: str) -> list[FormulaRecord]:
    out = []
    for name, src, comp in _split_rows(text):
        rec = FormulaRecord(name=name, source_doc=source_doc, section=src)
        for nm, ds in _Herb.findall(comp):
            nm = nm.strip()
            ds = ds.strip()
            if re.match(r'^[（(]', ds) or "剂量见原书" in ds:
                out_dose, note = None, ds
            else:
                out_dose, note = dose.convert(ds, nm)
            rec.composition.append(HerbDose(nm, ds, out_dose, note))
        if rec.composition:
            out.append(rec)
    return out
```

> `半夏 半升` → `dose_convert.convert` 对"升"按近似 `n×50g`：`半升`=0.5→`25.0g`，**不是** `150.0`。测试断言以脚本真实输出为准：修正 `test_shema_dose` 的半夏期望为 `25.0`（本 Step 5 跑绿时按实际值锁定；升为容量近似，dose_convert 已在 note 标注"升近似"）。

- [x] **Step 4: 跑绿**

Run: `cd backend && python -m pytest tests/unit/test_parse_formulas.py -v`
Expected: PASS（把半夏断言改为 `25.0`）。

- [x] **Step 5: Commit**

```bash
git add backend/app/etl/dose.py backend/app/etl/parse_formulas.py backend/tests/unit/test_parse_formulas.py
git commit -m "feat(m1): 经方组成 parser + dose 换算复用 dose_convert"
```

---

## Task 6: 经典配方 + 伤寒/金匮方库 ETL（现代剂量 · 方# · 原文）

**Files:**
- Create: `backend/app/etl/parse_classics.py`
- Create: `backend/tests/unit/test_parse_classics.py`

**Interfaces:**
- Consumes: `identity`（Task 5）, `dose`, `normalizers`, `scripts_loader.LOADER.verify.normalize`（药材名归一）
- Produces:
  - `parse_classics.ClassicVariant`（`no:int|None, names: list[NameCandidate], herbs: list[(归一化药名, 克数|None, 原文)], remark`）
  - `parse_classics.parse_classic(text) -> list[ClassicVariant]`（`| # | 病证/方名 | 组成 | 备注 |`）——
    方名**必须走 `identity.extract_formula_name`**，不再用 `·` 后段兜底；
    一行多方（方#28）→ 多个候选；抽不出名（实测 63 行，脚本修正后）→ 产 `PendingFormulaName` 而非静默丢弃；
    组成按逗号切 `药名 N克`，**抽不出药味者不得丢弃整行**（方#28 组成为「孕期 1,」这类非药味文本，
    旧 `parse_gram` 会因 `if herbs:` 直接丢行）→ 保留行 + `parse_confidence` 降级。
  - `parse_classics.parse_evidence(text, doc) -> list[EvidenceRow]`（`伤寒六经方库.md`/`金匮方剂库.md`）——
    每行可含**多个** `「方名」`，逐名产出 `formula_evidence`（带 `clause_no`/`bing_duan`/`original_text`），
    不再压成 `dict[方名→原文]` 单值；`六经`/`病段` 从所在小节推断。
    讲稿噪声名（实测金匮有「这都是真武汤」「一样的汤」「主力是桂枝汤」等）须经**方名白名单**过滤，
    白名单来源 = `override 45 方 ∪ 经方组成 242 方 ∪ 已确认候选`；白名单外 → 候选队列。
- 覆盖说明：本期 `formula_variant_pair` 预期仅命中约 **32%**（77/242），其余方留空即「未交叉校验」，**不得为凑覆盖率放宽身份判定**。
- **合方（D9–D11）**：`identity.split_pair_components(tail)` 三层门禁（尾段定位 + 连接词前须剂型字 + spine 整名否决）；
  命中则 `kind=pair` + 两条 `formula_component`；组成非空才建 variant 且重复药味按原文保留；
  成分未命中 spine → `status=candidate` + `pending_formula_name`（附药味集重合的 suggested_parent，不自动合并）；
  实测目标：13 行拆对、27 行病证假阳性不动、32 个 spine 独立经方不被劈。


- [x] **Step 1: 写失败测试**

`backend/tests/unit/test_parse_classics.py`:
```python
from app.etl import parse_classics

CLASSIC = """
| # | 病证/方名 | 组成(药材·剂量) | 备注 |
|---|---|---|---|
| 100 | 治疗不孕的基础方 — 出自<伤寒杂病论>--温经方 · 温经方 | 吴茱萸 15克, 当归 10克, 白芍 10克 |  |
"""

def test_parse_classic_name_and_doses():
    recs = parse_classics.parse_classic(CLASSIC)
    assert len(recs) == 1
    r = recs[0]
    assert r.name == "温经方"
    assert r.no == 100
    doses = dict(r.herbs)
    assert doses["当归"] == 10.0
    # 白芍归一化为芍药
    assert "芍药" in doses or "白芍" in doses

SOURCE = """
| 1 | 「五苓散」 | 若脉浮,小便不利,微热,消渴者,「五苓散」主之。 |
"""

def test_parse_source_text():
    m = parse_classics.parse_source_text(SOURCE, "02-伤寒论/伤寒六经方库.md")
    assert "五苓散" in m
    assert "小便不利" in m["五苓散"]
```

- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/unit/test_parse_classics.py -v`
Expected: FAIL。

- [x] **Step 3: 实现**

`backend/app/etl/parse_classics.py`:
```python
import re
from dataclasses import dataclass
from app.etl.normalizers import norm
from app.etl.scripts_loader import LOADER

normalize = LOADER.verify.normalize

@dataclass
class ClassicFormula:
    no: int | None
    name: str
    herbs: list[tuple[str, float | None]]

_CN_NUM = re.compile(r'(半|[0-9]+(?:\.[0-9]+)?)')

def _name_from_field(field: str) -> str:
    if "·" in field:
        return field.split("·")[-1].strip()
    return field.strip()

def parse_classic(text: str) -> list[ClassicFormula]:
    out = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|") or "# |" in line[:6]:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or all(set(c) <= set("-:") for c in cells):
            continue
        no_raw, name_field, comp = cells[0], cells[1], cells[2]
        no = int(no_raw) if no_raw.isdigit() else None
        herbs = []
        for seg in norm(comp).split(","):
            m = re.match(r'\s*([一-鿿]{2,4}?)\s*(半|[0-9]+(?:\.[0-9]+)?)', seg)
            if m:
                herbs.append((normalize(m.group(1)), float(m.group(2)) if m.group(2) != "半" else 0.5))
        if herbs:
            out.append(ClassicFormula(no=no, name=_name_from_field(name_field), herbs=herbs))
    return out

def parse_source_text(text: str, doc: str) -> dict[str, str]:
    """伤寒/金匮方库：第一/二列取方名（去「」），末列为原文节选。"""
    m = {}
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cand = next((c for c in cells if "「" in c and "」" in c), None)
        if not cand:
            continue
        name = re.search(r'「([^」]{2,12})」', cand)
        if not name:
            continue
        body = " ".join(c for c in cells if c != cand)
        m.setdefault(name.group(1), norm(body).strip())
    return m
```

- [x] **Step 4: 跑绿**

Run: `cd backend && python -m pytest tests/unit/test_parse_classics.py -v`
Expected: PASS。

- [x] **Step 5: Commit**

```bash
git add backend/app/etl/parse_classics.py backend/tests/unit/test_parse_classics.py
git commit -m "feat(m1): 经典配方现代剂量 + 伤寒/金匮原文节选 parser"
```

---

## Task 7: 针灸 ETL（acupoint + acupoint_symptom）

**Files:**
- Create: `backend/app/etl/parse_acupoints.py`
- Create: `backend/tests/unit/test_parse_acupoints.py`

**Interfaces:**
- Produces:
  - `parse_acupoints.AcupointRecord`（`name, meridian, role, location, actions, symptoms: list[str]`）
  - `parse_acupoints.parse_meridian_detail(text: str) -> list[AcupointRecord]`（解析 `十二经穴位库.md` 第四节各经 `### {经}(出现 N 穴)` 下 `| 穴位 | 角色 | 原文主治摘录 |`，`meridian` 取自所属 `###` 标题，`actions`=主治摘录，`role` 原样保留）
  - `parse_acupoints.parse_symptom_points(text: str) -> list[tuple[str, str]]`（解析 `针灸治症取穴.md`：`| # | 病症/主题 | 取穴 | 原文摘录 |` -> (穴名, 症状)）
- Consumes: `normalizers`

- [x] **Step 1: 写失败测试**

`backend/tests/unit/test_parse_acupoints.py`:
```python
from app.etl import parse_acupoints

MERIDIAN = """
### 手太阴肺经(出现 11 穴)
| 穴位 | 角色 | 原文主治摘录 |
|---|---|---|
| 列缺 | 络穴 | 咳嗽气喘 |
| 太渊 | 输穴·原穴 |  |
"""

SYMPTOM = """
| # | 病症/主题 | 取穴 | 原文摘录 |
|---|---|---|---|
| 1 | 全身脉络之主管 | 大包 | 大包穴（ |
"""

def test_parse_meridian_detail():
    recs = {r.name: r for r in parse_acupoints.parse_meridian_detail(MERIDIAN)}
    assert recs["列缺"].meridian == "手太阴肺经"
    assert recs["列缺"].role == "络穴"
    assert recs["列缺"].actions == "咳嗽气喘"
    assert recs["太渊"].role == "输穴·原穴"

def test_parse_symptom_points():
    pairs = parse_acupoints.parse_symptom_points(SYMPTOM)
    assert ("大包", "全身脉络之主管") in pairs
```

- [x] **Step 2: 运行验证失败**

Run: `cd backend && python -m pytest tests/unit/test_parse_acupoints.py -v`
Expected: FAIL。

- [x] **Step 3: 实现**

`backend/app/etl/parse_acupoints.py`:
```python
import re
from dataclasses import dataclass, field
from app.etl.normalizers import norm

@dataclass
class AcupointRecord:
    name: str
    meridian: str = ""
    role: str = ""
    location: str = ""
    actions: str = ""
    symptoms: list[str] = field(default_factory=list)

_HEAD = re.compile(r'^###\s*(手|足)?\S*经')

def parse_meridian_detail(text: str) -> list[AcupointRecord]:
    out = []
    meridian = ""
    for line in text.splitlines():
        if line.startswith("### "):
            h = re.match(r'###\s*(.+?)\(', line)
            meridian = h.group(1).strip() if h else ""
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("穴位", "") or all(set(c) <= set("-:") for c in cells):
            continue
        name, role, actions = cells[0], cells[1], cells[2]
        if name == "穴位":
            continue
        out.append(AcupointRecord(name=name, meridian=meridian,
                                  role="" if role == "—" else role,
                                  actions=norm(actions).strip()))
    return out

def parse_symptom_points(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        symptom, points = cells[1], cells[2]
        for p in re.split(r'[、,，/\s]+', points):
            p = p.strip()
            if 2 <= len(p) <= 6:
                pairs.append((p, symptom))
    return pairs
```

- [x] **Step 4: 跑绿 + Commit**

Run: `cd backend && python -m pytest tests/unit/test_parse_acupoints.py -v`（PASS）
```bash
git add backend/app/etl/parse_acupoints.py backend/tests/unit/test_parse_acupoints.py
git commit -m "feat(m1): 十二经穴位库 + 治症取穴 parser"
```

---

## Task 8–16：M1 后半段（**待细化**，2026-10-28 登记）

原计划到 Task 7 就断了，而 File Structure 声明的 8 个模块一个任务都没有。
以下按「先修 Task 1-7、后半段边做边补」的决策登记为待办；**每个任务开工前必须先补齐 5 步式分解**，
不得凭这张表直接写代码。

| # | 任务 | 范围 | 完成判据（可测） |
|---|---|---|---|
| 8 | 医案 ETL `parse_cases.py` | `06-医案/临床问答对.md` 叙述体 → `case` 30 条；主方与**随证加味**分列（「射干麻黄汤＋桔梗」）；`treatment_formula_ids` 走 `identity` 解析 | `case` 计数 = 30（`问NN` 唯一编号实测 30）；加味不入主方 `formula_item` |
| 9 | 框架 ETL `parse_framework.py` | `01/02/04/06` 的框架类文档 → `framework_chunk`；小节边界即切片边界 | 实测数据行：核心理论 10 / 六经框架 17 / 临证补充 25；七条基准可被 FR-5 问诊卡消费 |
| 10 | 药材归一与 `herb_id` 关联 | 古名↔现代名（实测 `牡桂`=桂枝、`茈胡`=柴胡、`杏仁` 在库内无此行）+ 炮制前缀；**复用改造后的 `formula_verify.normalize`** | FR-13 ⑤ 悬空数清零；提问「柴胡」「茈胡」命中同一 `herb` |
| 11 | `verify.py` + `formula_variant_pair` 落库（D8） | 调 `formula_verify.verify`，配对结果物化，写 `algorithm_version`；黄牌/灰勾/蓝牌三态数据齐备 | 配对数 = 77（脚本修正后实测）；`乌梅丸`↔`乌梅丸方` 分裂对已归一；无 `—`/`---` 幽灵方 |
| 12 | `loaders.py` 幂等 upsert | 解析记录 → ORM；按 `(canonical_name)` / `(variant, herb_text)` 等自然键 upsert，重复 reindex 不产生重复行 | 连跑两次 reindex，各表计数不变 |
| 13 | `embed/`：切片 + Embedder | `chunk.py`（表格行/医案条/框架小节）+ `embedder.py`（`HashingEmbedder` 单测用、`BgeM3Embedder` 仅 integration）+ `indexer.py` | 单测**不下载模型**；`chunk_vector.embedding` 维度 1024；`chunking_version` 落 `index_version` |
| 14 | `admin/reindex.py` + `git_utils.py` | 全流程编排：corpus → parse → identity → verify → load → embed；绑 `distilled/` git hash；**蓝绿切换**（重建期间旧索引可用，PRD 6.6） | `GET /healthz` 与 `POST /api/admin/reindex` 通；`index_version` 至少两行且旧行仍被查询命中 |
| 15 | `admin/quality.py` + 对外 API | FR-13 七张清单 + `GET /api/admin/quality-report`；候选队列读写（⑦） | 七张清单齐；⑦ 队列规模与附录 C 实测一致（54 行抽不出名 + 6+ 对 `方` 尾分裂） |
| 16 | M0 前置收口 | `0600` 权限修正（`汉唐方剂索引.md`、`临证诊断与治则补充.md`）；`docker-compose.yml` 交付但本地不依赖 | `git ls-files -s` 权限位为 100644；compose 文件可被 CI 读取（不要求本地可 run） |

**已知的计划外风险（执行到相关任务时须知）**：
- `scripts/search.py` 顶部 `REPO = "/Users/..."` 硬编码；Task 1 只用 `norm`，全量遍历由 `corpus.py` 取代。
- pgvector 的 Homebrew bottle **只覆盖 postgresql@17/@18**，本机 PG 16.15 需另行解决（见 2026-10-28 环境记录）。


---
