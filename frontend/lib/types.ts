export type RefType = "formula" | "herb" | "evidence" | "case" | "acupoint" | "framework";
export type AnswerStatus = "answered" | "refused" | "needs_more_info";

export interface Citation {
  ref_type: RefType | string;
  ref_id: number;
  title: string;
  anchor: string;
  snippet: string;
}

export interface Section {
  title: string;
  lines: string[];
}

export interface Answer {
  intent: string;
  status: AnswerStatus;
  headline: string;
  sections: Section[];
  citations: Citation[];
  dose_complete: boolean | null;
  candidates: Citation[];
  followup: string[];
  general_note: string | null;
  disclaimer: string;
  prose: string;
  top_score: number | null;
}

export interface ChatResponse {
  session_id: number;
  message_id: number;
  answer: Answer;
}

export interface MetaEvent {
  session_id: number;
  intent: string;
  status: AnswerStatus;
}

export interface Progress {
  total: number;
  by_type: Record<string, number>;
}

export interface SessionItem {
  id: number;
  title: string;
  last_activity_at: string;
  message_count: number;
}

export interface SessionListResponse {
  total: number;
  limit: number;
  offset: number;
  items: SessionItem[];
}

export type StoredMessage =
  | { role: "user"; content: { text: string }; created_at: string }
  | { role: "assistant"; content: Answer; created_at: string };

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: Record<string, unknown>;
  created_at: string;
}

export interface ChatHistory {
  session_id: number;
  messages: ChatHistoryMessage[];
}

export interface EvidenceRef {
  ref_type: string;
  ref_id: number;
  anchor: string;
  text: string;
  fields: Record<string, unknown>;
}

export interface SearchHit {
  ref_type: string;
  ref_id: number;
  title: string;
  snippet: string;
  score: number;
  match: "exact" | "vector" | "literal" | string;
  anchor: string;
}

export interface SearchResponse {
  query: string;
  normalized_query: string;
  index_version: { id: number; commit_hash: string; embedding_model_version: string | null };
  hits: SearchHit[];
}

export interface DoseItem {
  herb_text: string;
  herb_name: string | null;
  dose_text: string | null;
  dose_g: number | null;
  dose_state: string;
  preparation: string | null;
  conversion_note: string | null;
}

export interface FormulaVariant {
  id: number;
  source_doc: string;
  dose_basis: string;
  ordinal: number;
  source_row_no: number | null;
  raw_composition: string | null;
  items: DoseItem[];
  dose_complete: boolean | null;
}

export interface FormulaPair {
  variant_a: number;
  variant_b: number;
  variant_a_source: string | null;
  variant_b_source: string | null;
  herb_diff: Record<string, unknown> | null;
  dose_dev: Record<string, unknown> | null;
  score: number | null;
  pairing_method: string;
  algorithm_version: string | null;
  verified_at: string | null;
}

export interface FormulaListItem {
  id: number;
  canonical_name: string;
  status: string;
  kind: string;
  anchor: string;
  variant_count: number;
  evidence_count: number;
  dose_complete: boolean | null;
}

export interface FormulaListResponse {
  total: number;
  limit: number;
  offset: number;
  items: FormulaListItem[];
}

export interface FormulaDetail {
  id: number;
  canonical_name: string;
  status: string;
  kind: string;
  anchor: string;
  note: string | null;
  aliases: { name: string; doc: string; kind: string }[];
  lineage: {
    parent: { id: number; canonical_name: string } | null;
    children: { id: number; canonical_name: string }[];
  };
  variants: FormulaVariant[];
  pairs: FormulaPair[];
  components: { id: number; canonical_name: string; items: DoseItem[] }[];
  evidence: {
    id: number; source_doc: string; six_jing: string | null; bing_duan: string | null;
    clause_no: string | null; formula_no: string | null; original_text: string | null;
  }[];
  cases: { id: number; no: string; category: string | null }[];
  dose_complete: boolean | null;
}

export interface HerbListItem {
  id: number;
  name: string;
  alias: string[];
  flavor: string | null;
  flavor_state: "present" | "missing";
  flavor_source_state: string;
  taste_group: string | null;
  organ_group: string | null;
  formula_count: number;
}

export interface HerbDetail extends HerbListItem {
  effects: string | null;
  indications: string | null;
  dosage_note: string | null;
  taboo: string | null;
  preparation: string | null;
  raw_note: string | null;
  formulas: { id: number; canonical_name: string }[];
}

export interface HerbListResponse {
  total: number;
  limit: number;
  offset: number;
  items: HerbListItem[];
}

export interface AcupointListItem {
  id: number;
  name: string;
  meridian: string | null;
  role: string | null;
  location: string | null;
  actions: string | null;
  symptom_count: number;
}

export interface AcupointDetail extends AcupointListItem {
  symptoms: { symptom: string; source_doc: string | null }[];
}

export interface AcupointListResponse {
  total: number;
  limit: number;
  offset: number;
  items: AcupointListItem[];
}

export interface CaseListItem {
  id: number;
  no: string;
  category: string | null;
  chief_complaint: string | null;
  treatment: string | null;
  treatment_formulas: { id: number; canonical_name: string }[];
  added_herbs: string[];
}

export interface CaseDetail extends CaseListItem {
  pathogenesis: string | null;
  tips: string | null;
  raw_md: string | null;
}

export interface CaseListResponse {
  total: number;
  limit: number;
  offset: number;
  items: CaseListItem[];
}
