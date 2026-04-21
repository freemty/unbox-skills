# Shared Search Playbook

Canonical search query templates used by `/unbox` (full investigation) and `/unbox --mode=backfill` (targeted gap-filling). Both modes reference this single file to avoid drift.

## Tools

### Primary Search Engines (with fallback chain)

Google search is unreliable under parallel agent load (browser daemon crashes, CAPTCHA). **Every search query MUST follow this fallback chain:**

```
Plan A: opencli google search "query" --limit 10 -f md
  ↓ if fails (stale page, CAPTCHA, timeout)
Plan B: python3 ~/.claude/skills/web-fetcher/scripts/fetch.py "https://www.bing.com/search?q={URL_ENCODED_QUERY}"
  ↓ if fails (blocked)
Plan C: python3 ~/.claude/skills/web-fetcher/scripts/fetch.py "https://duckduckgo.com/?q={URL_ENCODED_QUERY}"
```

**Early detection:** If `opencli google search` fails on the FIRST query, don't retry it — switch to Plan B/C for ALL subsequent queries in the session. This saves ~30 seconds per failed attempt.

**URL encoding:** Use Python-style percent encoding for queries. In Bash: `python3 -c "import urllib.parse; print(urllib.parse.quote('中文查询'))"`. For simple ASCII queries, just replace spaces with `+`.

### Platform-Specific Tools (preferred over Google for their domains)

| Platform | Tool | Command | Reliability |
|----------|------|---------|-------------|
| 知乎 | opencli | `opencli zhihu search "query" --limit 10 -f md` | ★★★★ |
| 知乎文章 | opencli | `opencli zhihu download --url "URL" -f md` | ★★★★★ |
| 知乎问答 | opencli | `opencli zhihu question <ID> --limit 5 -f md` | ★★★★ |
| B站搜索 | fetch.py | `python3 fetch.py "https://search.bilibili.com/all?keyword={URL_ENCODED}"` | ★★★★ |
| YouTube | fetch.py | `python3 fetch.py "https://www.youtube.com/results?search_query={URL_ENCODED}"` | ★★★ |
| 搜狗微信 | fetch.py | `python3 fetch.py "https://weixin.sogou.com/weixin?type=2&query={URL_ENCODED}"` | ★★★ |
| Semantic Scholar | curl | `curl -s "https://api.semanticscholar.org/graph/v1/..."` | ★★★★★ |
| GitHub | gh | `gh api users/USERNAME` | ★★★★★ |
| Wayback | curl/fetch | See wayback section | ★★★★ |
| Any webpage | fetch.py | `python3 ~/.claude/skills/web-fetcher/scripts/fetch.py <url>` | ★★★★ |

**知乎注意：** 必须用 `opencli zhihu`，`fetch.py` 会 403。

**微信公众号：** 用搜狗微信搜索（`weixin.sogou.com`）比 Google 加 `mp.weixin.qq.com` 关键词更可靠。

**Rate limiting:** Wait 1-2 seconds between consecutive searches regardless of engine.

---

## Concurrency Guidelines

**Parallel agent limit for search-heavy tasks: 5 agents max.**

When dispatching parallel agents that all need to search:
- **3 agents**: Safe for Google. All can use Plan A.
- **5 agents**: Google will degrade. Agents should detect and switch to Plan B/C early.
- **8+ agents**: Google will crash. Pre-assign agents to different search backends:
  - Agents 0-2: Google (Plan A)
  - Agents 3-4: DuckDuckGo (Plan C directly)
  - Agents 5-7: Platform-specific only (知乎 + B站 + fetch known URLs)

**Best practice for backfill:** Run 5 agents at a time, wait for completion, then next batch. This is already in the SKILL.md spec but was violated in the 2026-04-17 mass backfill (8 concurrent agents → Google complete failure).

---

## Search Notation

Throughout this document:
- `[SEARCH]` = English search using the fallback chain (Plan A → B → C as defined above)
- `[SEARCH/zh]` = Chinese search: Plan A with `--lang zh`, Plan B with Chinese query URL-encoded, Plan C same
- Platform-specific tools (知乎, B站, 搜狗微信, Semantic Scholar, GitHub) are called directly — they don't need the fallback chain

---

## Search Sections

Each section has a `gap_id` used by backfill mode's gap analysis. In full investigation mode, all sections are executed. In backfill mode, only sections matching detected gaps are executed.

### identity (gap_id: N/A — always executed in full mode, never in backfill)

```
[SEARCH] "{NAME} researcher OR professor OR PhD"
python3 ~/.claude/skills/web-fetcher/scripts/fetch.py "https://HOMEPAGE/"
python3 ~/.claude/skills/web-fetcher/scripts/fetch.py "https://HOMEPAGE/bio/"
curl -s "https://api.semanticscholar.org/graph/v1/author/search?query={NAME}&fields=name,affiliations,homepage,paperCount,citationCount,hIndex"
[SEARCH] "{NAME} CV OR resume filetype:pdf"
```

