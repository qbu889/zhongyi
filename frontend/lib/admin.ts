/** /api/admin/* 客户端。类型一律以后端真实响应为准（backend/app/api/admin.py 与各
 * asdict/model_dump 出处），不照抄计划文本——计划旧稿里 `POST /session` 的 `{ok:true}`、
 * 日志端点不回显钳制参数等都是过时描述。 */
import { ApiError, parseApiError } from "./api";

/** GET/POST /api/admin/session：`_session_state()` 与 login 返回都只有这三个键。 */
export interface AdminSession { enabled: boolean; authenticated: boolean; expires_at: number | null }

/* —— 质量报告 GET /quality-report（asdict(admin.quality.QualityReport)）—— */
/** index_version 有两种形态：无 ready 版本时后端只给 `{id:null, status:"no-ready-index"}`，
 * 其余键缺席，故除 id/status 外全部可选。 */
export interface QualityIndexVersion {
  id: number | null;
  status: string;
  commit_hash?: string;
  embedding_model_version?: string;
  chunking_version?: string;
  extract_rule_version?: string;
  chunk_count?: number;
  notes?: Record<string, unknown>;
}
export interface HerbDiffRow {
  formula: string; pair_id: number;
  missing_in_gram: string[]; missing_in_ancient: string[];
}
/** 三键齐全**只**由 `verify.py:98-99`（`_dose_deviations`）这一条生成路径保证：那里先有
 * `if item.dose_g is None: continue` 与 `if not gram_g: continue` 两道过滤，落库的 dict 恒为
 * 三键且非空；`loaders.py:232/236` 原样搬运 `p.dose_dev`——**生产路径**唯一写者就是这一条。
 * 后端读它时用
 * `.get(..., "")`（`admin.py:405-406` 的 CSV 单元格）和 `.get(..., 0)`（`quality.py:75` 的
 * `worst_pct` 取最大值），那是"缺键不把端点炸成 500"的兜底，不是对键可缺席的背书。
 * 非该路径写入的行不受这条保证保护，且仓库里确实存在这种行：测试夹具
 * `test_models_roundtrip.py:103` 往同一列直写 `dose_dev={"麻黄": 100.0}`（值甚至不是 dict）。
 * 选择保持必填而非改可选：消费端（T12 的三列数字与 `worst_pct` 排序）拿到 `undefined` 也只能
 * 渲染成空白单元格，与异常数据现在的表现相同，却等于把"后端不认自己的契约"写进类型层。 */
export interface DoseDeviationEntry { ancient_g: number; gram_g: number; deviation_pct: number }
export interface DoseDeviationRow {
  formula: string; pair_id: number;
  items: Record<string, DoseDeviationEntry>; worst_pct: number;
}
export interface ParseFailureRow { reason: string; count: number }
/** details 的 reason 在 ORM 上可空（CSV 端点也按 `r["reason"] or ""` 处理），聚合行不会为 null。 */
export interface ParseFailureDetailRow {
  raw_name: string; doc: string; source_row_no: number | null;
  reason: string | null; decision: string;
}
export interface AnnotationItemRow { herb_text: string; variant_id: number; formula_item_id: number }
export interface DanglingHerbs { rows: number; distinct_terms: number; top: [string, number][] }
export interface PendingQueueSummary {
  total: number; by_decision: Record<string, number>; by_reason: Record<string, number>;
}
/** build_quality_report 的 counters 七键；session.scalar(count) 恒为 int。 */
export interface QualityCounters {
  herb_total: number; herb_without_taste: number; herb_without_flavor: number;
  formula_total: number; variant_gram: number; variant_ancient: number; item_total: number;
}
export interface QualityReport {
  index_version: QualityIndexVersion;
  herb_diff: HerbDiffRow[];
  dose_deviation: DoseDeviationRow[];
  parse_failures: ParseFailureRow[];
  parse_failure_details: ParseFailureDetailRow[];
  annotation_items: AnnotationItemRow[];
  dangling_herbs: DanglingHerbs;
  /** 固定五档：exact / approx / count_only / absent / unknown_unit。 */
  dose_state_distribution: Record<string, number>;
  pending_queue: PendingQueueSummary;
  counters: QualityCounters;
}

