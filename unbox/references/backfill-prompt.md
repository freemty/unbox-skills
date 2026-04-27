# Backfill Investigation: {NAME}

You are running a **targeted backfill** on an existing researcher profile for **{NAME}** ({CHINESE_NAME}).
The full investigation was already done. You are NOT re-running Phase 1 (identity) or the full pipeline.
Your job: fill specific gaps and chase specific leads.

## Pre-extracted Identity (DO NOT re-search these)

- **English name**: {NAME}
- **Chinese name**: {CHINESE_NAME}
- **Undergrad**: {UNDERGRAD_SCHOOL} ({UNDERGRAD_YEAR})
- **PhD**: {PHD_SCHOOL}, advisor: {ADVISOR}
- **Homepage**: {HOMEPAGE}
- **GitHub**: {GITHUB_USERNAME}
- **Chinese background**: {IS_CHINESE}

## Existing Report

The current report is at: `{EXISTING_REPORT_PATH}`

Read it first to understand what's already been covered. Do NOT duplicate existing content.

## Gap Sections to Fill

{GAP_SECTIONS}

## Pending Leads (from 未验证/待挖)

{PENDING_LEADS}

## Output

Write your findings to: `{OUTPUT_DIR}/_backfill_{SLUG}.md`

**Default `{OUTPUT_DIR}` if the orchestrator did not override it: `~/outputs/unbox/profiles`** (expand `~` to an absolute path). Never write to a cwd-relative `unbox-output/`.

Use the structured format below. Only include sections where you found new information.

**Write incrementally** — after each search block, update the output file.

## Tools Available

**Full reference: `~/.claude/skills/unbox/references/search-playbook.md`** (the orchestrating agent should inline the relevant gap sections from this file into your prompt)

**Quick reference — fallback chain:** Google → Bing → DuckDuckGo. If Google fails first try, skip it for the rest of the session.

**Quick reference — platform tools (more reliable than Google for Chinese):**
- 知乎: `opencli zhihu search/download/question` (NOT fetch.py)
- B站: `python3 fetch.py "https://search.bilibili.com/all?keyword={URL_ENCODED}"`
- 搜狗微信: `python3 fetch.py "https://weixin.sogou.com/weixin?type=2&query={URL_ENCODED}"`

**URL encoding:** `python3 -c "import urllib.parse; print(urllib.parse.quote('中文查询'))"`

**Rate limiting:** Wait 1-2 seconds. Total budget: ~25 search attempts (a failed fallback counts as 1 attempt).

## Search Playbook

Execute ONLY the sections listed in "Gap Sections to Fill" above. Skip everything else.

**Execute only the sections matching your gap list from `references/search-playbook.md`.** For each gap_id in your gap list, run the corresponding queries from the shared playbook.

## Chasing Pending Leads

For each item in "Pending Leads" above:

1. Read the lead carefully — what specific question does it ask?
2. Design 1-2 targeted searches to answer it
3. If a URL is mentioned in the lead, fetch it directly
4. If the search yields an answer, mark it as RESOLVED with evidence
5. If the search yields nothing, mark it as STILL_PENDING

**Budget: ~2 searches per lead, max 10 leads per run.**

## CRITICAL: Snowball Rule

Every time you fetch a page and read its content, **extract new leads** and follow up with 1-2 additional searches. The best discoveries come from the second hop.

Examples:
- Article mentions "他曾获得ACM区域赛银牌" -> search `"{CHINESE_NAME} ACM 区域赛"`
- Alumni page mentions high school name -> search `"{CHINESE_NAME} {HIGH_SCHOOL}"`
- Forum post mentions a nickname or detail -> follow that thread

**Reserve 5 searches from your budget for snowball follow-ups.**

## Output Template

Write findings using this exact structure:

```markdown
# Backfill: {NAME} ({CHINESE_NAME})

Date: {YYYY-MM-DD}
Gap sections searched: {list}
Leads pursued: {count}

## NEW_SECTION: 非学术身份
<!-- Only include if non-academic section is new to the report -->
- [Finding with source URL]
- [Finding with source URL]

## APPEND: 性格信号 > 校友报道/人物专访
<!-- Append to existing section -->
- [New finding from alumni story, with URL]

## APPEND: 性格信号 > 争议/八卦
<!-- Append to existing section -->
- [Finding, with credibility note]

## APPEND: 性格信号 > 其他发现
<!-- Append to existing section -->
- [Tech media coverage finding]
- [Award report finding]
- [Video presence finding]

## LEAD_RESOLVED: {original lead text}
Status: RESOLVED
Evidence: {what was found, with URL}

## LEAD_RESOLVED: {original lead text}
Status: STILL_PENDING
Notes: {what was searched, why it failed}

## NEW_LEADS: 未验证/待挖 (snowball)
<!-- New leads discovered during this backfill -->
- [New lead from snowball search]
- [New lead from snowball search]

## SEARCH_LOG
<!-- Track budget usage -->
Total Google searches: N/25
Total fetches: N
Rate limit hits: N
```

## Merge Instructions

After backfill completes, merge results into the original profile following the protocol in `references/merge-utils.md`. Key rules:

- Use the unified marker format: `> 📎 补全 ({date}, 来源: {source}): {fact}`
- Run idempotency check before every addition (check all existing `📎` markers)
- Insert new content at end of target section, before the next `##` heading
- For conflicts, follow the evidence priority order in merge-utils.md

## Important Rules

1. **DO NOT re-search identity.** Chinese name, school, advisor are given. Use them directly.
2. **DO NOT repeat searches already reflected in the existing report.** Read the report first.
3. **Fetch every promising result.** A search without fetching the top results is wasted.
4. **Snowball is mandatory.** After every fetch, extract at least one new lead if possible.
5. **Mark credibility.** Forum gossip: "据论坛讨论". Self-reported: "据本人知乎". Official: "据校方网站".
6. **Budget discipline.** ~25 Google searches total. If hitting rate limits, prioritize gap sections over pending leads.
7. **Write incrementally.** Update the output file after each search block, not at the end.
