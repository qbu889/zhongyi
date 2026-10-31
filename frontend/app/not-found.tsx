import Link from "next/link";

export default function NotFound() {
  return (
    <section data-testid="not-found" className="mx-auto max-w-2xl px-4 py-16 text-center">
      <h1 className="font-serif text-2xl font-semibold">页面不存在</h1>
      <p className="mt-2 text-sm text-ink/70">链接可能已失效，或该条目尚未收录。</p>
      <Link href="/chat" className="mt-4 inline-block text-sm text-cinnabar underline">
        返回对话页
      </Link>
    </section>
  );
}