/* —— 候选方名 GET/POST /pending*（PendingItem 的 pydantic dump；datetime 序列化为字符串）—— */
export interface PendingItem {
  id: number; raw_name: string; doc: string; source_row_no: number | null;
  suggested_parent: string | null; confidence: number | null; evidence_text: string | null;
  reason: string | null; decision: string; decided_by: string | null;
  decided_at: string | null; decided_name: string | null;
}
/** limit 是后端钳制到 [1,200] 后的实际生效值（list_pending 的 docstring）。 */
export interface PendingList { total: number; limit: number; offset: number; items: PendingItem[] }
/** POST /pending/{id}/decision：merged 时 alias_created 为布尔，其余动作后端给 null。 */
export interface DecisionResult { item: PendingItem; alias_created: boolean | null }

/* —— 重建 POST /reindex（asdict(reindex.ReindexReport)）。dataclass 字段带默认值，
 * asdict 永远输出全部键：reused=true 的短路路径上 counts/skipped 是空 dict、其余是 0，
 * 所以这里全部声明为必存在，不照抄计划文本里的可选写法。 —— */
export interface ReindexReport {
  version_id: number; commit_hash: string; status: string; reused: boolean;
  embedding_model_version: string;
  counts: Record<string, number>; skipped: Record<string, number>;
  chunks: number; noise_tokens: number; dangling_herb_items: number; elapsed_ms: number;
}

/* —— GET /index-versions / GET /reindex/preview（admin.py 的 _version_item 单点形状）—— */
export interface IndexVersionInfo {
  id: number; status: string; commit_hash: string;
  formula_count: number; herb_count: number; acupoint_count: number; case_count: number;
  chunk_count: number; embedding_model_version: string;
  chunking_version: string; extract_rule_version: string;
  notes: Record<string, unknown>; created_at: string | null;
}
export interface IndexVersions {
  current: IndexVersionInfo | null; target_commit_hash: string; versions: IndexVersionInfo[];
}
/** build_corpus() 返回字典的原样键（backend/app/admin/reindex.py:97-110，共 11 个）。
 * 收进类型层而不是 `Record<string, number>`：组件里 `corpus_counts` 的每一次读取都是点号
 * 访问，错键（`herb` 少个 s）在 Record 下合法、只会静默渲染成占位符"—"；具名可选键让写错
 * 键变成编译错误。全部可选——后端新增语料源时不该炸前端，但**不许**退回开放索引签名。
 * 草药键是复数 `herbs`。 */
export interface ReindexCorpusCounts {
  herbs?: number; vocab?: number; ancient?: number; classic?: number; evidence?: number;
  framework?: number; cases?: number; acupoints?: number; acupoint_symptoms?: number;
  pairs?: number; aliases?: number;
}
export interface ReindexPreview {
  changed: boolean; will_reuse: boolean; target_commit_hash: string;
  /** changed/will_reuse 与 POST /reindex 非 force 的四元组复用谓词同一口径。 */
  corpus_counts: ReindexCorpusCounts;
  current: IndexVersionInfo | null;
}

/* —— 问答日志（GET /logs/summary /logs/refusals /logs）。回显钳制后的 window_days/limit/offset —— */
export interface LogsSummary {
  queries_total: number; queries_recent: number; refusal_rate: number; avg_hit_count: number;
  window_days: number;
}
export interface RefusalRow { query: string; count: number; top_score_max: number | null }
export interface RefusalList { window_days: number; limit: number; items: RefusalRow[] }
export interface LogItem {
  id: number; created_at: string | null; session_id: number | null; query: string;
  intent: string; refused: boolean; top_score: number | null; hit_count: number;
}
export interface LogList { total: number; limit: number; offset: number; items: LogItem[] }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    cache: "no-store",
    ...init,
    // 凭据策略写死在展开之后：规格 §13-10 唯一的 CSRF 边界是 `SameSite=Lax` + 全部写操作走
    // POST，而这条边界只在 cookie 真的随同源请求送达时才成立。它不该只活在 fetch 的隐式默认
    // 里，也不该由某个调用方的 init 悄悄降级成 omit/include。行为与改前一致（默认本就是
    // same-origin，当前没有任何调用方传 credentials）。
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) throw await parseApiError(res);
  return (await res.json()) as T;
}

