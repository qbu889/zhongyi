# M4 前端设计：对话页 + 四大库 + 溯源抽屉 + 问诊引导

> 状态：待评审
> 里程碑：M4（PRD §8）
> 验收：PRD §6.7 交互验收清单
> 前置：M1–M3 已合并 master（`6dfa98c`）
> 后端边界：最小补口（会话列表/删除、SSE 进度与错误事件、列表多值筛选、E2E 引导脚本）

---

## 1. 目标

交付一个可用的 Web 前端，让用户能：

1. 用自然语言提问，看到意图、检索进度、流式回答与**可见的库内出处**；
2. 点开角标看到不截断的原文，并能跳到对应库详情；
3. 浏览方剂/中药/针灸/医案四大库，筛选条件可分享、可回退；
4. 在信息不足时通过问诊卡补充主诉，再进入辨证链；
5. 在任何页面看到同一份免责声明。

设计原则沿用 PRD §6：**哪句话有库内出处、哪句是组织语、哪条被拒答，必须一眼可辨。**

---

## 2. 范围

### 2.1 M4 交付

| 路由 | 内容 |
|---|---|
| `/chat`、`/chat/[sessionId]` | 对话页：会话侧栏、状态机、流式、角标、抽屉、方/药/穴/案卡、拒答卡、问诊卡 |
| `/formulas`、`/formulas/[id]` | 方剂库列表 + 详情（含克↔古制开关、校验明细、就本条提问） |
| `/herbs`、`/herbs/[id]` | 中药库列表 + 详情 |
| `/acupoints`、`/acupoints/[id]` | 针灸库列表 + 详情 |
| `/cases`、`/cases/[id]` | 医案库列表 + 详情 |
| 全局 | 顶栏、固定免责条、404、空状态、错误态 |

### 2.2 M4 明确不做

- 辨证框架页（`/framework` 仅占位页，M5）
- 管理端（`/admin` 仅占位页，M5）
- 👍/👎 反馈写入 `answer_log`（M5 日志看板）
- 会话重命名（只做新建、删除、回放）
- FR-14「在原文 `text/` 搜一下」实际检索（按钮保留但置灰，M5）
- compose 前端服务（PRD M5「compose 部署」）
- 鉴权、生产建表路径、真实 LLM 接入
- `Answer` 结构变更（逐味 `doses`、`cards` 字段均不加）

---

## 3. 约束与不变量

- **只依据本地库**：前端不补写方名、药名、穴位、病机或疗效；拒答卡不出现「自由发挥」正文。
- **剂量诚实**：克数只来自 `dose_g`；`approx` 显示为近似（`~`+橙牌），`count_only / unknown_unit / absent` 克数列显示 `—`；不得把古制数量渲染成精确克数（NFR-4）。
- **免责三处**：全局底栏、详情页尾、复制/导出物；文案用服务端 `disclaimer`，前端不改写（NFR-5）。
- **单测离线**：Vitest/MSW 不访问网络；Playwright 只连本机后端与本机数据库。
- **不改后端纪律**：`refusal_threshold=0.30`、门禁规则、管理端无鉴权现状均不改。
- **不伪造出处**：角标只挂 `Answer.citations` 中真实存在的引用；无 `general_note` 时不渲染灰框。

---

## 4. 架构与技术选型

- **Next.js App Router + React + TypeScript strict + Tailwind CSS**（PRD D5 默认）。
- **服务端渲染优先**：四大库列表/详情用 Server Component 直取后端，筛选条件在 URL → 首屏直出。
- **对话页为 Client Component**：SSE、会话状态、抽屉与问诊交互都在客户端。
- **无障碍原语**：Radix（Dialog/Drawer、Tabs、Switch、Tooltip），不自建焦点陷阱。
- **不引入全局状态库**：URL query + 局部 `useState` + 少量 `useReducer`（对话状态机）。
- **代理**：浏览器请求同源 `/api/*`，由 `next.config` rewrite 到 `BACKEND_ORIGIN`，规避 CORS；SSE 走同一代理。

---

## 5. 路由与全局布局

```
┌────────────────────────────────────────────────────────┐
│ 顶栏：Logo ｜ 对话 ｜ 方剂库 ｜ 中药库 ｜ 针灸 ｜ 医案 ｜ 辨证框架(禁用) ｜ 管理(禁用) │
├──────────┬──────────────────────────────┬──────────────┤
│ 会话列表   │        主内容区                │  溯源抽屉      │
├──────────┴──────────────────────────────┴──────────────┤
│ 底部常驻免责条（NFR-5）                                  │
└────────────────────────────────────────────────────────┘
```

