import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminPendingPage from "@/app/admin/pending/page";
import { AdminShell } from "@/components/admin/AdminShell";
import { FormulaPicker } from "@/components/admin/FormulaPicker";
import { PendingTable } from "@/components/admin/PendingTable";
import { SearchSuggest } from "@/components/library/SearchSuggest";
import type { PendingItem, PendingList } from "@/lib/admin";

import { server } from "../msw/server";

/** 夹具按 `PendingItem` 的 11 键全量给（lib/admin.ts 对着后端 pydantic dump 逐键核过）；
 * 缺键在这里就是 typecheck 失败，不留"渲染层猜形状"的空间。 */
const item: PendingItem = {
  id: 1, raw_name: "甲", doc: "03-金匮/方剂库.md", source_row_no: 12, suggested_parent: null,
  confidence: 0.4, evidence_text: "出自《金匮》…", reason: "multi_name_row",
  decision: "pending", decided_by: null, decided_at: null, decided_name: null,
};
/** 指针 §1（R-M5-2 / §13-8 搬迁）：合成格显示与复制的都是这一串，逐字无装饰字符。 */
const PATH = "03-金匮/方剂库.md#12";
const list: PendingList = { total: 1, limit: 50, offset: 0, items: [item] };
const searchResponse = {
  query: "桂", normalized_query: "桂",
  index_version: { id: 1, commit_hash: "x", embedding_model_version: null },
  hits: [{ ref_type: "formula", ref_id: 9, title: "桂枝汤", snippet: "", score: 1, match: "exact", anchor: "方#9" }],
};
/** 判定响应的真实形状：`{item, alias_created}`（admin.py:311）。 */
const decisionResponse = (patch: Partial<PendingItem>, aliasCreated: boolean | null = null) => ({
  item: { ...item, ...patch }, alias_created: aliasCreated,
});
/** 登录门常量：页级用例走 AdminShell，必须先把探针装成已登录。 */
const signedIn = () => HttpResponse.json({ enabled: true, authenticated: true, expires_at: 1 });

/** 把"在途的那条迟到响应"推到终点再断言：轮转宏任务队列（0 延时，不等满任何 N 毫秒）并把
 * React 的工作队列排空，直到迟到那条**要么已落进视图、要么被守卫丢弃**，不留"它还没跑到"的第三种解释。
 * 它只负责测试侧的排空，不承担守卫职责（守卫是 page.tsx 的序号比对）；本仓库两次否决假定时器，这里也没有引入。 */
