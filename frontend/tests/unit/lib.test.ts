import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { citationKey, numberCitations, numbersForLine, unmatchedCitations } from "@/lib/citations";
import { doseCell } from "@/lib/dose";
import { answerToMarkdown } from "@/lib/export";
import { buildQuery, pageFrom, pageHref } from "@/lib/filters";
import { formatIntakeSummary, prefillIntake } from "@/lib/intake";
import { parseSseFrame, streamChat } from "@/lib/sse";
import type { Citation, MetaEvent, Section } from "@/lib/types";

const citations: Citation[] = [
  { ref_type: "case", ref_id: 11, title: "问11", anchor: "医案#问11", snippet: "咳" },
  { ref_type: "formula", ref_id: 61, title: "射干麻黄汤", anchor: "方#61", snippet: "咳" },
  { ref_type: "case", ref_id: 11, title: "问11", anchor: "医案#问11", snippet: "咳" },
];

describe("citations", () => {
  it("dedupes by ref and numbers in order", () => {
    const numbers = numberCitations(citations);
    expect([...numbers.values()]).toEqual([1, 2]);
    expect(numbers.get(citationKey(citations[2]))).toBe(1);
  });

  it("attaches numbers to lines containing the title", () => {
    const numbers = numberCitations(citations);
    const line = "治：射干麻黄汤、乌梅丸";
    expect(numbersForLine(line, citations, numbers)).toEqual([2]);
  });

  it("reports citations not found in any line", () => {
    const sections: Section[] = [{ title: "定方", lines: ["治：射干麻黄汤"] }];
    expect(unmatchedCitations(sections, citations).map(citationKey)).toEqual(["case:11"]);
  });
});

describe("dose", () => {
  it("renders exact, approximate and missing doses", () => {
    expect(doseCell({ dose_g: 45, dose_state: "exact" })).toEqual({ text: "45g", tone: "exact" });
    expect(doseCell({ dose_g: 15, dose_state: "approx" })).toEqual({ text: "~15g", tone: "approx" });
    expect(doseCell({ dose_g: null, dose_state: "unknown_unit" })).toEqual({ text: "—", tone: "none" });
  });
});

describe("filters", () => {
  it("serializes repeated values and pages", () => {
    expect(buildQuery({ q: "桂枝", six_jing: ["太阳", "阳明"], offset: 0 }))
      .toBe("?q=%E6%A1%82%E6%9E%9D&six_jing=%E5%A4%AA%E9%98%B3&six_jing=%E9%98%B3%E6%98%8E");
    const sp = new URLSearchParams("q=桂枝&page=3");
    expect(pageFrom(sp)).toBe(3);
    expect(pageHref("/formulas", sp, 1)).toBe("/formulas?q=%E6%A1%82%E6%9E%9D");
  });
});

describe("intake", () => {
  it("prefills matched symptoms and formats a summary", () => {
    const draft = prefillIntake("怕冷，无汗，大便溏");
    const filled = draft.questions.filter((f) => f.state === "abnormal");
    expect(filled.map((f) => f.key)).toEqual(expect.arrayContaining(["寒热", "汗", "便"]));
    const summary = formatIntakeSummary(draft);
    expect(summary).toContain("主诉补充（问诊卡）");
    expect(summary).toContain("寒热=异常");
  });

  it("labels explicit normal findings as normal, not abnormal", () => {
    const draft = prefillIntake("不渴，手足温，胃口好，大便正常");
    const byKey = [...draft.baselines, ...draft.questions];
    for (const key of ["饮", "额凉手足温", "胃口", "大便"]) {
      expect(byKey.find((f) => f.key === key)?.state).toBe("normal");
    }
    expect(byKey.filter((f) => f.state === "abnormal")).toEqual([]);
    const summary = formatIntakeSummary(draft);
    expect(summary).toContain("饮=正常");
    expect(summary).not.toContain("饮=异常");
  });
});

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("sse", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses event/data frames and ignores comments", () => {
    expect(parseSseFrame('event: meta\ndata: {"session_id":1}'))
      .toEqual({ event: "meta", data: { session_id: 1 } });
    expect(parseSseFrame("data: a\ndata: b")).toEqual({ event: "message", data: "a\nb" });
    expect(parseSseFrame(": ping")).toBeNull();
  });

  it("delivers frames split across chunks and resolves on done", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      'event: meta\ndata: {"session_id":7,"intent":"B","status":"answered"}\n\nevent: token\ndata: {"text":"桂枝"}\n\nevent: tok',
      // done 帧没有末尾空行，仍应被 flush 并视为正常结束
      'en\ndata: {"text":"汤"}\n\nevent: done\ndata: {"session_id":7,"message_id":1,"answer":{}}',
    ])));
    const tokens: string[] = [];
    let meta: MetaEvent | null = null;
    let done: unknown = null;
    await streamChat("q", null, {
      onMeta: (value) => { meta = value; },
      onToken: (text) => tokens.push(text),
      onDone: (value) => { done = value; },
    });
    expect(meta).toMatchObject({ session_id: 7 });
    expect(tokens.join("")).toBe("桂枝汤");
    expect(done).toEqual({ session_id: 7, message_id: 1, answer: {} });
  });

  it("rejects a stream that ends without a terminal frame", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      'event: meta\ndata: {"session_id":7,"intent":"B","status":"answered"}\n\n',
    ])));
    const error = await streamChat("q", null, {}).catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("stream_truncated");
  });
});

describe("export", () => {
  it("includes sections, citations and the server disclaimer", () => {
    const md = answerToMarkdown({
      intent: "B", status: "answered", headline: "桂枝汤",
      sections: [{ title: "组成", lines: ["桂枝 45g（三两）"] }],
      citations: [{ ref_type: "formula", ref_id: 61, title: "桂枝汤", anchor: "方#61", snippet: "" }],
      dose_complete: true, candidates: [], followup: [], general_note: null,
      disclaimer: "免责声明", prose: "", top_score: 1,
    });
    expect(md).toContain("### 组成");
    expect(md).toContain("[1] 桂枝汤（方#61）");
    expect(md).toContain("免责声明");
  });
});