- 顶栏「辨证框架」「管理」渲染为禁用项并标注 M5；直接访问 `/framework`、`/admin` 返回占位页（一句说明 + 免责条）。
- 断点：≥1280 三栏（会话 240px / 主区 / 抽屉 400px 覆盖）；768–1279 会话栏折叠、抽屉全屏；<768 单栏、抽屉底部滑出。
- 免责条 `position: sticky/fixed` 底部，不随滚动消失；回答卡片内另有服务端免责尾注。

---

## 6. 数据层与接口契约

### 6.1 连接

- 服务端：`BACKEND_ORIGIN`（默认 `http://localhost:8000`）+ `/api/...`，`cache: "no-store"`。
- 浏览器：相对路径 `/api/...`；`next.config` rewrite `/api/:path*` → `${BACKEND_ORIGIN}/api/:path*`。
- 环境示例：`frontend/.env.example` 中 `BACKEND_ORIGIN=http://localhost:8000`。
- 风险兜底：若 Next rewrite 对 SSE 有缓冲，改为浏览器直连后端并在 FastAPI 加 CORS（作为首个任务的验证点，见 §12.3）。

### 6.2 类型

手写 `lib/types.ts`，与 pydantic 响应一一对应：`Answer`、`Citation`、`Section`、`ChatResponse`、`SearchResponse`、`FormulaDetail`、`HerbDetail`、`AcupointDetail`、`CaseDetail`、`SessionItem`。不做 codegen。

### 6.3 错误契约

- REST 错误：`{"detail": {"code": "...", "message": "..."}}`；前端按 `code` 显示可读文案。
- 索引未就绪：`409 index_not_ready` → 对话页提示「索引尚未构建」，给管理员操作指引（不提供按钮）。
- 嵌入不匹配：`503 embedding_mismatch`。
- 证据 404：抽屉显示「该出处在当前索引版本不存在」，保留角标来源与近似锚点。

### 6.4 SSE 契约

现有事件保持兼容，新增 `progress` 与 `error`：

```
event: meta
data: {"session_id":1,"intent":"A","status":"answered"}

event: progress
data: {"total":12,"by_type":{"formula":4,"herb":5,"case":3,"evidence":0}}

event: citation
data: { ...Citation }

event: token
data: {"text":"..."}

event: done
data: { ...ChatResponse }

event: error
data: {"code":"llm_timeout","message":"生成失败"}
```

- `progress` 在检索完成、首个 token 前发出；计数来自 `answer.citations` 按 `ref_type` 聚合。
- 后端在首个 token 前提交事务，客户端中断后该轮仍可在历史中回放；不做逐 token 断点续传。
- 前端解析：按空行分帧，读取 `event:` 与 `data:`；未知事件忽略。

### 6.5 会话接口（后端新增）

```
GET /api/chat/sessions?limit=20&offset=0
{
  "total": 3, "limit": 20, "offset": 0,
  "items": [
    {"id": 1, "title": "咳嗽气喘痰白不能平躺", "last_activity_at": "...", "message_count": 4}
  ]
}

DELETE /api/chat/{session_id}  ->  204
```

- `title` 取该会话首条用户消息正文，截断 30 字；无用户消息时为「新会话」。
- 按 `last_activity_at` 倒序；`message_count` 含 user + assistant。
- `DELETE`：删除该会话的 `chat_message`，将 `qa_log.session_id` 置 NULL（保留日志），再删 `chat_session`；不存在返回 404。
- 路由注册顺序：`/sessions` 必须在 `/{session_id}` 之前，避免 `sessions` 被当作 id 校验。

### 6.6 列表参数扩展（后端新增）

- 方剂：`six_jing` 支持重复参数（多选）；新增 `source_doc`（按 `formula_evidence.source_doc` 精确匹配）。单值调用行为不变。
- 中药：`taste_group` 支持重复参数（多选）。单值行为不变。
- 其余筛选保持现有单值参数。

---

## 7. 对话页

### 7.1 状态机

```
idle → intent → retrieving → streaming → done
                     └──────────────→ refused（done 的特殊终态）
  任意阶段 → error / interrupted
```

