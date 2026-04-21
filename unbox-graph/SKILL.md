---
name: unbox-graph
description: >
  Maintain and reason about the researcher relationship graph.
  Three modes: `sync` extracts structure from profiles; `enrich` cross-references
  text between connected profiles; `think` runs structural analysis.
  Triggers: /unbox-graph, graph sync, graph enrich, graph think, 更新图谱, 图谱分析, 交叉验证.
---

# Unbox Graph — 图谱同步、富化与结构推理

维护 `graph.json`，基于图谱做信息回流，发现 pattern 并推荐行动。

## When to Use

- User says `/unbox-graph sync` or `更新图谱` or `同步图谱`
- User says `/unbox-graph enrich` or `交叉验证` or `交叉补充`
- User says `/unbox-graph think` or `图谱分析` or `下一步挖谁`
- After completing a batch of new profiles (sync → enrich)
- When deciding what to research next (think)

## When NOT to Use

- Profiling new researchers → use `/unbox`
- Gap-filling existing profiles with NEW web searches → use `/unbox --mode=backfill`

## Commands

```
/unbox-graph sync              # extract nodes/edges from all profiles, update graph.json
/unbox-graph sync --diff       # show what would change without writing
/unbox-graph enrich            # cross-reference text between connected profiles (no web search)
/unbox-graph enrich --dry-run  # show what would be backfilled without writing
/unbox-graph think             # structural analysis + action recommendations
/unbox-graph think --strategy <name>  # focus on one strategy (expand/cluster/bridge/temporal)
```

## File Locations

| File | Purpose |
|------|---------|
| `~/unbox-output/graph.json` | The relationship graph (nodes + edges) |
| `~/unbox-output/profiles/*.md` | Source of truth for extraction |
| `~/unbox-output/overviews/*.md` | Additional context for clusters |

## Graph Schema

```json
{
  "nodes": [
    {
      "id": "slug",
      "name": "English Name",
      "chinese_name": "中文名",
      "institution": "Current Affiliation",
      "has_profile": true,
      "mentioned_in": ["slug1", ...]
    }
  ],
  "edges": [
    {
      "source": "slug-a",
      "target": "slug-b",
      "type": "advisor|collaborator|colleague|sibling|couple|rival",
      "evidence": "One-line explanation"
    }
  ]
}
```

### Edge Types

| Type | Meaning | Direction |
|------|---------|-----------|
| `advisor` | source advised target (PhD/postdoc) | source → target |
| `collaborator` | frequent co-authors (3+ papers or joint project) | bidirectional |
| `colleague` | same institution, not advisor/student | bidirectional |
| `sibling` | same advisor (学术同门) | bidirectional |
| `couple` | confirmed or strongly suspected personal relationship | bidirectional |
| `rival` | competing on same problem/narrative | bidirectional |

---

## Mode 1: Sync

Extract structure from profiles into graph.json.

### Sync Step 1: Scan Profiles

For each `profiles/*.md` file:

1. **Skip** non-person files (README, files matching known non-person slugs)
2. **Extract identity** from `## 身份锚点` section:
   - `name`: from `# Title` (English name before parentheses)
   - `chinese_name`: from `# Title` (text inside parentheses)
   - `institution`: from `现任:` or `现职:` line
3. **Extract edges** from `## 师门谱系` section:
   - `### 导师` → edge type `advisor` (advisor → this person)
   - `### 导师的导师` → edge type `advisor` (grandparent → parent)
   - `### 同门` → edge type `sibling` (this person ↔ each sibling)
   - `### 频繁合作者` → edge type `collaborator`
   - `### 学生/PhD/alumni/博后` → edge type `advisor` (this person → student)
4. **Extract edges** from relationship analysis sections in overviews:
   - Look for `couple` signals (e.g., "极高可能为伴侣")
   - Look for `rival` signals (e.g., "直接竞争关系")
5. **Extract mentioned people** from `## 师门谱系` who don't have profiles:
   - Create unprofiled nodes with `mentioned_in` pointing to this profile

### Sync Step 2: Merge with Existing Graph

- If node exists → **update** empty fields only (never overwrite)
- If node new → **add**
- If edge exists (same source, target, type) → **skip**
- Never delete existing nodes or edges

### Sync Step 3: Update has_profile

Check file existence for all nodes.

### Sync Step 4: Validate & Write

1. Remove orphan nodes (no edges AND not has_profile AND empty mentioned_in)
2. Sort nodes by id, edges by (source, target)
3. Write `graph.json` with `indent=2, ensure_ascii=False`
4. Print summary

### Sync Implementation

Run `python3 ~/unbox-output/scripts/graph_sync.py` (v2). See `references/sync-script.md` for details.

Key properties:
- Self-contained (stdlib only)
- Idempotent (running twice = same result)
- Handles 7+ format variants: bullets, tables, code-block trees, colon-headers, paragraph-style, CJK name swap, mixed formats
- Normalizes `relation` → `type` for legacy edges
- Strict `is_person_name()` filter rejects institutions, projects, years
- ~3500 edges extracted from 230 profiles

---

