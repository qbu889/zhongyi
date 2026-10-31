import Link from "next/link";
import type { ReactNode } from "react";

export function ResultRow({
  href, title, badges, meta,
}: {
  href: string;
  title: string;
  badges?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <li className="border-b border-line py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link href={href} className="font-serif text-base hover:text-cinnabar">{title}</Link>
        {badges}
      </div>
      {meta && <div className="mt-1 text-sm text-ink/60">{meta}</div>}
    </li>
  );
}