- 发送后立即插入用户气泡 + 骨架助手气泡。
- `meta` 到达：显示意图徽章（A 辨证 / B 方剂 / C 中药 / D 取穴 / E 医案 / F 综合）与 `session_id`；用 `history.replaceState` 更新 URL。
- `progress` 到达：显示「命中 N 条本地证据（方剂 x / 中药 y / 医案 z）」；点击展开本轮证据列表。
- `token` 到达：文本流式追加；**卡片不在此阶段渲染**。
- `done`：用 `answer.sections` 重排正文，挂角标，批量回填卡片；`status=refused` 转入拒答卡。
- `error`：气泡内错误条「生成失败，重试 / 换浏览页查询」；保留已到进度信息。

### 7.2 流式与终态渲染

- 流式阶段只渲染 `prose`（FakeLlm 下为各 section 的确定性拼接）。
- `done` 后用 `sections` 渲染标题 + 行，避免与卡片重复；`prose` 不再次展示。
- 说明：真实 LLM 的 prose 与 sections 合并呈现留到 M5，M4 以 sections 为唯一正文口径（诚实边界，见 §13）。

### 7.3 角标定位

- 按 `ref_type:ref_id` 去重编号 `[1..n]`，同来源复用同号。
- 定位规则：在某 section 的某行中查找 `citation.title` 的子串；命中则把角标挂在该行尾。多引用同一行时按编号顺序排列。
- 未命中任何行时，角标挂在答案正文末尾的「出处」行；**不做逐句语义对齐**（服务端未提供 citation offset）。
- hover 350ms 显示摘要卡（title + anchor + snippet 前 60 字）；点击打开抽屉。
- `general_note` 若存在：灰底虚线框 + 「通用框架说明（非本库内容）」，不带角标（M3 恒为 null，渲染器与单测先就位）。

### 7.4 溯源抽屉

- 点击角标调用 `GET /api/evidence/{ref_type}:{ref_id}`，显示 `text` 全文；用 `citation.snippet` 做子串高亮，找不到则不高亮。
- 抽屉内容：全文、anchor（`文件#章节#方#/医案号`）、「在库详情页打开」、「复制引用」。
- 详情页映射：formula→`/formulas/:id`、herb→`/herbs/:id`、acupoint→`/acupoints/:id`、case→`/cases/:id`；evidence 若 `fields.formula_id` 存在则跳方剂详情；framework 暂无详情页，隐藏跳转。
- 抽屉 Esc 关闭、焦点返回触发角标；移动端底部滑出。

### 7.5 结构化卡片

`done` 后按 citations 去重，批量请求详情接口回填；单卡失败显示错误占位与「重试」，不影响正文。

- **方剂卡**：数据来自 `/api/formulas/:id`。四列固定「药味 / 克数 / 古制原量 / 换算留痕」，默认克；切到古制时整列替换并在表尾标 `1两≈15g`。
  - `dose_state=approx`：克数列 `~{g}g` + 橙牌；tooltip 出 `conversion_note`。
  - `count_only / unknown_unit / absent`：克数列 `—`，tooltip 出中文状态与 `conversion_note`。
  - `dose_complete=false`：表头挂「本方剂量不完全可执行」。
  - 变体徽章读 `pairs`：无配对=蓝「未交叉校验」；`herb_diff` 为空=灰勾；有差异=黄牌并展开逐行差异。
  - 加减方（`lineage.parent` 非空）：卡顶显示母方链接，不把母方当成本方变体。
- **中药卡**：性味/功效/主治/禁忌分节；五味、五脏 chip 链接到 `/herbs?taste_group=…`、`/herbs?organ_group=…`；`flavor_state=missing` 显示「本经未载性味」。
- **穴位卡**：按经络分组、角色徽标（五输/原/络/郄/募）；主穴/配穴层次暂不呈现（M3 未上 wire，见 §13）。
- **医案卡**：问→答→治→要诀，默认展开问/治；「同病类医案」链接到 `/cases?category=…`。
- 卡片与整轮回答支持复制 Markdown / 导出；导出物带免责与出处尾注（NFR-5）。

### 7.6 拒答卡

触发：`status=refused`。

- 固定文案「本地库未收录「××」」+ top_score + 已检索库摘要。
- 候选 chips（`answer.candidates`，≤3）：点击填入输入框并直接发送。
- 「在原文 `text/` 搜一下」按钮：置灰，tooltip「原文检索 FR-14 将在 M5 开放」。
- 正文区为空，不渲染 prose。

### 7.7 会话侧栏

