export const SEVEN_BASELINES = ["额凉手足温", "胃口", "睡眠", "大便", "小便", "精神", "脉"] as const;
export const TEN_QUESTIONS = ["寒热", "汗", "头身", "便", "饮", "胸", "冷", "别", "妇", "声"] as const;

export type TriState = "normal" | "abnormal" | "unknown" | "";
export interface IntakeField {
  key: string;
  state: TriState;
  note: string;
  source: "typed" | "history" | null;
}
export interface IntakeDraft {
  baselines: IntakeField[];
  questions: IntakeField[];
}

type Polarity = "normal" | "abnormal";

// 每个 token 带极性；同一 key 内异常词排在正常词之前，显式异常优先命中。
// 已移除「胃口/精神/大便/小便/睡眠/脉」等裸词，避免「胃口好」「大便正常」被强制判为异常。
const KEYWORDS: Record<string, [string, Polarity][]> = {
  额凉手足温: [["手足冷", "abnormal"], ["额凉", "normal"], ["手足温", "normal"]],
  胃口: [["纳差", "abnormal"], ["不想吃", "abnormal"], ["食欲不振", "abnormal"], ["胃口好", "normal"], ["食欲好", "normal"]],
  睡眠: [["失眠", "abnormal"], ["多梦", "abnormal"], ["易醒", "abnormal"], ["睡眠正常", "normal"]],
  大便: [["便秘", "abnormal"], ["腹泻", "abnormal"], ["便溏", "abnormal"], ["大便正常", "normal"]],
  小便: [["尿频", "abnormal"], ["夜尿", "abnormal"], ["尿少", "abnormal"], ["小便正常", "normal"]],
  精神: [["乏力", "abnormal"], ["疲倦", "abnormal"], ["疲乏", "abnormal"], ["精神好", "normal"]],
  脉: [["脉浮", "abnormal"], ["脉沉", "abnormal"], ["脉数", "abnormal"], ["脉细", "abnormal"], ["脉弦", "abnormal"]],
  寒热: [["恶寒", "abnormal"], ["怕冷", "abnormal"], ["畏寒", "abnormal"], ["发热", "abnormal"], ["发烧", "abnormal"], ["寒热", "abnormal"]],
  汗: [["汗出", "abnormal"], ["无汗", "abnormal"], ["自汗", "abnormal"], ["盗汗", "abnormal"], ["出汗", "abnormal"]],
  头身: [["头痛", "abnormal"], ["头项", "abnormal"], ["身痛", "abnormal"], ["项强", "abnormal"], ["眩晕", "abnormal"]],
  便: [["便秘", "abnormal"], ["腹泻", "abnormal"], ["便溏", "abnormal"]],
  饮: [["口渴", "abnormal"], ["饮水", "abnormal"], ["口干", "abnormal"], ["不渴", "normal"]],
  胸: [["胸闷", "abnormal"], ["胸痛", "abnormal"], ["心悸", "abnormal"], ["胁痛", "abnormal"]],
  冷: [["手足冷", "abnormal"], ["四肢冷", "abnormal"], ["畏寒肢冷", "abnormal"]],
  别: [["月经", "abnormal"], ["经期", "abnormal"], ["带下", "abnormal"]],
  妇: [["月经", "abnormal"], ["经期", "abnormal"], ["带下", "abnormal"], ["产后", "abnormal"]],
  声: [["声低", "abnormal"], ["声嘶", "abnormal"], ["懒言", "abnormal"]],
};

export const TRI_LABELS: Record<Exclude<TriState, "">, string> = {
  normal: "正常",
  abnormal: "异常",
  unknown: "不清楚",
};

function field(key: string, text: string): IntakeField {
  const hit = (KEYWORDS[key] ?? []).find(([word]) => text.includes(word));
  return hit
    ? { key, state: hit[1], note: hit[0], source: "typed" }
    : { key, state: "", note: "", source: null };
}

export function prefillIntake(text: string): IntakeDraft {
  return {
    baselines: SEVEN_BASELINES.map((key) => field(key, text)),
    questions: TEN_QUESTIONS.map((key) => field(key, text)),
  };
}

function line(fieldValue: IntakeField): string | null {
  if (!fieldValue.state) return null;
  const note = fieldValue.state === "abnormal" && fieldValue.note
    ? `（${fieldValue.note}）` : "";
  const source = fieldValue.source === "typed" ? "〔提取〕"
    : fieldValue.source === "history" ? "〔历史〕" : "";
  return `${fieldValue.key}=${TRI_LABELS[fieldValue.state]}${note}${source}`;
}

export function formatIntakeSummary(draft: IntakeDraft): string {
  const collect = (fields: IntakeField[]) =>
    fields.map(line).filter((item): item is string => Boolean(item)).join("；");
  return `主诉补充（问诊卡）：\n基准：${collect(draft.baselines)}\n十问：${collect(draft.questions)}`;
}
