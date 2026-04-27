---
name: unbox
description: >
  Use when profiling researchers beyond their publication list — personality,
  early career, mentorship lineage, direction evolution, deleted content.
  Also supports targeted gap-filling on existing profiles (--mode=backfill).
  Triggers: /unbox, 开盒, researcher profile, 'who is this author', backfill, 补全.
---

# Unbox — 研究者画像调研

不是查简历，是拼人。发表列表谁都能查，要挖的是性格信号、早期经历、方向演变、师门关系。

## When to Use

- User says `/unbox` or `开盒`
- User asks to research/profile researchers ("这人什么背景", "who is this author")
- User pastes a paper link and wants to know about the authors
- User wants to understand a research group's composition

## When NOT to Use

- Looking up a single paper's content → use `web-fetcher` or `scholar-agent`
- Adding researchers to selfOS wiki → use `selfos` skill after unbox
- General topic research → use `deep-research`

## Command

```
/unbox <input>                    # full investigation (default)
/unbox --mode=backfill [name]     # targeted gap-filling on existing profiles
/unbox --mode=backfill --top N    # top N profiles by gap count
/unbox --mode=backfill --dry-run  # show gap analysis only
```

### Full Mode (default)

Input is one of:
- arXiv URL: `https://arxiv.org/abs/...`
- OpenReview URL: `https://openreview.net/forum?id=...`
- Comma-separated names: `"Alice Zhang, Bob Li, Charlie Wang"`
- Local file path (one name per line)

## Workflow

**Before executing, read `references/subagent-prompt.md` for the full per-person pipeline.**

### Step 1: Parse Input

Determine input type:

| Input | Detection | Action |
|-------|-----------|--------|
| `https://arxiv.org/abs/...` | URL regex | Fetch page via `python3 ~/.claude/skills/web-fetcher/scripts/fetch.py <url>`, extract author list |
| `https://openreview.net/forum?id=...` | URL regex | Fetch page via `fetch.py`, extract author list |
| Comma-separated string | Contains `,` and no URL scheme | Split by `,`, trim whitespace |
| File path | File exists on disk | Read file, one name per line |

For paper links: after extracting authors, display the list and ask user to confirm or remove names before proceeding.

### Step 2: Create Output Directory

```bash
mkdir -p ~/outputs/unbox/profiles ~/outputs/unbox/overviews
```

**Canonical output paths (see `docs/outputs-convention.md`):**
- Individual profiles: `~/outputs/unbox/profiles/{slug}.md`
- Overview files: `~/outputs/unbox/overviews/_overview.md` (or batch-specific name)
- Backfill deltas: `~/outputs/unbox/profiles/_backfill_{slug}.md`

Never write to cwd-relative `unbox-output/` — always use absolute `~/outputs/unbox/`.

### Step 3: Dispatch Subagents

For each researcher name, spawn one subagent using the Agent tool:

- **All subagents launch in parallel** (single message with multiple Agent tool calls)
- Each subagent receives the full prompt from `references/subagent-prompt.md` with `{NAME}` replaced
- Each subagent writes its report to `~/outputs/unbox/profiles/{slug}.md`
- Slug: lowercase name, spaces replaced with `-`, remove non-ascii (e.g., "Alice Zhang" → `alice-zhang`)

Example Agent call:
```
Agent({
  description: "Unbox: Alice Zhang",
  prompt: "<contents of subagent-prompt.md with {NAME} = Alice Zhang>",
  mode: "bypassPermissions"
})
```

### Step 4: Assemble Overview

After all subagents complete, read all generated reports and create `~/outputs/unbox/overviews/_overview.md`:

```markdown
# Unbox Report

Generated: {date}
Source: {input description}
Researchers: {count}

| 姓名 | 机构 | 一句话 | 报告 |
|------|------|--------|------|
| ... | ... | ... | [链接](slug.md) |
```

The "一句话" for each person is extracted from the `## 一句话` section of their report.

### Step 5: Report to User

Print the overview table and the path to `~/outputs/unbox/profiles/`.

---

## Backfill Mode Workflow (`--mode=backfill`)

**Before executing, read `references/backfill-prompt.md` for the per-person backfill subagent prompt.**

Backfill mode runs targeted searches on existing profiles to fill gaps introduced by prompt upgrades. It does NOT re-run identity anchoring or the full pipeline.

### Backfill Step 1: Gap Analysis

For each target profile, read the existing report and detect which sections are missing.

**Gap detection rules** — check for presence of section headers or key content using gap_ids from `references/search-playbook.md`:

