export const GLOBAL_DISCLAIMER = "执业中医师面诊；本库为学术蒸馏产物，非诊疗建议";
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