- 挂载时与每轮 `done` 后拉取 `GET /api/chat/sessions`；当前会话高亮。
- 新建：跳 `/chat`；首次提问拿到 id 后更新 URL 并刷新列表。
- 删除：二次确认 → `DELETE`；若删的是当前会话则跳 `/chat`。
- 打开历史：`GET /api/chat/:id` 回放 user/assistant 消息；assistant 消息直接用存储的 `Answer` 渲染正文、角标、卡片（不为回放重新提问）。

### 7.8 停止与重试

- 生成中显示「停止」；点击 `AbortController.abort()`，保留已出 token，气泡标「已中断」。
- 首个 token 前网络失败：自动重试 1 次；仍失败或已出 token：显示「重试」按钮（重发会新增一轮，不伪装断点续传）。

### 7.9 快捷追问

M4 不生成额外追问 chips；仅当 `answer.followup` 非空时渲染问诊卡（§8）。「该方剂量换算 / 配穴方案」类 chips 留 M5。

---

## 8. 问诊卡

### 8.1 触发

`answer.followup` 非空时，在回答末尾插入问诊卡（非弹窗，可跳过）。`followup` 的三条后端问题作为卡片引导语展示。

### 8.2 字段

- 第一屏「七条基准」：额凉手足温 / 胃口 / 睡眠 / 大便 / 小便 / 精神 / 脉；每项三态开关：`正常 / 异常 / 不清楚`。选「异常」展开一行自由文本。
- 第二屏「十问」：寒热 / 汗 / 头身 / 便 / 饮 / 胸 / 冷 / 别 / 妇 / 声；同样三态 + 展开文本。
- 只问缺失项：已能从当前问题或历史对话提取的项预填，并标「已从您的描述提取」。

### 8.3 预填

- 前端维护确定性关键词表（如「怕冷/恶寒」→寒热、「汗出/无汗」→汗、「大便/便秘/溏」→便、「口渴/饮水」→饮），只做字符串命中。
- 预填仅影响初始值，用户可改；不生成任何诊断结论。

### 8.4 提交

把表单拼成结构化主诉摘要，作为一条新的用户消息发送：

```
主诉补充（问诊卡）：
基准：额凉手足温=正常；胃口=异常（饭后胀）；睡眠=不清楚；……
十问：寒热=恶寒；汗=无汗；头身=头痛；……
```

摘要逐项保留来源（本轮填写 / 历史提取）；提交后清空表单并重新进入辨证链。

### 8.5 跳过

关闭卡片，并在当前回答顶部标注「基于不完整信息，以下辨证仅供参考」；答案内容不改写。

### 8.6 键盘

Tab 遍历三态开关，空格切换，Enter 提交；Tabs 用方向键切换；焦点可见；不依赖鼠标。

---

## 9. 四大库

### 9.1 列表通用

- 顶部检索框：debounce 250ms 调 `POST /api/search`；下拉按 `match` 分组（`exact` 精确 / `literal` 字面 / `vector` 语义相关），精确与字面组优先；回车提交到列表（写 `q` query）。
- 左侧筛选面即时生效，全部同步 URL；提供「复制当前筛选链接」。
- 列表行只显示主名、出处摘要、徽标；点击进详情。
- 空状态：「换个筛选」+「去对话页问」；错误态可重试。

### 9.2 方剂库

- 筛选：`q`、`six_jing`（多选）、`source_doc`、`status`、`kind`、`herb`（组成反查）；分页 `limit=20`。
- `candidate` 行灰显并标「身份待确认」。
- 「是否含交叉校验差异」筛选 M4 不做（列表接口无该字段，见 §13）；详情页仍有变体徽章。

### 9.3 中药库

- 筛选：`q`、`taste_group`（多选）、`organ_group`、`flavor_state`；分页。
- 列表显示性味、五味/五脏 chip、含方数。

### 9.4 针灸库

- 筛选：`q`、`meridian`、`role`、`symptom`；分页。
- 列表显示经络、角色徽标、主治摘要、症状数。

### 9.5 医案库

- 筛选：`q`、`category`；分页。
- 列表显示医案号、病类、主诉、治疗方 links。

### 9.6 详情页

- 基本信息卡 + 组成/功效分节 + 原文节选（衬线引用块）+ 校验明细 + 关联推荐。
- 方剂详情：克↔古制开关与对话卡共用 `lib/dose.ts`；变体列表严格按 API 返回，不把加减方并入母方变体；差异行逐条展开。
- 页面底部免责条（与全局底栏并存）。

### 9.7 「就本条提问」

- 方/药/穴/案详情固定按钮 → `/chat?ref=formula:61`。
- 对话页读取 `ref`，用 `GET /api/evidence/{ref}` 取标题与首条出处，预填输入框「关于 桂枝汤（伤寒论·太阳篇）：」；用户可改后发送。
- 不自动发送，避免误触产生无意义问答。

