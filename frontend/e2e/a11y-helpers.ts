import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

/** M4 `a11y.spec.ts` 的同一套 helper（T15 指针 §4：axe 口径不许另起炉灶）：
 * `wcag2a`/`wcag2aa` 标签内 serious/critical 违规清单，用例侧断言它 `toEqual([])`。
 * 提到共享文件是为了 admin.spec.ts（T15）与 a11y.spec.ts（M4）用**同一实现**，
 * 而不是复制一份再各自漂移；阈值与过滤逻辑一字未改。 */
export async function blocking(page: Page): Promise<string[]> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  return results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id}: ${violation.help}`);
}
