"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminShell, useAdminReauth } from "@/components/admin/AdminShell";
import { QualitySection } from "@/components/admin/QualitySection";
import { adminErrorLabel, adminGet, isAdminUnauthorized, type QualityReport } from "@/lib/admin";

type Cell = (string | number | null)[];
const join = (values: string[]) => values.join("、");

export default function AdminQualityPage() {
  return (
    <AdminShell title="质量报告" path="/admin/quality">
      <QualityReportBody />
    </AdminShell>
  );
}

function QualityReportBody() {
  const reprobe = useAdminReauth();
  const [report, setReport] = useState<QualityReport | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    adminGet<QualityReport>("/api/admin/quality-report")
      .then(setReport)
      .catch((caught: unknown) => {
        // 指针 §1：数据端点 401 = 会话过期，交回 AdminShell 重新探针（门接管成登录卡），
        // 绝不进 adminErrorLabel——表里 admin_unauthorized 是「口令不正确」，对没输口令的人是误诊。
        if (isAdminUnauthorized(caught)) { reprobe(); return; }
        setError(adminErrorLabel(caught));
      });
  }, [reprobe]);
  useEffect(load, [load]);

  if (error) {
    return <p role="alert" className="text-sm text-cinnabar">报告加载失败：{error}
      <button type="button" onClick={load} className="ml-2 underline">重试</button></p>;
  }
  if (!report) return <p role="status" className="text-sm text-ink/70">读取质量报告…</p>;

  const herbDiff = report.herb_diff;
  const doseDev = report.dose_deviation;
  const failureDetails = report.parse_failure_details;
  const annotations = report.annotation_items;
  const dangling = report.dangling_herbs;
  const states = report.dose_state_distribution;
  const queue = report.pending_queue;

  // 规格 §4.1：七个数据面各一表；只有四个行清单可导（herb_diff/dose_deviation/
  // parse_failure_details/annotation_items），三个聚合视图（dangling/dose_state/pending_queue）
  // 铺成 CSV 会造假列名，故不给导出链接。
  const sections: {
    id: string; title: string; headers: string[]; rows: Cell[];
    exportList?: string; pathColumn?: number;
  }[] = [
    {
      id: "herb_diff", title: "① 药材差异", exportList: "herb_diff",
      headers: ["方名", "仅古制有", "仅克数本有"],
      rows: herbDiff.map((r) => [r.formula, join(r.missing_in_gram), join(r.missing_in_ancient)]),
    },
    {
      // 指针 §4：DoseDeviationEntry 三键必填，直接渲染值本身，不 `?? "—"` 假装可缺。
      id: "dose_deviation", title: "② 剂量偏差>50%", exportList: "dose_deviation",
      headers: ["方名", "药味", "古制g", "克数本g", "偏差%"],
      rows: doseDev.flatMap((entry) => Object.entries(entry.items).map(
        ([herb, dev]) => [entry.formula, herb, dev.ancient_g, dev.gram_g, dev.deviation_pct])),
    },
    {
      // R-M5-2：源文件 + 行号合成一格（表头保持四列），§13-8 只做「显示 + 可复制」不做链接。
      id: "parse_failure_details", title: "③ 解析失败明细", exportList: "parse_failure_details",
      headers: ["候选方名", "源文件#行号", "原因", "判定"], pathColumn: 1,
      rows: failureDetails.map((r) => [r.raw_name, r.doc, r.source_row_no, r.reason, r.decision]),
    },
    {
      id: "annotation_items", title: "④ 注记被误抽为药味", exportList: "annotation_items",
      headers: ["药味文本", "variant_id", "formula_item_id"],
      rows: annotations.map((r) => [r.herb_text, r.variant_id, r.formula_item_id]),
    },
    {
      id: "dangling_herbs", title: "⑤ herb_id 悬空",
      headers: ["项目", "值"],
      rows: [
        ["悬空行数", dangling.rows],
        ["去重词数", dangling.distinct_terms],
        ...dangling.top.map(([term, count]) => [term, count]),
      ],
    },
    {
      id: "dose_state_distribution", title: "⑥ 换算状态五态分布",
      headers: ["状态", "味数"],
      rows: Object.entries(states).map(([state, count]) => [state, count]),
    },
    {
      id: "pending_queue", title: "⑦ 待确认方名候选队列",
      headers: ["维度", "取值", "数量"],
      rows: [
        ...Object.entries(queue.by_decision).map(([k, v]) => ["判定", k, v]),
        ...Object.entries(queue.by_reason).map(([k, v]) => ["原因", k, v]),
      ],
    },
  ];

  return (
    <div data-testid="quality-report">
      {sections.map((section) => <QualitySection key={section.id} {...section} />)}
      <p className="mt-4 text-xs text-ink/70">
        ⑤⑥⑦ 是聚合视图，按规格 §4.1 不提供 CSV 导出；要下钻待审真实行请去「候选方名」页。
      </p>
    </div>
  );
}
