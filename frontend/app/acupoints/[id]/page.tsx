import { AcupointDetailView } from "@/components/library/AcupointDetailView";
import { loadDetail, parseId } from "@/lib/detail";
import type { AcupointDetail } from "@/lib/types";

export default async function AcupointDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const point = await loadDetail<AcupointDetail>(`/api/acupoints/${parseId(id)}`);
  return <AcupointDetailView point={point} />;
}
