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
  { href: "/admin", label: "管理", disabled: true },
];
