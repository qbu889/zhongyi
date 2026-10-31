import { CaseDetailView } from "@/components/library/CaseDetailView";
import { loadDetail, parseId } from "@/lib/detail";
import type { CaseDetail } from "@/lib/types";

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const caseItem = await loadDetail<CaseDetail>(`/api/cases/${parseId(id)}`);
  return <CaseDetailView caseItem={caseItem} />;
}