async function flushInFlightWork() {
  for (let round = 0; round < 4; round += 1) {
    await act(async () => {
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
  }
}

beforeEach(() => {
  // Vitest 5：简写箭头体的 beforeEach 会被当成 teardown，必须用块体（同 admin-panels.test）。
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/* ————————————————————————————————————————————
   指针 §1 + §2：源路径格与复制诚实性。
   本 describe 必须排在本文件最前、且第一例不用 userEvent——实测 user-event 14.6.8 的
   `setup()` 会把 `navigator.clipboard` 换成它自己的 Clipboard stub，并且 RTL 的
   `cleanup()` **不回收它**（同一文件后续用例仍能看到 writeText 且 resolve 成功）。
   所以"剪贴板不存在 → 如实播报失败"这条锁只在没有 userEvent 的用例里成立，
   下面第一例的前置断言就是排序漂移时会立刻变红的保险。
   ———————————————————————————————————————————— */
describe("PendingTable 源路径格（R-M5-2 / §13-8 搬迁到此）", () => {
  it("剪贴板不可用时只播报失败，绝不播报成功（本文件不 stub 的那条锁）", async () => {
    expect((navigator as { clipboard?: unknown }).clipboard).toBeUndefined();
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    const cell = within(screen.getByRole("table")).getAllByRole("cell")[1];
    // 用 fireEvent 而不是 userEvent：后者会装上 clipboard stub，把失败分支变成成功分支。
    fireEvent.click(within(cell).getByRole("button", { name: "复制源文件路径" }));

    expect(await within(cell).findByText("复制失败，请手动选择路径")).toBeInTheDocument();
    const status = within(cell).getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    // 闭集文案逐字（整串相等，不是子串）：失败时绝不出现"已复制"。
    expect(status.textContent).toBe("复制失败，请手动选择路径");
    expect(screen.queryByText(/已复制/)).not.toBeInTheDocument();
    // select-all 就是 §13-8 的降级方案本身：失败文案教的"手动选择"在屏上真能做到。
    expect(within(cell).getByText(PATH)).toHaveClass("select-all");
  });

  it("合成格四钉：列数=表头数、格内原样、不是链接、复制写入的内容与格内一致", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    // 与 T12 被搬走的那组断言同一写法：setup() 之后整只 navigator 换成最小 stub。
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);

    const table = screen.getByRole("table");
    // 钉 1：源文件与行号合成一格后，表头数与单元格数仍相等（不等会被 axe 判死）。
    expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
    const cells = within(table).getAllByRole("cell");
    expect(cells).toHaveLength(7);
    const cell = cells[1];
    // 钉 2：格内文本就是 `路径#行号` 原样。
    expect(within(cell).getByText(PATH)).toBeInTheDocument();
    // 钉 3：该格不是链接（浏览器打不开服务器本地文件、语料 0600，伪链接是超出证据的承诺）。
    expect(within(cell).queryByRole("link")).not.toBeInTheDocument();
    // 钉 4：复制按钮写入的内容与格内一致，装饰字符不得进复制内容。
    await user.click(within(cell).getByRole("button", { name: "复制源文件路径" }));
    expect(writeText).toHaveBeenCalledWith(PATH);
    expect(writeText.mock.calls[0][0]).toBe(within(cell).getByText(PATH).textContent);
    expect(await within(cell).findByText("已复制源路径")).toBeInTheDocument();
    expect(within(cell).getByRole("status").textContent).toBe("已复制源路径");
  });

  it("行号缺失（source_row_no 为 null）时格内只有路径，不留悬空 #", () => {
    render(<PendingTable items={[{ ...item, source_row_no: null }]} total={1} onChanged={() => {}} />);
    const cell = within(screen.getByRole("table")).getAllByRole("cell")[1];
    expect(within(cell).getByText("03-金匮/方剂库.md")).toBeInTheDocument();
    expect(within(cell).queryByText(/#/)).not.toBeInTheDocument();
  });
});

describe("PendingTable 三个判定动作", () => {
  it("归并需先选目标方：未选时确认按钮禁用、说明原因，且按下不发请求", async () => {
    const user = userEvent.setup();
    let posts = 0;
    server.use(http.post("/api/admin/pending/1/decision", () => {
      posts += 1;
      return HttpResponse.json(decisionResponse(
        { decision: "merged", decided_by: "admin", decided_at: "x", decided_name: null }, true));
    }));
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));

    const confirm = screen.getByRole("button", { name: "确认归并" });
    expect(confirm).toBeDisabled();
    expect(screen.getByText("请先选择目标方")).toBeInTheDocument();
    // 后端对缺失/空串的 target_formula_id 回 422 `invalid_decision_payload`（admin.py:262-265）；
    // 禁用 + 说明原因 = 不把维护者引向一条注定失败的写请求。
    // F-2.4（评审 Minor 收紧）：这里用 `fireEvent.click` 而不是 `user.click`——user-event 对 disabled
    // 目标直接跳过派发，`posts` 永远 0、断言不可能失败。fireEvent 把原生 click 打到 DOM 上，走组件自己的
    // 路径（React 对 disabled 按钮抑制 onClick），这条 `posts === 0` 才真的钉住 `disabled={!open.target}`。
    fireEvent.click(confirm);
    expect(posts).toBe(0);
  });

  it("确认独立方的表单里原话显示「仅登记，不建方」", async () => {
    const user = userEvent.setup();
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "确认为独立方" }));
    expect(screen.getByText(/仅登记，不建方/)).toBeInTheDocument();
    // 后端 confirmed_new 只写 decided_name，不建 formula 行（admin.py:278）——表单也不给建方暗示。
    expect(screen.getByText("仅登记，不建方：ETL 读取判定结果建方属下一轮范围。")).toBeInTheDocument();
  });

  it("判噪声需二次确认后才提交，且请求体只有 action", async () => {
    const user = userEvent.setup();
    const seen: unknown[] = [];
    server.use(http.post("/api/admin/pending/1/decision", async ({ request }) => {
      seen.push(await request.json());
      return HttpResponse.json(decisionResponse({ decision: "noise" }));
    }));
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "判为噪声" }));
    expect(seen).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "确认判噪声" }));
    await waitFor(() => expect(seen).toHaveLength(1));
    // 逐键相等：多发 `name: ""` 或 `note` 都会打在这里。`note` 后端接受但不落库（admin.py:243-244），
    // 所以表单里没有备注框——放一个会静默丢输入的字段是最糟的诚实性缺陷（指针 §5）。
    expect(seen[0]).toEqual({ action: "noise" });
  });

  it("确认独立方：规范名必填才提交，请求体是 {action, name}", async () => {
    const user = userEvent.setup();
    const seen: unknown[] = [];
    server.use(http.post("/api/admin/pending/1/decision", async ({ request }) => {
      seen.push(await request.json());
      return HttpResponse.json(decisionResponse({ decision: "confirmed_new", decided_name: "桂枝汤" }));
    }));
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "确认为独立方" }));
    const submit = screen.getByRole("button", { name: "登记判定" });
    // 空规范名后端回 422「确认为独立方必须填规范名」（admin.py:269-271），前端先挡住。
    expect(submit).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "规范方名" }), " 桂枝汤 ");
    expect(screen.getByRole("button", { name: "登记判定" })).toBeEnabled();
    await user.click(submit);
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]).toEqual({ action: "confirmed_new", name: "桂枝汤" });
  });

  it("归并：选定目标方后才可提交，请求体带 target_formula_id 且回调 onChanged", async () => {
    const user = userEvent.setup();
    const seen: unknown[] = [];
    const onChanged = vi.fn();
    server.use(
      http.post("/api/search", () => HttpResponse.json(searchResponse)),
      http.post("/api/admin/pending/1/decision", async ({ request }) => {
        seen.push(await request.json());
        return HttpResponse.json(decisionResponse(
          { decision: "merged", decided_by: "admin", decided_at: "x" }, true));
      }),
    );
    render(<PendingTable items={[item]} total={1} onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    expect(screen.getByText("目标：桂枝汤")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认归并" }));

    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]).toEqual({ action: "merged", target_formula_id: 9 });
    expect(await screen.findByText("已记录判定。")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledOnce();
    // 提交后面板收起，不留下一个已失效的表单。
    expect(screen.queryByRole("button", { name: "确认归并" })).not.toBeInTheDocument();
  });

  it("目标方不存在（404 formula_not_found）：显示闭集标签整串，不泄漏后端原文也不谎称成功", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/search", () => HttpResponse.json(searchResponse)),
      http.post("/api/admin/pending/1/decision", () => HttpResponse.json(
        { detail: { code: "formula_not_found", message: "目标方不存在" }, }, { status: 404 })),
    );
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    await user.click(screen.getByRole("button", { name: "确认归并" }));

    const status = await screen.findByText("目标方不存在");
    expect(status).toHaveAttribute("role", "status");
    // 整串相等：绕开 adminErrorLabel 直接渲染后端 message 的回归拦得住（同 T11 的 F-C）。
    expect(status.textContent).toBe("目标方不存在");
    expect(screen.queryByText("已记录判定。")).not.toBeInTheDocument();
    // 失败时表单仍在，维护者可以换一个目标方重试，而不是整块消失。
    expect(screen.getByRole("button", { name: "确认归并" })).toBeEnabled();
  });

  it("动作与参数不匹配（422 invalid_decision_payload）：走 adminErrorLabel 的「参数不完整」", async () => {
    const user = userEvent.setup();
    const seen: unknown[] = [];
    server.use(http.post("/api/admin/pending/1/decision", async ({ request }) => {
      seen.push(await request.json());
      return HttpResponse.json(
        { detail: { code: "invalid_decision_payload", message: "未知动作「noise」，只支持 merged/confirmed_new/noise" } },
        { status: 422 });
    }));
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "判为噪声" }));
    await user.click(screen.getByRole("button", { name: "确认判噪声" }));
    await waitFor(() => expect(seen).toHaveLength(1));
    const status = await screen.findByText("参数不完整");
    expect(status.textContent).toBe("参数不完整");
    expect(screen.queryByText(/只支持 merged/)).not.toBeInTheDocument();
  });

  it("写动作 401：交回 AdminShell 重新探针，不查标签表也不显示「口令不正确」", async () => {
    const user = userEvent.setup();
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        // 第一次探针已登录（否则挂不上 children）；会话过期后重新探针 → locked。
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.post("/api/admin/pending/1/decision", () => HttpResponse.json(
        { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 })),
    );
    render(
      <AdminShell title="候选方名审核" path="/admin/pending">
        <PendingTable items={[item]} total={1} onChanged={() => {}} />
      </AdminShell>,
    );
    await user.click(await screen.findByRole("button", { name: "判为噪声" }));
    await user.click(screen.getByRole("button", { name: "确认判噪声" }));
    // 探针 1 → 2 = 状态机走回 AdminShell 的唯一探针入口，页面没有自己调 adminProbe()。
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    expect(screen.queryByText("已记录判定。")).not.toBeInTheDocument();
  });

  it("归并表单如实说明别名的移动口径，且不提供也不暗示撤销", async () => {
    const user = userEvent.setup();
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));
    // 后端 R-M5-6：归并是"移动"，删除按 (name, doc) + kind=人工归并 限定（admin.py:288-294）。
    expect(screen.getByText(/归并按「候选方名 \+ 源文件」移动人工归并别名/)).toBeInTheDocument();
    expect(screen.getByText(/立即写入 formula_alias/)).toBeInTheDocument();
    // 指针 §5：M5-A 没有撤销端点，UI 不得提供或暗示"按行撤销归并"。
    // F-7：锁同时覆盖 `undo`（大小写不敏感）——一个写着 "Undo" 的按钮也不许溜过去。
    expect(screen.queryByText(/撤销|回退|恢复|undo/i)).not.toBeInTheDocument();
    // 指针 §4「不开弹窗」现在是断言而非读码：行内展开面板不是 dialog，屏上不得出现 dialog 角色。
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("判定列照后端原值渲染；已判定行把 decided_name 并列显示", () => {
    render(<PendingTable items={[
      item,
      { ...item, id: 2, decision: "confirmed_new", decided_by: "admin", decided_at: "x", decided_name: "桂枝汤" },
    ]} total={2} onChanged={() => {}} />);
    const table = screen.getByRole("table");
    expect(within(table).getByRole("cell", { name: "pending" })).toBeInTheDocument();
    expect(within(table).getByRole("cell", { name: "confirmed_new：桂枝汤" })).toBeInTheDocument();
    // 共 N 条取响应的 total，不是本屏条数（同 T14 的"看板不自我印证"口径）。
    expect(screen.getByText(/共 2 条候选/)).toBeInTheDocument();
  });

  it("表头列名合并为「源文件#行号」，不再有独立的「行号」列", () => {
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    const headers = within(screen.getByRole("table")).getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual(["候选方名", "源文件#行号", "原因", "建议母方", "置信度", "判定", "操作"]);
  });

  /* F-1（规格 §14-5）：`merged` 分支读 `alias_created`——幂等归并（后端 admin.py:304-310 回 false）
     不能只播报「已记录判定。」，要点名"该别名已存在"，同时让维护者知道判定仍算记录、不是整次失败。 */
  it("归并幂等分支（alias_created=false）播报含逐字「该别名已存在」，且判定已记录、不谎称新增", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/search", () => HttpResponse.json(searchResponse)),
      http.post("/api/admin/pending/1/decision", () => HttpResponse.json(decisionResponse(
        { decision: "merged", decided_by: "admin", decided_at: "x", decided_name: null }, false))),
    );
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    await user.click(screen.getByRole("button", { name: "确认归并" }));

    const status = await screen.findByText("判定已记录，该别名已存在。");
    expect(status).toHaveAttribute("role", "status");
    // 闭集逐字 `该别名已存在` 必在；且不得出现"新增"——出现即把"未新增别名"的幂等分支谎报成新建。
    expect(status.textContent).toContain("该别名已存在");
    expect(status.textContent).not.toContain("新增");
    // 判定成功仍会收起面板、触发重拉（不能把幂等当成失败）。
    expect(screen.queryByRole("button", { name: "确认归并" })).not.toBeInTheDocument();
  });

  it("归并新建别名（alias_created=true）保持原播报「已记录判定。」，不误报别名已存在", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/search", () => HttpResponse.json(searchResponse)),
      http.post("/api/admin/pending/1/decision", () => HttpResponse.json(decisionResponse(
        { decision: "merged", decided_by: "admin", decided_at: "x", decided_name: null }, true))),
    );
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: "归并到既有方" }));
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    await user.click(screen.getByRole("button", { name: "确认归并" }));

    const status = await screen.findByText("已记录判定。");
    expect(status).toHaveAttribute("role", "status");
    expect(screen.queryByText("判定已记录，该别名已存在。")).not.toBeInTheDocument();
  });

  /* F-2（规格 §9:123）：这一屏此前没有「写操作进行中」状态面——POST 在途时按钮全可点、状态行被清空，
     双击就会对 `merged` 再跑一次 alias 移动。延迟响应必须由测试自己持有 promise，**不用 timer**
     （本计划已两次否决 Vitest 假定时器）。 */
  it("写操作在途：按钮禁用并说明原因、双击只发一次 POST，resolve 后才进终态", async () => {
    let posts = 0;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    server.use(http.post("/api/admin/pending/1/decision", async () => {
      posts += 1;
      await gate;                       // 卡在测试手里的 promise 上，直到 release()
      return HttpResponse.json(decisionResponse({ decision: "noise" }));
    }));
    render(<PendingTable items={[item]} total={1} onChanged={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "判为噪声" }));   // 展开面板＝第一击，不发请求
    const submit = screen.getByRole("button", { name: "确认判噪声" });
    fireEvent.click(submit);            // 第一提交：POST 在途
    fireEvent.click(submit);            // 双击：同批第二个 click

    // 在途状态面：该行三个动作按钮 + 提交按钮一律禁用，并给出"禁用原因"（§9:123 要的就是禁用 + 原因）。
    expect(screen.getByRole("button", { name: "确认判噪声" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "归并到既有方" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "确认为独立方" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "判为噪声" })).toBeDisabled();
    expect(screen.getByText(/判定提交中，请稍候/)).toBeInTheDocument();

    // 双击只发一次：两个 click 同批派发，也只有一条 POST 到达端点（护栏在途期间挡住第二次写）。
    await waitFor(() => expect(posts).toBe(1));
    expect(posts).toBe(1);

    release();                          // 放行在途响应 → 进入终态才播报
    expect(await screen.findByText("已记录判定。")).toBeInTheDocument();
    expect(screen.queryByText(/判定提交中，请稍候/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "归并到既有方" })).toBeEnabled();
  });

  /* F-4（规格 §9「已判定行默认展开留痕」）：decided_by/decided_at 此前屏上无处可看。 */
  it("已判定行展示 decided_by 与 decided_at 留痕；未判定行不显示这两项的空壳", () => {
    const decidedAt = "2026-01-02T03:04:05Z";
    const shown = new Date(decidedAt).toLocaleString("zh-CN");
    render(<PendingTable items={[
      item, // pending：decided_by/decided_at 皆为 null
      { ...item, id: 2, decision: "merged", decided_by: "admin", decided_at: decidedAt, decided_name: null },
    ]} total={2} onChanged={() => {}} />);

    // 已判定行：留痕次级行同时给出"谁判的"(admin) 和"何时判的"(M4 本地化口径 toLocaleString("zh-CN"))。
    expect(screen.getByText("admin")).toBeInTheDocument();
    expect(screen.getByText(shown)).toBeInTheDocument();
    // 未判定行：整行内既无 admin 也无判定时间，也不留"判定留痕"的空壳。
    const pendingRow = screen.getAllByRole("row").find((row) => within(row).queryByText("pending"));
    expect(pendingRow).toBeDefined();
    expect(within(pendingRow!).queryByText("admin")).not.toBeInTheDocument();
    expect(within(pendingRow!).queryByText(shown)).not.toBeInTheDocument();
    expect(within(pendingRow!).queryByText(/判定留痕/)).not.toBeInTheDocument();
  });
});