---

## 10. 视觉与无障碍

- 色板：宣纸底 `#F6F1E7`、墨色主文 `#1F2328`、朱砂强调 `#A23B2A`、分隔线 `#D8CDB8`。正文/背景对比度 ≥4.5:1。
- 字体：古籍引文用衬线系统栈（`Songti SC`、`Noto Serif CJK SC`、`serif`）；白话用无衬线系统栈；不下载 webfont。
- 焦点：所有交互元素可见 focus ring；抽屉焦点陷阱、Esc 关闭、关闭后焦点回到触发点；提供 skip link。
- 流式文本不逐 token 播报；`aria-live="polite"` 只在完成/拒答/错误时播报。
- 问诊表单纯键盘可完成；对比度与 form 可访问性用 axe 自动检查。

---

## 11. 后端改动清单

| 文件 | 改动 |
|---|---|
| `backend/app/api/chat.py` | 新增 `GET /api/chat/sessions`（注册在 `/{session_id}` 之前）、`DELETE /api/chat/{session_id}` |
| `backend/app/rag/service.py` | `stream_events` 增加 `progress`、`error`；首个 token 前提交事务 |
| `backend/app/api/chat.py` | `chat_stream` 配合事务调整，异常时发 `error` 事件而非中断连接 |
| `backend/app/api/formulas.py` | `six_jing` 多值、`source_doc` 筛选 |
| `backend/app/api/herbs.py` | `taste_group` 多值 |
| `backend/tests/db/test_chat_api.py` | 会话列表排序/标题、删除后 `qa_log` 保留、SSE 事件顺序 |
| `backend/tests/db/test_formula_api.py`、`test_library_api.py` | 多值/`source_doc` 筛选 |
| `backend/scripts/e2e_bootstrap.py` | 仅当 `DATABASE_URL` 库名含 `e2e` 时建扩展/表/索引并 reindex；否则拒绝运行 |

说明：`Answer` schema 不变；`doses`、`cards`、`dose_complete` 等现有字段口径不变。

---

## 12. 测试策略与验收

### 12.1 Vitest + RTL + MSW（离线）

- 角标去重编号与标题匹配定位。
- 剂量四态渲染：exact / approx（`~`+橙牌）/ count_only / unknown_unit / absent；`dose_complete=false` 提示。
- 拒答卡：candidates chips、置灰兜底按钮、无正文。
- 问诊卡：三态切换、预填、提交摘要文本、跳过标注。
- URL 筛选序列化/反序列化（多值、分页、空值）。
- `general_note` 灰框样式与无角标。
- SSE 解析器：分帧、未知事件、错误事件、中断。

### 12.2 Playwright（真实后端 + e2e 库）

启动方式：`e2e_bootstrap.py` 准备库 → `uvicorn` 起后端 → `next dev` 起前端；Playwright `webServer` 数组管理。

必须覆盖：

1. 提问「咳嗽气喘痰白不能平躺」：状态机流转、意图徽章、流式、角标、抽屉显示问11原文高亮。
2. 提问库外方名：拒答卡 + candidates chips + 置灰原文兜底按钮，正文为空。
3. 方剂卡克↔古制切换，数值与 `/formulas/:id` 详情一致。
4. 检索「柴胡」与「牡桂」：都命中同一条中药记录，且落在精确匹配组（古名/别名归一）。
5. 打开桂枝汤详情：变体列表不含桂枝加葛根汤/桂枝加厚朴杏仁汤。
6. 五苓散 / 一物瓜蒂汤详情：非 exact 克数为 `—`/`~`，页面无臆造克数，顶部有不完全提示。
7. 四大库任一筛选组合刷新后保持（URL 同步）。
8. 问诊卡纯键盘完成提交，生成主诉摘要并触发新一轮。
9. 免责条在对话、详情、复制导出物三处出现。
10. axe 扫描对话页与详情页：无 serious/critical 对比度或表单可访问性问题。

### 12.3 风险验证任务（前置）

在正式页面开工前，先做一个最小 SSE 穿透验证：Next rewrite 代理下 `meta/progress/token/done` 是否逐帧到达。若不穿透，切换为浏览器直连后端 + FastAPI CORS，并记录到实现计划。

### 12.4 §6.7 映射

