export const GLOBAL_DISCLAIMER = "执业中医师面诊；本库为学术蒸馏产物，非诊疗建议";
// 与服务端 gate.DISCLAIMER 同句；对话页仍渲染服务端下发的 answer.disclaimer。
export const ANSWER_DISCLAIMER =
  "本回答基于本地蒸馏语料整理，仅供学习与检索参考；诊断与用药请由执业中医师面诊决定。";
export const PAGE_SIZE = 20;

export type NavItem = { href: string; label: string; disabled?: boolean };

export const NAV_ITEMS: NavItem[] = [
  { href: "/chat", label: "对话" },
  { href: "/formulas", label: "方剂库" },
  { href: "/herbs", label: "中药库" },
  { href: "/acupoints", label: "针灸" },
  { href: "/cases", label: "医案" },
  { href: "/framework", label: "辨证框架", disabled: true },
  // T11 起 /admin 概览页上线（控制人裁定：顶栏「管理」入口由本任务认领，见 task-11 指针 §3）；
  // /admin/quality 等子页 T12–T14 陆续接上，入口本身不再禁用。
  { href: "/admin", label: "管理" },
];