describe("FormulaPicker", () => {
  it("legend 是分组可访问名；命中项渲染为选择按钮并回调 onPick", async () => {
    const user = userEvent.setup();
    server.use(http.post("/api/search", () => HttpResponse.json(searchResponse)));
    const onPick = vi.fn();
    render(<FormulaPicker legend="选择目标方" onPick={onPick} />);
    expect(screen.getByRole("group", { name: "选择目标方" })).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ ref_type: "formula", ref_id: 9 }));
    // F-5：更正不准确串（字符串更正，不是放宽断言）——/api/search 返回 exact/literal/vector 三组，
    // 三组都可选；只有归并结果才喂精确通道。逐字用闭集新串。
    expect(screen.getByText("从检索结果里挑一个目标方；归并后该别名即刻进精确检索通道。")).toBeInTheDocument();
  });
});

describe("SearchSuggest 的 onPick（M4 原行为由 library.test.tsx 一字未改地锁住）", () => {
  it("给了 onPick 就渲染选择按钮，不给仍是跳转链接", async () => {
    const user = userEvent.setup();
    const picked = vi.fn();
    server.use(http.post("/api/search", () => HttpResponse.json(searchResponse)));
    const commit = vi.fn();
    const { unmount } = render(<SearchSuggest kinds={["formula"]} onCommit={commit} onPick={picked} />);
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    await user.click(await screen.findByRole("button", { name: "选择 桂枝汤" }));
    expect(picked).toHaveBeenCalledWith(expect.objectContaining({ ref_id: 9 }));
    // 选中后收起面板：M4 的开关逻辑不因 onPick 改变。
    expect(screen.queryByTestId("suggest")).not.toBeInTheDocument();
    unmount();

    render(<SearchSuggest kinds={["formula"]} onCommit={commit} />);
    await user.type(screen.getByRole("searchbox", { name: "检索" }), "桂");
    expect(await screen.findByRole("link", { name: "桂枝汤" }))
      .toHaveAttribute("href", "/formulas/9");
  });
});

