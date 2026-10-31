import { notFound } from "next/navigation";

import { ApiError, serverGet } from "./api";

// R17：只接受纯十进制数字段。Number() 会放行 "0x10" / "1e2" / " 5 "，
// 大数字串还会被安全整数之外的值悄悄截断，必须一律挡在 notFound()。
export function parseId(raw: string): number {
  if (!/^\d+$/.test(raw)) notFound();
  const id = Number(raw);
  if (!Number.isSafeInteger(id) || id <= 0) notFound();
  return id;
}

export async function loadDetail<T>(path: string): Promise<T> {
  try {
    return await serverGet<T>(path);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }
}
