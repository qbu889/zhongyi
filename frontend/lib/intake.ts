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

const KEYWORDS: Record<string, string[]> = {
  额凉手足温: ["额凉", "手足温", "手足冷"],
  胃口: ["胃口", "纳差", "食欲", "不想吃"],
  睡眠: ["睡眠", "失眠", "多梦", "易醒"],
  大便: ["大便", "便秘", "腹泻", "便溏"],
  小便: ["小便", "尿频", "夜尿", "尿少"],
  精神: ["精神", "乏力", "疲倦", "疲乏"],
  脉: ["脉浮", "脉沉", "脉数", "脉细", "脉弦"],
  寒热: ["恶寒", "怕冷", "畏寒", "发热", "发烧", "寒热"],
  汗: ["汗出", "无汗", "自汗", "盗汗", "出汗"],
  头身: ["头痛", "头项", "身痛", "项强", "眩晕"],
  便: ["大便", "便秘", "腹泻", "便溏"],
  饮: ["口渴", "饮水", "口干", "不渴"],
  胸: ["胸闷", "胸痛", "心悸", "胁痛"],
  冷: ["手足冷", "四肢冷", "畏寒肢冷"],
  别: ["月经", "经期", "带下"],
  妇: ["月经", "经期", "带下", "产后"],
  声: ["声低", "声嘶", "懒言"],
};

export const TRI_LABELS: Record<Exclude<TriState, "">, string> = {
  normal: "正常",
  abnormal: "异常",
  unknown: "不清楚",
};

function field(key: string, text: string): IntakeField {
  const word = (KEYWORDS[key] ?? []).find((item) => text.includes(item));
  return word
    ? { key, state: "abnormal", note: word, source: "typed" }
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
