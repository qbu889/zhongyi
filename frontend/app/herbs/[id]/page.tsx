import { HerbDetailView } from "@/components/library/HerbDetailView";
import { loadDetail, parseId } from "@/lib/detail";
import type { HerbDetail } from "@/lib/types";

export default async function HerbDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const herb = await loadDetail<HerbDetail>(`/api/herbs/${parseId(id)}`);
  return <HerbDetailView herb={herb} />;
}
