# 中医经方 Skills（基于 `distilled/` 蒸馏库）

一套 Claude Code 项目级 skills，把 `/Users/linziwang/PycharmProjects/zhongyi/distilled`
（约 256K 字符、18 文档）蒸馏成 5 个可复用临床能力。**所有结论严格基于本地库**，不套用通用模板。

## 五个 skill
| skill | trigger（触发场景） | 主数据 |
|---|---|---|
| `formula-lookup` (公式检索) | 查方剂组成/剂量/出处/克数 | 方剂库-经方组成、经典配方、金匮方剂库、伤寒六经方库 |
| `syndrome-differentiation` (辨证) | 一组症状→定经/定证型/问诊 | 六经辨证框架、临证诊断与治则补充 |
| `herb-lookup` (中药) | 查药性味功效/按味五脏/古名对照 | 中药库(379味)、药物按味归类 |
| `acupoint-selection` (取穴) | 穴位角色/按症取穴 | 十二经穴位库、针灸治症取穴 |
| `clinical-case` (医案) | 生成/整理经方医案问答对 | 临床问答对(30例) |

## 使用方式
- 在对话中自然描述需求，Claude 会按 description 自动匹配触发；也可用 `shortcut` 手动指定。
- 跨能力任务会串联：如"咳嗽喘辨证开方" = syndrome-differentiation → formula-lookup → acupoint-selection。

## ⚠️ 环境注意（重要）
本仓库 shell 把 `grep` 包装成调用 claude 二进制的函数，直接 `grep` 会报
"claude native binary not installed"。skill 内已要求用 **`command grep`** 绕过。
若你在终端手搜库文件，同样加 `command` 前缀。

## 通用硬规则（所有 skill 共守）
- 方/药/穴/病机**必须本地 grep 到**，查不到不推荐、不臆造。
- 剂量只出**克**（古制按 1两≈15g 换算并留痕）。
- 结尾附标准免责声明：**执业中医师面诊**；本库为学术蒸馏产物，非诊疗建议。