`[SEARCH]` means: follow the fallback chain (Google → fetch Google → DuckDuckGo).

### thesis-ack (gap_id: `thesis-ack`)

```
[SEARCH] "{NAME} PhD thesis site:{UNIVERSITY_DOMAIN}"
[SEARCH] "{NAME} alumni site:{UNIVERSITY_DOMAIN}"
[SEARCH] "{NAME} dissertation {UNIVERSITY_NAME}"
```

### blog (gap_id: `blog`)

```
[SEARCH] "{NAME} blog OR 'about me' OR personal"
```

### zhihu (gap_id: `zhihu`) — Chinese researchers only

**Use 知乎 native search (not Google):**
```
opencli zhihu search "{CHINESE_NAME}" --limit 10 -f md
opencli zhihu search "{NAME} {CHINESE_NAME}" --limit 5 -f md
[SEARCH] "{CHINESE_NAME} 微博"
```

### alumni-media (gap_id: `alumni-media`)

```
[SEARCH] "{NAME} interview OR podcast OR profile OR portrait"
[SEARCH/zh] "{CHINESE_NAME} 采访 OR 访谈 OR 专访 OR 人物 OR 故事 OR 对话"
[SEARCH/zh] "{CHINESE_NAME} 校友 OR 校友故事 OR 校友风采 OR 杰出校友"
[SEARCH/zh] "{CHINESE_NAME} {UNDERGRAD_SCHOOL} 校友"
```

For non-Chinese researchers:
```
[SEARCH] "{NAME} alumni story OR alumni profile OR featured graduate"
[SEARCH] "{NAME} interview TechCrunch OR Wired OR Quanta OR The Verge"
```

### tech-media (gap_id: `tech-media`) — Chinese researchers primarily

**Prefer platform direct search over Google:**
```
python3 fetch.py "https://www.jiqizhixin.com/search?keywords={URL_ENCODED_CHINESE_NAME}"
python3 fetch.py "https://www.qbitai.com/?s={URL_ENCODED_CHINESE_NAME}"
[SEARCH/zh] "{CHINESE_NAME} 机器之心 OR 量子位 OR 雷锋网 OR 36kr OR 新智元"
[SEARCH/zh] "{CHINESE_NAME} 腾讯云 OR CSDN OR InfoQ OR 澎湃"
```

### award-reports (gap_id: `award-reports`)

```
[SEARCH/zh] "{CHINESE_NAME} MIT TR35 OR 福布斯 OR 求是奖 OR 科学探索奖 OR 青橙奖 OR 达摩院青橙"
[SEARCH/zh] "{CHINESE_NAME} 杰出青年 OR 优秀青年 OR 长江学者 OR 万人计划"
```

For non-Chinese researchers:
```
[SEARCH] "{NAME} award profile OR fellowship announcement OR prize citation"
```

### video-presence (gap_id: `video-presence`)

**Use platform native search (not Google):**
```
python3 fetch.py "https://search.bilibili.com/all?keyword={URL_ENCODED_CHINESE_NAME}"
python3 fetch.py "https://www.youtube.com/results?search_query={URL_ENCODED_NAME}+talk+OR+lecture"
```

Fallback if platform search fails:
```
[SEARCH] "{CHINESE_NAME} site:bilibili.com OR site:youtube.com"
```

### rebuttal (gap_id: `rebuttal`)

```
[SEARCH] "{NAME} site:openreview.net"
```

### github (gap_id: `github`)

```bash
gh api "users/{USERNAME}/repos?sort=stars&per_page=20" --jq '.[] | "\(.name) ★\(.stargazers_count) — \(.description)"'
```

### tutorials (gap_id: `tutorials`)

```
[SEARCH] "{NAME} tutorial ICML OR NeurIPS OR ICLR OR OSDI OR SOSP"
[SEARCH] "{NAME} invited talk OR keynote OR workshop talk"
```

### non-academic (gap_id: `non-academic`)

```
[SEARCH/zh] "{CHINESE_NAME} 运动 OR 体育 OR 田径 OR 马拉松 OR 篮球 OR 跑步"
[SEARCH/zh] "{CHINESE_NAME} 音乐 OR 乐队 OR 摄影 OR 书法"
[SEARCH/zh] "{CHINESE_NAME} 社团 OR 学生会 OR 志愿者 OR 支教 OR 创业"
[SEARCH] "{NAME} hobby OR sport OR music OR photography OR marathon"
```

### early-life (gap_id: `early-life`) — Chinese researchers only

