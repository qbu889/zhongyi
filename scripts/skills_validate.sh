#!/usr/bin/env bash
# skills_validate.sh — 校验 .claude/skills 并模拟触发检索，确认 skill 指引可落地。
# 用法:
#   bash scripts/skills_validate.sh                  # 只做结构+引用校验
#   bash scripts/skills_validate.sh demo 射干麻黄汤  # 再加一次方剂模拟检索
#   bash scripts/skills_validate.sh demo 腰背痛      # demo + 症状检索(针灸治症)
# 注: 本环境 grep 被包装成报错函数，故一律用 `command grep` 绕过。
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
SKILLS_DIR=".claude/skills"
FAIL=0

echo "===== 1) frontmatter 校验 (name + description) ====="
for d in formula-lookup syndrome-differentiation herb-lookup acupoint-selection clinical-case; do
  f="$SKILLS_DIR/$d/SKILL.md"
  if [ ! -f "$f" ]; then echo "  [MISSING] $f"; FAIL=1; continue; fi
  name="$(command sed -n 's/^name: //p' "$f" | head -1)"
  desc="$(command sed -n 's/^description: //p' "$f" | head -1)"
  if [ -n "$name" ] && [ -n "$desc" ]; then
    echo "  [OK] $d  name=$name"
  else
    echo "  [BAD ] $d  name='$name' desc='$desc'"; FAIL=1
  fi
done

echo "===== 2) 引用蒸馏文件存在性 ====="
check_files() {  # $1=skill  剩余参数=相对路径
  skill="$1"; shift
  for rel in "$@"; do
    if [ -f "$rel" ]; then echo "  [OK] $skill -> $rel"
    else echo "  [MISSING] $skill -> $rel"; FAIL=1; fi
  done
}
check_files formula-lookup \
  distilled/方剂库-经典配方.md distilled/方剂库-经方组成.md \
  distilled/03-金匮/金匮方剂库.md distilled/02-伤寒论/伤寒六经方库.md
check_files syndrome-differentiation \
  distilled/02-伤寒论/六经辨证框架.md distilled/02-伤寒论/临证诊断与治则补充.md \
  distilled/06-医案/临床问答对.md
check_files herb-lookup \
  distilled/04-神农本草经/中药库.md distilled/04-神农本草经/药物按味归类.md
check_files acupoint-selection \
  distilled/05-针灸/十二经穴位库.md distilled/05-针灸/针灸治症取穴.md
check_files clinical-case distilled/06-医案/临床问答对.md

echo "===== 3) demo 模拟触发检索 ====="
MODE="${1:-none}"; QTY="${2:-}"
if [ "$MODE" = "demo" ] && [ -n "$QTY" ]; then
  echo "-- 方剂库检索: $QTY --"
  for f in distilled/方剂库-经典配方.md distilled/方剂库-经方组成.md \
           distilled/03-金匮/金匮方剂库.md distilled/02-伤寒论/伤寒六经方库.md; do
    n="$(command grep -c -- "$QTY" "$f" 2>/dev/null || echo 0)"
    command grep -Hn -- "$QTY" "$f" 2>/dev/null | head -3
    echo "   (命中行 ~$n in $f)"
  done
  echo "-- 症状/取穴检索: $QTY --"
  command grep -Hn -- "$QTY" distilled/05-针灸/针灸治症取穴.md 2>/dev/null | head -3
fi

echo "===== 结果 ====="
if [ "$FAIL" -eq 0 ]; then echo "  全部通过"; else echo "  存在缺漏"; fi
exit $FAIL
