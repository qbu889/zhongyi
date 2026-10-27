# Grill Me（拷问式方案访谈插件）

多轮"拷问式"访谈，压力测试你的方案、设计或想法：把决策画成一棵**设计树**，每轮只问"前置条件已满足"的前沿问题（附推荐答案），直到所有分支都被显式确认，才允许动手实施。

## 包含的 Skills

| skill | 触发方式 | 说明 |
|---|---|---|
| `grill-me` | **仅手动**（slash 调用；frontmatter 保留源仓库的 `disable-model-invocation: true`） | 入口壳，被调用后转调 `grilling` |
| `grilling` | 自动（"grill" 类触发词 / 要求压力测试想法时）+ 被 `grill-me` 调用 | 核心访谈流程：设计树、分轮提问、问答格式模板 |

使用：输入 `/grill-me` 开始一轮拷问访谈；或直接描述"帮我 grill 这个方案"触发 `grilling`。

## 来源（Provenance）

- 源仓库：https://github.com/mattpocock/skills （Matt Pocock，skills.sh 排行第一的 `grill-me`，约 137 万安装）
- 源路径：`skills/productivity/grill-me/SKILL.md`、`skills/productivity/grilling/SKILL.md`
- 获取方式：`git clone --depth 1`（2026-10 主分支），SKILL.md 正文**逐字保留**，未做改写
- Logo：源仓库无图标，`assets/avatar.svg` 为本插件自绘占位（烤架+问号），非源资产

## 省略的源文件（及原因）

- `grill-me/agents/openai.yaml`、`grilling/agents/openai.yaml`：OpenAI/ChatGPT 平台的展示名与调用策略配置（display_name、`allow_implicit_invocation: false`），Qoder 不消费该格式。其中"不允许隐式调用"的语义已通过 `grill-me` frontmatter 的 `disable-model-invocation: true` 保留。

## 支持文件依赖

- 无 `references/`、`scripts/`、模板等外部引用；两个 SKILL.md 完全自包含。
- `grill-me` 依赖同插件的 `grilling` skill 存在（正文显式调用），请整包安装。

## 校验

- 离线校验：`validate_qoder_plugin.py`（结果见安装记录 / 提交说明）。
