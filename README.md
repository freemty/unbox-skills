# unbox-skills

Researcher profiling toolkit for Claude Code. Three skills that work together to build and maintain a knowledge graph of academic researchers.

## Skills

| Skill | Purpose | Trigger |
|-------|---------|---------|
| `unbox` | Deep-dive investigation of researchers | `/unbox <name or URL>` |
| `unbox-graph` | Graph sync, cross-reference enrichment, structural analysis | `/unbox-graph sync\|enrich\|think` |
| `unbox-to-wiki` | Compile profiles into selfOS wiki entries | `/unbox-to-wiki <name>` |

## Workflow

```
/unbox <target>          # investigate researcher(s), write profiles
/unbox-graph sync        # extract relationships into graph.json
/unbox-graph enrich      # cross-reference facts between connected profiles
/unbox-graph think       # structural analysis, recommend next targets
```

## Setup

Symlink each skill into `~/.claude/skills/`:

```bash
ln -sf $(pwd)/unbox ~/.claude/skills/unbox
ln -sf $(pwd)/unbox-graph ~/.claude/skills/unbox-graph
ln -sf $(pwd)/unbox-to-wiki ~/.claude/skills/unbox-to-wiki
```

## Scripts

- `scripts/graph_sync.py` — Standalone Python script that extracts nodes/edges from markdown profiles into `graph.json`. Stdlib only, idempotent.

## Output

Skill output (profiles, graph.json, overviews) lives in a separate repo: [unbox-output](https://github.com/freemty/unbox-output).

## Architecture

```
unbox-skills/           # this repo (tools)
  unbox/                # full investigation skill
  unbox-graph/          # graph maintenance skill
  unbox-to-wiki/        # wiki compilation skill
  scripts/              # shared scripts

unbox-output/           # separate repo (data)
  profiles/             # researcher markdown profiles
  overviews/            # batch summary reports
  graph.json            # relationship graph
  scripts/              # runtime copy of graph_sync.py
```