| §6.7 验收项 | 方式 | 备注 |
|---|---|---|
| 1 咳喘样例全流程 + 角标 + 问11 高亮 | Playwright | 核心用例 |
| 2 拒答卡 + chips + 原文兜底按钮 | Playwright | 兜底按钮为置灰态（FR-14 留 M5） |
| 3 方剂卡克/古制一致 | Playwright | 与详情页对比 |
| 4 柴胡/牡桂 精确匹配 | Playwright | 依赖现有检索 |
| 5 桂枝汤变体列表身份纪律 | Playwright | 依赖现有详情 API |
| 6 五苓散/一物瓜蒂汤剂量诚实 | Playwright | 无臆造克数 |
| 7 `general_note` 灰框区分 | Vitest | M3 恒为 null，无真实数据 |
| 8 问诊卡三态/摘要/跳过 | Playwright | 键盘路径 |
| 9 四库 URL 同步 | Playwright | 刷新保持 |
| 10 免责三处 + 键盘 + 对比度 | Playwright + axe | 对比度自动 + 人工复核 |

验收结果在 M4 完成后写入 `docs/需求文档-RAG系统.md` 的 M4 行，并附命令与计数。

---

## 13. 已知边界与偏差

1. **FR-14 原文兜底未实现**：按钮存在但置灰，M5 开放。
2. **`general_note` 无真实数据**：M3 恒为 null，仅组件测试覆盖样式。
3. **检索进度非阶段实时**：后端在检索完成后一次性发出 `progress`；前端阶段文案是本地状态过渡，不声称逐阶段服务端推送。
4. **角标无 sentence offset**：按标题子串挂到行尾，未命中则挂正文末尾；不做逐句语义对齐。
5. **停止后的历史**：事务在首个 token 前提交，历史回放显示完整回答，而不是中断时的部分文本。
6. **穴位主/配层次**：M3 未把取穴 `logic` 上 wire，卡片只显示角色与经络，不推断主配。
7. **方剂「交叉校验差异」筛选**：列表接口无该字段，M4 不做。
8. **会话不重命名**；反馈、框架页、管理页、compose、鉴权、生产建表均留 M5。
9. **无真实 LLM**：prose 为 FakeLlm 拼接；M4 终态以 `sections` 为正文口径。
10. **单轮快速追问 chips**：M4 不生成，只保留问诊卡。

---

## 14. 文件结构

```
frontend/
  package.json
  next.config.ts
  postcss.config.mjs
  tsconfig.json
  playwright.config.ts
  vitest.config.ts
  .env.example
  app/
    layout.tsx
    globals.css
    page.tsx                     -> redirect /chat
    chat/page.tsx
    chat/[sessionId]/page.tsx
    formulas/page.tsx
    formulas/[id]/page.tsx
    herbs/page.tsx
    herbs/[id]/page.tsx
    acupoints/page.tsx
    acupoints/[id]/page.tsx
    cases/page.tsx
    cases/[id]/page.tsx
    framework/page.tsx           # M5 占位
    admin/page.tsx               # M5 占位
  components/
    shell/AppHeader.tsx  DisclaimerBar.tsx
    chat/ChatPanel.tsx  MessageBubble.tsx  Composer.tsx  IntentBadge.tsx
         RetrievalProgress.tsx  SessionSidebar.tsx  CitationSup.tsx
    drawer/EvidenceDrawer.tsx
    cards/FormulaCard.tsx  HerbCard.tsx  AcupointCard.tsx  CaseCard.tsx
          DoseToggle.tsx  VariantBadge.tsx
    intake/IntakeCard.tsx
    library/LibraryShell.tsx  FilterPanel.tsx  SearchSuggest.tsx  ResultRow.tsx
  lib/
    api.ts  types.ts  sse.ts  citations.ts  dose.ts  intake.ts  filters.ts  format.ts
  tests/unit/*.test.ts(x)
  e2e/*.spec.ts
```

后端新增：`backend/scripts/e2e_bootstrap.py`。

---

## 15. 交付顺序

1. SSE 穿透验证（rewrite vs CORS）+ 前端脚手架与全局壳。
2. 后端最小补口（会话列表/删除、progress/error、多值筛选）+ pytest。
3. 对话页：状态机、流式正文、角标、抽屉。
4. 卡片（方/药/穴/案）+ 拒答卡。
5. 问诊卡 + 会话侧栏 + 停止/重试。
6. 四大库列表（URL 同步、联想）+ 详情页 + 就本条提问。
7. 视觉/无障碍收尾、复制导出。
8. Vitest 补全 + Playwright §6.7 验收 + 文档记录。
