import { FormulaDetailView } from "@/components/library/FormulaDetailView";
import { loadDetail, parseId } from "@/lib/detail";
import type { FormulaDetail } from "@/lib/types";

export default async function FormulaDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const formula = await loadDetail<FormulaDetail>(`/api/formulas/${parseId(id)}`);
  return <FormulaDetailView formula={formula} />;
}