| Gap ID | Detection Rule |
|--------|----------------|
| `non-academic` | No "非学术" content in 性格信号 |
| `alumni-media` | No "校友" or "专访/人物报道" beyond basic interview |
| `overseas-forums` | No mention of newmitbbs, 1point3acres, muchong |
| `controversy` | No "争议" or "如何评价" content |
| `award-reports` | No award coverage details |
| `video-presence` | No video presence |
| `tech-media` | No 机器之心/量子位/雷锋网/36kr coverage |
| `wechat-mp` | No mp.weixin.qq.com sourced content |

Also extract identity anchors (name, school, advisor, etc.) and parse "未验证/待挖" leads.

**Priority score** = count of missing sections + count of actionable leads.

If `--dry-run`, print gap analysis table and stop.

### Backfill Step 2: Build Backfill Prompts

For each profile (sorted by priority score descending):

1. Read `references/backfill-prompt.md`
2. Replace placeholders with extracted identity anchors and gap list
3. Reference `references/search-playbook.md` for queries — only execute sections matching detected gaps

### Backfill Step 3: Dispatch Subagents

**Batch size: 5 parallel subagents at a time.** Same Agent call pattern as full mode.

Dispatch order: sorted by priority score (most gaps first).

For each batch:
1. Launch 5 subagents in parallel, each with the filled backfill prompt
2. Wait for all 5 to complete
3. Before launching next batch, check rate limit status (if 429 errors, wait 30 seconds)

Each subagent writes findings to: `{OUTPUT_DIR}/_backfill_{SLUG}.md`

**Budget:** ~25 Google searches per person (vs ~80 for full investigation).

### Backfill Step 4: Merge Results

After each batch, merge backfill results into original profiles. Reference `references/merge-utils.md` for the append protocol:

| Backfill Type | Merge Strategy |
|---------------|---------------|
| New section content | Insert before `## 未验证` or at end if header doesn't exist |
| Enhanced existing section | Append with `> 🔍 补全 ({date}): ` prefix |
| New 未验证/待挖 items (snowball) | Append to existing 未验证 list |
| Resolved 未验证 items | Change `- [ ]` to `- [x]` with resolution |

**Idempotency check**: Before adding content, search for the key phrase in the existing report. Skip if already present.

### Backfill Step 5: Summary Report

Print per-profile changes (sections added, leads resolved, new leads from snowball).

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| 用 `fetch.py` 抓知乎 → 403 | 必须用 `opencli zhihu search/download/question` |
| 从新闻报道推断本科院校 | 个人主页 bio 页面是 ground truth，优先级最高 |
| 只搜英文不搜中文 | 中国研究者的早期经历（竞赛、保研）全在中文搜索里 |
| 不搜高中/高考信息 | 从本科入学年反推高考年，搜 "{中文名} 高中/高考/自主招生"，信息密度远超本科标签 |
| 忽略微信公众号 | 大量早期信息沉淀在学校/院系/社团公众号，用 Google 搜 "{中文名} mp.weixin.qq.com"（注意：不要用 `site:` 语法，直接作为关键词） |
| 不查高校 BBS | 水木社区 (newsmth.net) 有入学名单、院系讨论；cc98.org 有浙大信息 |
| 不查海外中文论坛 | newmitbbs.com 和一亩三分地 (1point3acres.com) 有大量 biographical tidbits |
| Wayback Machine 是唯一的时光机 | 先查 GitHub Pages 源码仓库的 git log，精确到天 |
| 只看发表列表 | 性格信号（thesis 致谢、知乎、rebuttal 风格）才是核心 |
| 忽略 conference tutorials | Tutorial 比 paper 更能看出判断力和思想 flow |
| 对单个名字没加消歧 | "Hao Zhang" 有几十个同名人，加 institution/paper 关键词 |
| 只搜"采访/访谈" | 中文人物报道关键词更多：专访、人物、故事、校友故事、校友风采 |
| 不搜非学术特质 | 运动队、社团、乐队、创业等信息藏在校级新闻和校友报道里 |
| 不搜科技媒体 | 机器之心/量子位/雷锋网/36kr/腾讯云的人物长文是性格信号金矿 |
| 不搜奖项报道 | MIT TR35/求是奖/科学探索奖的报道常包含详细人物背景 |
| 搜一次就停 | 必须滚雪球：每次 fetch 页面后提取新线索，追加搜索 |
| 不搜"如何评价 XXX" | 知乎"如何评价"类问题是中文互联网上最集中的人物讨论 |
| Running backfill without reading existing report | Read the report FIRST. Backfill ONLY fills gaps, never re-searches identity. |
| Re-running all search sections in backfill mode | Only execute sections matching detected gaps from gap analysis. |