describe("候选方名审核页", () => {
  it("默认通道显式发 decision=pending，一级标题与队列都在", async () => {
    const urls: string[] = [];
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json(list);
      }),
    );
    render(<AdminPendingPage />);
    expect(await screen.findByTestId("pending-table")).toBeInTheDocument();
    // 指针 §5：缺省只回 pending，显式传值才按该值过滤——客户端点名发具体值，不靠空串。
    expect(new URL(urls[0]).searchParams.get("decision")).toBe("pending");
    // §13 保留 h1（AdminShell 的 title 就是页面主标题）。
    expect(screen.getByRole("heading", { level: 1, name: "候选方名审核" })).toBeInTheDocument();
  });

  it("判定筛选传具体值，绝不使用空串全量通道", async () => {
    const user = userEvent.setup();
    const urls: string[] = [];
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json({ ...list, items: [{ ...item, decision: "merged" }] });
      }),
    );
    render(<AdminPendingPage />);
    await screen.findByTestId("pending-table");
    await user.selectOptions(screen.getByRole("combobox", { name: "按判定筛选" }), "merged");
    await waitFor(() => expect(urls).toHaveLength(2));
    expect(new URL(urls[1]).searchParams.get("decision")).toBe("merged");
    // `?decision=`（显式空串）是全量通道，本页不许发它。
    for (const url of urls) {
      expect(new URL(url).searchParams.get("decision")).not.toBe("");
      expect(new URL(url).searchParams.has("decision")).toBe(true);
    }
  });

  it("原因筛选改的是请求参数，不是本地过滤", async () => {
    const user = userEvent.setup();
    const urls: string[] = [];
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json(list);
      }),
    );
    render(<AdminPendingPage />);
    await screen.findByTestId("pending-table");
    await user.selectOptions(screen.getByRole("combobox", { name: "按原因筛选" }), "no_composition");
    await waitFor(() => expect(urls).toHaveLength(2));
    expect(new URL(urls[1]).searchParams.get("reason")).toBe("no_composition");
    // 选「全部」时不带 reason 参数（后端 `if reason` 才过滤）。
    await user.selectOptions(screen.getByRole("combobox", { name: "按原因筛选" }), "");
    await waitFor(() => expect(urls).toHaveLength(3));
    expect(new URL(urls[2]).searchParams.has("reason")).toBe(false);
  });

  it("判定写入成功后按当前筛选重新拉队列", async () => {
    const user = userEvent.setup();
    let gets = 0;
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", () => {
        gets += 1;
        return HttpResponse.json(list);
      }),
      http.post("/api/admin/pending/1/decision", () => HttpResponse.json(decisionResponse({ decision: "noise" }))),
    );
    render(<AdminPendingPage />);
    await screen.findByTestId("pending-table");
    expect(gets).toBe(1);
    await user.click(screen.getByRole("button", { name: "判为噪声" }));
    await user.click(screen.getByRole("button", { name: "确认判噪声" }));
    await waitFor(() => expect(gets).toBe(2));
  });

  it("加载中态：请求在途渲染 role=status 的读取中面，不与成功/失败面同屏", async () => {
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", async () => {
        await pending;
        return HttpResponse.json(list);
      }),
    );
    render(<AdminPendingPage />);
    const loading = await screen.findByText("读取候选队列…");
    expect(loading).toHaveAttribute("role", "status");
    expect(screen.queryByTestId("pending-table")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    release();
    await screen.findByTestId("pending-table");
    expect(screen.queryByText("读取候选队列…")).not.toBeInTheDocument();
  });

  it("加载失败（500）：正向渲染失败文案与重试按钮，不静默成空队列", async () => {
    const user = userEvent.setup();
    let requests = 0;
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", () => {
        requests += 1;
        return new HttpResponse("Internal Server Error", { status: 500 });
      }),
    );
    render(<AdminPendingPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("队列加载失败：HTTP 500");
    expect(within(alert).getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.queryByTestId("pending-table")).not.toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(requests).toBe(2));
  });

  it("空队列：诚实空态而不是失败文案", async () => {
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", () => HttpResponse.json({ total: 0, limit: 50, offset: 0, items: [] })),
    );
    render(<AdminPendingPage />);
    expect(await screen.findByText("该筛选下没有候选行。")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pending-table")).not.toBeInTheDocument();
  });

  it("队列超出本屏 limit 时如实说明截断，不让维护者以为看到的是全部", async () => {
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", () => HttpResponse.json(
        { total: 64, limit: 50, offset: 0, items: [item] })),
    );
    render(<AdminPendingPage />);
    const notice = await screen.findByText(/此屏载入前 1 条/);
    expect(notice).toHaveTextContent("共 64 条");
    expect(notice).toHaveTextContent("limit 50");
  });

  /* F-3（规格 §9:123 截断面）：真实队列 64 行、单原因筛选仍 >50，而后端缺省 limit=50——
     不发大 limit 时"请用筛选缩小范围"是给不到剩余行的建议。请求显式带 limit=200（端点钳制并回显）。 */
  it("队列请求带上 limit=200，pending 队列一次装得下当前全量", async () => {
    const urls: string[] = [];
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json(list);
      }),
    );
    render(<AdminPendingPage />);
    await screen.findByTestId("pending-table");
    // 实际发出去的 URL——不是响应回显值——含 limit=200（admin.py:130-139 会钳制到 [1,200] 并回显）。
    expect(new URL(urls[0]).searchParams.get("limit")).toBe("200");
  });

  it("总数(260) > 已渲染(200) 时截断提示仍在（limit=200 也装不下的余量交给 T16 分页）", async () => {
    // 不许为过这条断言把提示删掉：mock total 260、items 给满 200 条，验证提示随 total>已渲染而出现。
    const items = Array.from({ length: 200 }, (_, i) => ({ ...item, id: i + 1 }));
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", () => HttpResponse.json(
        { total: 260, limit: 200, offset: 0, items })),
    );
    render(<AdminPendingPage />);
    const notice = await screen.findByText(/此屏载入前 200 条/);
    expect(notice).toHaveTextContent("共 260 条");
    expect(notice).toHaveTextContent("limit 200");
  });

  it("pending 端点 401：交回 AdminShell 重新探针，不查标签表", async () => {
    let probes = 0;
    server.use(
      http.get("/api/admin/session", () => {
        probes += 1;
        return HttpResponse.json(
          { enabled: true, authenticated: probes < 2, expires_at: probes < 2 ? 1 : null });
      }),
      http.get("/api/admin/pending", () => HttpResponse.json(
        { detail: { code: "admin_unauthorized", message: "请先登录管理端" } }, { status: 401 })),
    );
    render(<AdminPendingPage />);
    await waitFor(() => expect(probes).toBe(2));
    expect(await screen.findByRole("textbox", { name: "管理端口令" })).toBeInTheDocument();
    expect(screen.queryByText("口令不正确")).not.toBeInTheDocument();
    expect(screen.queryByText(/队列加载失败/)).not.toBeInTheDocument();
  });

  /* 修复轮 3（产品侧竞态）：`load()` 没有请求顺序/取消守卫时，先发的 `GET ?decision=pending`
   * 会晚于后发的 `GET ?decision=merged` 落地，把已经切过去的筛选视图**持久**覆盖回待审队列
   * （e2e `#35 归并即时生效` 间歇翻红的根因，毫秒级时间线见 task-15-report.md 修复轮 2）。
   * 本用例把那个时序做成确定性的：两条 handler 各持一只 promise，先放后发的 merged、再放先发的
   * pending——完全由测试手里的 promise 驱动，不用 timer、不用固定延时。
   * 这条必须"没有守卫就翻红"：临时删掉 page.tsx 的序号守卫时，终态断言实际失败输出见报告。 */
  it("陈旧响应守卫：先发后到的 pending 列表不许覆盖已切换的 merged 视图", async () => {
    const user = userEvent.setup();
    // 两条筛选各返回**只有 own 一行**的队列，让"屏上是哪张列表"可由候选名逐字判别。
    const mergedRow: PendingItem = {
      ...item, id: 2, raw_name: "乙", decision: "merged",
      decided_by: "admin", decided_at: "2026-01-02T03:04:05Z", decided_name: null,
    };
    const urls: string[] = [];
    let releaseStale!: () => void;   // 第一条（pending）：故意让它后落地
    let releaseFresh!: () => void;   // 第二条（merged）：故意让它先落地
    const staleGate = new Promise<void>((resolve) => { releaseStale = resolve; });
    const freshGate = new Promise<void>((resolve) => { releaseFresh = resolve; });
    /** 旧响应是否已经交还给客户端——用来证明这条用例真的把竞态跑到了，而不是空跑。 */
    let staleDelivered = false;
    server.use(
      http.get("/api/admin/session", signedIn),
      http.get("/api/admin/pending", async ({ request }) => {
        const decision = new URL(request.url).searchParams.get("decision");
        urls.push(decision ?? "");
        if (decision === "pending") {
          await staleGate;
          staleDelivered = true;
          return HttpResponse.json({ ...list, items: [item] });
        }
        await freshGate;
        return HttpResponse.json({ ...list, items: [mergedRow] });
      }),
    );

    render(<AdminPendingPage />);
    await waitFor(() => expect(urls).toEqual(["pending"]));
    // 旧请求还在途时切筛选：这就是 `setData(null)` 卸载 PendingTable、两条 GET 交叠的窗口。
    await user.selectOptions(screen.getByRole("combobox", { name: "按判定筛选" }), "merged");
    await waitFor(() => expect(urls).toEqual(["pending", "merged"]));

    // 后发的 merged 先落地 → 视图必须是 merged 筛选的数据。
    releaseFresh();
    expect(await screen.findByText("乙")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "merged" })).toBeInTheDocument();
    expect(screen.queryByText("甲")).not.toBeInTheDocument();

    // 先发的 pending 现在才落地（真实网络里那 15–21ms 的迟到窗口）。守卫必须整条丢弃它。
    releaseStale();
    await waitFor(() => expect(staleDelivered).toBe(true));
    await flushInFlightWork();

    // 终态三钉：视图仍是最后一次请求的筛选结果、没有闪回 pending 行、筛选框与视图不矛盾。
    expect(screen.getByText("乙")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "merged" })).toBeInTheDocument();
    expect(screen.queryByText("甲")).not.toBeInTheDocument();
    expect(screen.queryByRole("cell", { name: "pending" })).not.toBeInTheDocument();
    expect(screen.queryByText("读取候选队列…")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "按判定筛选" })).toHaveValue("merged");
    // 竞态真的发生过（两条列表请求、旧的确实后落地），且守卫只是丢弃，不额外重发请求。
    expect(urls).toEqual(["pending", "merged"]);
  });
});
