import Link from "next/link";

export type DetailRefType = "formula" | "herb" | "acupoint" | "case";

export function AskLink({ refType, refId }: { refType: DetailRefType; refId: number }) {
  return (
    <Link
      href={`/chat?ref=${refType}:${refId}`}
      className="rounded border border-cinnabar px-3 py-1 text-sm text-cinnabar hover:bg-cinnabar/10"
    >
      就本条提问
    </Link>
  );
}
