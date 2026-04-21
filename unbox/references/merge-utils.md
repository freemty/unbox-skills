# Shared Merge Protocol

Canonical rules for appending new information to existing unbox profiles. Used by:
- `/unbox-cross-ref` (internal cross-referencing, no external search)
- `/unbox --mode=backfill` (external search gap-filling)
- `/unbox-to-wiki --inject` (wiki enrichment from profile data)

All three operations share the same append/dedup/conflict resolution logic below.

---

## Unified Marker System

All appended content uses a single marker format with a `source_type` tag:

```
> 📎 {source_type} ({date}, 来源: {source}): {fact}
```

### Source Types

| Source Type | Used By | Example |
|-------------|---------|---------|
| `交叉补充` | cross-ref | `> 📎 交叉补充 (2026-04-17, 来源: yinghao-xu.md): 沈宇军是"对科研生涯产生巨大影响的第二个人"` |
| `补全` | backfill | `> 📎 补全 (2026-04-17, 来源: Google/校友报道): 曾获校运会400米接力亚军` |
| `wiki注入` | wiki inject | `> 📎 wiki注入 (2026-04-17, 来源: jimmy-ba.md): "most caring supervisor I've ever had"` |

### Why Unified

Previously: cross-ref used `📎 交叉补充`, backfill used `🔍 补全` — two marker systems that didn't intercheck for duplicates. Now all use `📎` prefix with `source_type` differentiation. Dedup logic checks ALL `📎` markers regardless of source_type.

**`🔍 补全` is DEPRECATED.** Some older profiles still contain `🔍` markers from before the unification. When checking for duplicates, also check for `🔍` markers (treat them as equivalent to `📎 补全`). But all NEW markers must use the `📎` format.

---

## Append Rules

### Where to Insert

| Content Type | Target Section | Fallback |
|-------------|---------------|----------|
| Relationship info | 师门谱系 or 频繁合作者 | 未验证 / 待挖 |
| Event / date | 性格信号 > 其他发现 or 时光机 | 未验证 / 待挖 |
| Affiliation info | 身份锚点 | 未验证 / 待挖 |
| Personality | 性格信号 > 其他发现 | 未验证 / 待挖 |
| Unverified / speculative | Always: 未验证 / 待挖 | — |

Insert at the **end** of the chosen section (before the next `##` heading), using the Edit tool.

### Idempotency Check (CRITICAL)

Before adding any content, perform ALL of these checks:

1. **Exact marker search**: `grep "📎" {profile_path}` — list all existing markers
2. **Semantic dedup**: For each proposed addition, check if the core fact (person, date, event) already appears ANYWHERE in the profile, even with different wording
3. **Cross-type check**: A fact added by cross-ref should NOT be re-added by backfill, and vice versa. Check all `📎` markers regardless of source_type.

If any check matches, **skip** the addition.

### Append Format

```markdown
> 📎 {source_type} ({YYYY-MM-DD}, 来源: {source}): {fact}
```

- One marker per fact, one line
- `{source}` is either a filename (`yinghao-xu.md`) or a URL/description (`Google/校友报道`)
- Keep `{fact}` concise — one sentence max
- For forum-sourced info, append credibility note: `(据论坛讨论)`

---

## Conflict Resolution

When a new fact contradicts existing content:

### Step 1: Compare Evidence Quality

Priority order (highest first):
1. Primary source (person's own homepage, their own blog/知乎)
2. Official institutional page (university, company)
3. Cited URL from a third party
4. Another person's unbox profile (secondary mention)
5. Forum discussion (lowest)

### Step 2: Resolve

**If one side is clearly more reliable:**
- Edit the less reliable version to match
- Add HTML comment at edit point:
  ```
  <!-- cross-ref: 原文为 "X"，{source} 记为 "Y"，已修正 (来源更可靠: {reason}) -->
  ```

**If truly ambiguous:**
- Do NOT change either side
- Add to 未验证 / 待挖:
  ```
  > ⚠️ 待验证 (与 {source} 冲突): {description}
  ```

### Step 3: URL Verification (optional)

Only for cross-ref mode: if both sides cite a URL and the conflict is about a verifiable fact, you MAY fetch those specific URLs to resolve. No speculative Google searches.

---

## Structural Rules

- **Never add new sections** — only append within existing sections, or add to 未验证 / 待挖
- **Preserve formatting** — match surrounding indentation and style
- **Never restructure** — don't reorganize the report
- **Conservative default** — when in doubt, add to 未验证 / 待挖 rather than asserting as fact
