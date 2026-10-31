export type FilterValue = string | string[] | number | null | undefined;

export function buildQuery(values: Record<string, FilterValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    // 0（如 offset=0）与空串都是默认值，按未筛选处理，不写入 URL
    if (value === null || value === undefined || value === "" || value === 0) continue;
    if (Array.isArray(value)) {
      for (const item of value) if (item) params.append(key, item);
    } else {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function readList(params: URLSearchParams, key: string): string[] {
  return params.getAll(key).filter(Boolean);
}

export function pageFrom(params: URLSearchParams): number {
  const value = Number(params.get("page") ?? "1");
  return Number.isFinite(value) && value >= 1 ? Math.floor(value) : 1;
}

export function pageHref(path: string, params: URLSearchParams, page: number): string {
  const next = new URLSearchParams(params);
  if (page <= 1) next.delete("page");
  else next.set("page", String(page));
  const query = next.toString();
  return query ? `${path}?${query}` : path;
}

export function paramsFrom(
  raw: Record<string, string | string[] | undefined>,
): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    if (Array.isArray(value)) {
      for (const item of value) if (item) params.append(key, item);
    } else if (value) {
      params.set(key, value);
    }
  }
  return params;
}