```
[SEARCH/zh] "{CHINESE_NAME} 高中 OR 中学"
[SEARCH/zh] "{CHINESE_NAME} 高考"
[SEARCH/zh] "{CHINESE_NAME} 自主招生 OR 领军计划 OR 博雅计划 OR 强基计划"
[SEARCH/zh] "{CHINESE_NAME} ACM OR 数学竞赛 OR 信息学竞赛 OR NOI OR IOI"
[SEARCH/zh] "{CHINESE_NAME} {UNDERGRAD_SCHOOL}"
[SEARCH/zh] "{CHINESE_NAME} 保研 OR 推免"
```

### wechat-mp (gap_id: `wechat-mp`) — Chinese researchers only

**搜狗微信搜索 is the primary tool for this gap:**
```
python3 fetch.py "https://weixin.sogou.com/weixin?type=2&query={URL_ENCODED_CHINESE_NAME}"
[SEARCH/zh] "{CHINESE_NAME} mp.weixin.qq.com"
```

### overseas-forums (gap_id: `overseas-forums`) — Chinese researchers with overseas experience

**These site-specific searches work better with Plan B/C than Google:**
```
[SEARCH/zh] "{CHINESE_NAME} site:1point3acres.com"
[SEARCH/zh] "{CHINESE_NAME} site:newmitbbs.com"
[SEARCH/zh] "{CHINESE_NAME} site:muchong.com"
```

### controversy (gap_id: `controversy`)

**知乎 native search is MORE reliable than Google for this gap:**
```
opencli zhihu search "如何评价 {CHINESE_NAME}" --limit 5 -f md
[SEARCH/zh] "{CHINESE_NAME} 争议 OR 质疑 OR 批评 OR 离职 OR 辞职"
```

For non-Chinese researchers:
```
[SEARCH] "{NAME} controversy OR criticism OR left OR resigned"
```

### mentorship (gap_id: N/A — always executed in full mode, never in backfill)

```
[SEARCH] "{ADVISOR_NAME} lab members OR students OR group"
[SEARCH] "{ADVISOR_NAME} site:scholar.google.com"
[SEARCH] "{ADVISOR_NAME} PhD advisor OR supervisor OR dissertation"
```

### wayback (gap_id: `wayback`)

```bash
curl -s "https://web.archive.org/cdx/search/cdx?url={URL}&output=json&collapse=timestamp:6&limit=50"
python3 ~/.claude/skills/web-fetcher/scripts/fetch.py "https://web.archive.org/web/{TIMESTAMP}/{URL}"
gh api "repos/{USERNAME}/{USERNAME}.github.io" --jq '{name, created_at, pushed_at}' 2>/dev/null
gh api "repos/{USERNAME}/{REPO}/commits?per_page=50" --jq '.[] | "\(.commit.author.date | split(\"T\")[0]) \(.commit.message | split(\"\n\")[0])"'
```

---

## Budget Guidelines

| Mode | Total search attempts | Platform-specific | General (fallback chain) | Snowball reserve |
|------|----------------------|-------------------|-------------------------|-----------------|
| Full investigation | ~80 | ~30 (知乎/B站/Scholar/GitHub) | ~35 (each may cost 1-3 attempts) | 15 |
| Backfill | ~25 | ~12 | ~8 | 5 |

**Budget counts attempts, not unique queries.** A single `[SEARCH]` that falls through to Plan C costs 3 attempts. If Google is down, your effective general search capacity drops by ~60%. Compensate by reallocating budget to platform-specific tools and direct URL fetching.

## Snowball Rule (CRITICAL — applies to both modes)

Every time you fetch a page and read its content, **extract new leads** and **immediately pursue them with follow-up searches**. The template queries above are starting points, not the finish line. The best discoveries come from the second or third hop.

## Chinese vs Non-Chinese Logic

| Dimension | Chinese Researcher | Non-Chinese Researcher |
|-----------|-------------------|----------------------|
| early-life | Full execution | Skip entirely |
| overseas-forums | Execute | Skip |
| wechat-mp | 搜狗微信 + Google fallback | Skip |
| controversy | 知乎 native search (primary) | English search only |
| tech-media | 机器之心/量子位 direct fetch | Skip |
| video-presence | B站 native search | YouTube search |

## Lessons Learned (2026-04-17 mass backfill)

1. **8 concurrent agents killed Google entirely.** Stay under 5.
2. **opencli google search browser daemon is fragile.** Detect failure early, switch to Plan B/C.
3. **Platform-specific search is MORE reliable than Google for Chinese content.** 知乎 + B站 + 搜狗微信 together cover ~60% of what Google/zh would find.
4. **Common name pollution is real.** "张凯", "周鹏程", "Jun Gao" all have severe disambiguation problems. Always add institution or paper keywords.
5. **Negative results are worth recording.** "Searched X, found nothing" is a signal — it means low online presence, which itself is a personality marker.