## Mode 2: Enrich (formerly cross-ref)

Cross-reference text between profiles that share edges. Move information from profile A to profile B when A mentions facts about B that B's own profile lacks.

**Key constraint: NO external research.** All evidence comes from existing profiles. This is pure information redistribution.

### Enrich Step 1: Build Registry

1. Load `graph.json` — use edges to know which pairs of profiles are connected
2. For each profiled node, extract: english_name, chinese_name, slug, aliases
3. Print: `Found N profiled people, M edges between profiled pairs`

### Enrich Step 2: Extract Cross-Mentions (parallel subagents)

Split profiles into groups of ~7. For each group, spawn one subagent with:
- The full registry (all people, not just their group)
- The full text of their group's reports
- The extraction prompt from `references/extract-prompt.md`

Each subagent outputs structured cross-mentions:
```
SOURCE: {slug of report containing the mention}
ABOUT: {slug of person being mentioned}
TYPE: {relationship | event | date | affiliation | personality}
FACT: {the specific fact, one line}
CONTEXT: {surrounding sentence}
```

### Enrich Step 3: Apply Changes (parallel subagents)

Group mentions by `ABOUT` person. For each person with cross-mentions, classify each as:
- **BACKFILL** — info not present in person's own report → add
- **CONFIRM** — already present → skip
- **CONFLICT** — contradicts existing info → resolve by evidence quality

Apply changes using the merge protocol:
- Format: `> 📎 交叉补充 ({date}, 来源: {source_slug}.md): {fact}`
- Idempotency: check for existing `📎` markers before adding

### Enrich Step 4: Generate Report

Create `_cross-ref.md` with:
- Backfills applied (count + table)
- Conflicts resolved (count + table)
- Unresolvable conflicts (if any)

Clean up temp files.

### Important Constraints

- **No external research** — do not Google, fetch URLs, or call any API
- **Exception for conflicts**: If both sides cite a URL, MAY fetch those specific URLs
- **Preserve report structure** — only append within existing sections
- **Idempotent** — running twice should not duplicate backfills

### Enrich Reference Files

- `references/extract-prompt.md` — subagent prompt for extraction phase
- `references/apply-prompt.md` — subagent prompt for apply phase
- `references/merge-utils.md` — shared merge protocol (also used by backfill)

---

## Mode 3: Think

Structural analysis of graph.json to recommend next actions.

### Think Step 1: Load & Compute Metrics

```python
degree = {}          # total edges per node
profiled_degree = {} # edges to other profiled nodes
# Global: total_nodes, profiled_nodes, total_edges
```

### Think Step 2: Run Strategies

#### Strategy A: Boundary Expansion

Find unprofiled nodes that would add the most connectivity if profiled.

```
Score = len(mentioned_in) * 2 + degree + bonus
  bonus: +3 if node is advisor of 2+ profiled people
  bonus: +2 if node bridges two otherwise-disconnected clusters
```

#### Strategy B: Cluster Analysis

Find dense subgraphs (3+ mutually connected profiled nodes).

#### Strategy C: Bridge Nodes

Find profiled nodes that connect otherwise-separate clusters.

#### Strategy D: Temporal Corridors (future)

Requires `year_start`/`year_end` on edges. Not yet populated.

### Think Step 3: Present Recommendations

```markdown
## Unbox Graph Think

Graph: {N} nodes ({M} profiled), {E} edges

### 🌱 Expansion Candidates
| # | Person | Score | Why |
|---|--------|-------|-----|

### 🔬 Dense Clusters
| Cluster | Members | Opportunity |
|---------|---------|-------------|

### 🌉 Bridge Nodes
| Person | Connects | Value |
|--------|----------|-------|

### 💡 Structural Insights
- [topology observations]

---
Quick actions:
- "跑 expansion top 3" → `/unbox` top 3
- "跑 enrich" → `/unbox-graph enrich`
- "跑 sync" → `/unbox-graph sync`
```

---

## Design Principles

1. **Sync is deterministic** — same profiles → same graph
2. **Enrich never searches the web** — pure redistribution of existing information
3. **Think never modifies files** — read-only analysis
4. **All three modes are idempotent** — safe to re-run
5. **Incremental** — merge, never replace

## Relationship to Other Skills

| Skill | Role | Status |
|-------|------|--------|
| `/unbox` | Creates profiles | Active — run sync after |
| `/unbox --mode=backfill` | Web search to fill gaps in profiles | Active |
| `/unbox-graph sync` | Structure extraction → graph.json | **This skill** |
| `/unbox-graph enrich` | Text cross-reference between profiles | **This skill** (absorbs cross-ref) |
| `/unbox-graph think` | Structural analysis → recommendations | **This skill** (absorbs unbox-next) |
| `/unbox-cross-ref` | **DEPRECATED** → use `enrich` | Deprecated |
| `/unbox-next` | **DEPRECATED** → use `think` | Deprecated |

## Deprecation

- `/unbox-next` → `/unbox-graph think`
- `/unbox-cross-ref` → `/unbox-graph enrich`

Both deprecated skills retain their files with deprecation notices pointing here.
