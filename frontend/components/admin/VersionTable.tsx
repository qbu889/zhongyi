import type { IndexVersions } from "@/lib/admin";

/** notes 是后端自由形状（Record<string, unknown>，实测存
 * {skipped:{...}, noise_tokens:n, dangling_herb_items:n, pair_count:n}），渲染成
 * `k: v` 摘要；嵌套 dict 递归展开——计划稿的扁平写法会把
 * {skipped:{pair_missing_variant:4}} 打成 "skipped: [object Object]"，吞掉 skipped 计数。
 * 标签用「构建摘要」（评审 F-E，新增产品文案，T16 回写规格）：`notes` 里除了 skipped
 * 还有 noise_tokens/dangling_herb_items/pair_count（reindex.py:184-185），
 * 用 `<dt>skipped</dt>` 描述不了它包住的值。 */
function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map(value).join("/");
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, n]) => `${k}: ${value(n)}`)
      .join("；");
  }
  return String(v);
}

export function VersionTable({ data }: { data: IndexVersions }) {
  const current = data.current;
  return (
    <section data-testid="version-table" className="text-sm">
      <h2 className="font-serif text-lg">当前索引</h2>
      {!current ? <p className="mt-1 text-ink/70">尚无 ready 索引，请先重建。</p> : (
        <dl className="mt-1 grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1">
          <dt className="text-ink/70">版本</dt><dd>{value(current.id)}（{value(current.status)}）</dd>
          <dt className="text-ink/70">语料 commit</dt><dd className="break-all">{value(current.commit_hash)}</dd>
          <dt className="text-ink/70">四元组</dt>
          <dd>
            <span>{value(current.embedding_model_version)}</span> / <span>{value(current.chunking_version)}</span>
            {" / "}<span>{value(current.extract_rule_version)}</span>
          </dd>
          <dt className="text-ink/70">计数</dt>
          <dd>方 {value(current.formula_count)} · 药 {value(current.herb_count)} · 穴 {value(current.acupoint_count)}
            · 案 {value(current.case_count)} · 切片 {value(current.chunk_count)}</dd>
          <dt className="text-ink/70">构建摘要</dt><dd>{value(current.notes)}</dd>
          <dt className="text-ink/70">生成时间</dt><dd>{value(current.created_at)}</dd>
        </dl>
      )}
      <h2 className="mt-4 font-serif text-lg">版本历史</h2>
      <table className="mt-1 w-full border-collapse text-left">
        <caption className="text-left text-xs text-ink/70">最近 50 条索引版本</caption>
        <thead><tr className="border-b border-line">
          <th scope="col" className="py-1">id</th><th scope="col">状态</th>
          <th scope="col">语料 commit</th><th scope="col">切片</th></tr></thead>
        <tbody>
          {data.versions.map((row) => (
            <tr key={row.id} className="border-b border-line/60">
              <td className="py-1">{value(row.id)}</td><td>{value(row.status)}</td>
              <td className="break-all">{value(row.commit_hash)}</td><td>{value(row.chunk_count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