export const adminProbe = () => request<AdminSession>("/api/admin/session");
export const adminLogin = (token: string) =>
  request<AdminSession>("/api/admin/session", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
  });
// logout 返回 204，没有 JSON 体：不能走会 res.json() 的 adminPost。
export const adminLogout = () => request<void>("/api/admin/session/logout", { method: "POST" });
export const adminGet = <T,>(path: string) => request<T>(path);
export const adminPost = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const adminCsvHref = (list: string) => `/api/admin/quality-report/export?list=${encodeURIComponent(list)}`;

/** 决策 422 的 code `invalid_decision_payload` **就在**这张表里（见下方），因此命中它的是闭集
 * 标签「参数不完整」，而端点按场景逐字段生成的具体 message（见 _invalid_payload，如
 * 「归并的 target_formula_id 必须是 ≥1 的整数，收到 …」）被**有意吞掉**、不会显示。
 * 注：表里没有的 code 才会落到后端原文——但 `invalid_decision_payload` 不属于这一类。
 * 「显示闭集标签 vs 透传后端原文」的取舍登记给 T16 判，本轮只更正注释、不改行为。 */
export const ADMIN_ERROR_LABELS: Record<string, string> = {
  admin_disabled: "管理端未启用：请设置 ADMIN_TOKEN（至少 16 字符）",
  admin_unauthorized: "口令不正确",
  reindex_in_progress: "已有重建在跑，请稍后再试",
  reindex_failed: "重建失败",
  corrupt_corpus_git_state: "读不到语料的 git 状态",
  invalid_export_list: "该清单不支持导出",
  pending_not_found: "该候选记录不存在",
  formula_not_found: "目标方不存在",
  invalid_decision_payload: "参数不完整",
};
export function adminErrorLabel(error: unknown): string {
  return error instanceof ApiError
    ? ADMIN_ERROR_LABELS[error.code] ?? error.message
    : "请求失败";
}

/** 数据端点 401 的谓词。`require_admin`（backend/app/api/admin.py:51）对过期会话回
 * `{code:"admin_unauthorized", message:"请先登录管理端"}`——与登录卡口令错误是同一个 code、
 * 不同的话术。cookie TTL 1800s，会话中途过期时任何 adminGet/adminPost 都可能带回这个 401；
 * 把它喂进 ADMIN_ERROR_LABELS 会对什么都没输的维护者说"口令不正确"。
 * 唯一正确反应：命中本谓词 → 调 AdminShell 提供的重新探针回登录态，**不查标签表**。
 * T11–T14 的页面一律复用本谓词，不各自重写 status===401 判断。 */
export const isAdminUnauthorized = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 401;
/** 门状态五值（规格 §9:123 把「未启用」与「加载失败」列为两条独立状态面、§11:152 要求
 * 「未启用 / 未登录 / 加载失败」是三态三文案，均不得合并）：
 * `checking` 探针在途；`unreachable` 探针失败且**不是** 503 admin_disabled（后端挂了、502、
 * 断网、非 JSON 响应体）——可重试、fail-closed；`disabled` 探针成功但 `enabled:false`，
 * 或后端点名的 503 `admin_disabled`；`locked` 已启用未登录；`ready` 已登录。
 * `unreachable` 与 `disabled` 的分界是本轮的实质：把两者合并会让维护者去查 `ADMIN_TOKEN`，
 * 而真正坏的是后端进程。 */
export type AdminGate = "checking" | "unreachable" | "disabled" | "locked" | "ready";

/** GET /pending 的两条通道（admin.py list_pending：缺省 decision 只回 decision=pending 的
 * 队列行，显式空串是唯一的"全量"通道）。拆成两个常量而不是让调用方裸拼 `?decision=`，
 * 是为了"要全量必须点名 PENDING_ALL_PATH"——误发空值在结构上就回不到默认通道。
 * 追加其余参数：PENDING_PATH 后用 `?`，PENDING_ALL_PATH 后用 `&`。 */
export const PENDING_PATH = "/api/admin/pending";
export const PENDING_ALL_PATH = "/api/admin/pending?decision=";
