# Sync Script Reference

When executing `/unbox-graph sync`, run the script at `~/unbox-output/scripts/graph_sync.py`.

```bash
python3 ~/unbox-output/scripts/graph_sync.py
```

The v2 script handles ALL profile format variants (see below). The original v1 script is preserved below for reference.

## Format Variants Handled (v2)

1. **Standard bullet lists** with `### ` subsection headers
2. **Colon-in-header**: `### 导师: Name (Inst)` — person in header, bullets below are descriptions
3. **Code block trees**: `├── Name (inst)` / `└── Name` with tree indentation
4. **Tables**: `| Name | Role | ...` with bold or plain names
5. **No subsection headers**: classify from context keywords
6. **Paragraph-style**: `**Name** (info): description text`
7. **CJK name swap**: `朱军 (Jun Zhu)` → uses English name for slug
8. **Alternative section names**: `师承与学术网络`, `Academic Lineage`, `合作网络`, etc.

## Original Script (v1)

```python
#!/usr/bin/env python3
"""
unbox-graph sync: Extract nodes and edges from profiles, merge into graph.json.
Idempotent — running twice produces the same result.
"""

import json
import os
import re
from pathlib import Path
from collections import defaultdict

PROFILE_DIR = Path(os.path.expanduser("~/unbox-output/profiles"))
GRAPH_PATH = Path(os.path.expanduser("~/unbox-output/graph.json"))
OVERVIEW_DIR = Path(os.path.expanduser("~/unbox-output/overviews"))

# Non-person files to skip
SKIP_SLUGS = {'README', '1ce0ear', 'annevi', 'baimeow', 'li4n0', 'wuhan005', 'xzhou'}


def slugify(name: str) -> str:
    """Convert a name to slug format."""
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


def extract_person_from_line(line: str) -> tuple:
    """Extract (name, institution) from a bullet line. Two-step: try bold, then plain."""
    # Must start with bullet
    m = re.match(r'[-*]\s+(.+)', line)
    if not m:
        return ('', '')
    content = m.group(1).strip()
    
    # Try bold pattern: **Name** or **Name (Inst)**
    m2 = re.match(r'\*\*(.+?)\*\*\s*(?:[（(]([^)）]+)[)）])?', content)
    if m2:
        name = m2.group(1).strip()
        # Remove Chinese characters from name for slug, but keep for display
        inst = (m2.group(2) or '').strip()
        return (name, inst)
    
    # Plain pattern: Name (Inst) or just Name
    m3 = re.match(r'([^(（\[*]+?)\s*(?:[（(]([^)）]+)[)）])?(?:\s*[-—:].*)?$', content)
    if m3:
        name = m3.group(1).strip()
        inst = (m3.group(2) or '').strip()
        if name:
            return (name, inst)
    
    return ('', '')


def extract_from_profile(filepath: Path) -> dict:
    """Extract node info and edges from a single profile."""
    slug = filepath.stem
    text = filepath.read_text(encoding='utf-8')
    lines = text.split('\n')
    
    result = {
        'node': {
            'id': slug,
            'name': '',
            'chinese_name': '',
            'institution': '',
            'has_profile': True,
        },
        'edges': [],
        'mentions': [],  # (slug_or_name, name, institution) for unprofiled people
    }
    
    # Extract name from title line
    for line in lines[:5]:
        if line.startswith('# '):
            title = line[2:].strip()
            # Pattern: "English Name (中文名)"
            m = re.match(r'^(.+?)\s*[（(](.+?)[)）]', title)
            if m:
                result['node']['name'] = m.group(1).strip()
                result['node']['chinese_name'] = m.group(2).strip()
            else:
                result['node']['name'] = title
            break
    
    # Extract institution from 身份锚点 section
    in_anchor = False
    for line in lines:
        if '身份锚点' in line:
            in_anchor = True
            continue
        if in_anchor:
            if line.startswith('## ') and '身份锚点' not in line:
                break
            # Look for 现任/现职
            m = re.match(r'[-|]\s*现[任职][:|：]\s*\**(.+?)\**\s*$', line)
            if m:
                inst = m.group(1).strip()
                # Clean markdown
                inst = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', inst)
                inst = re.sub(r'\*+', '', inst)
                result['node']['institution'] = inst[:100]  # truncate
                break
            # Also check table format
            m = re.match(r'\|\s*现职\s*\|\s*(.+?)\s*\|', line)
            if m:
                inst = m.group(1).strip()
                inst = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', inst)
                inst = re.sub(r'\*+', '', inst)
                result['node']['institution'] = inst[:100]
                break
    
    # Extract edges from 师门谱系 section
    in_lineage = False
    current_subsection = ''
    for line in lines:
        if '师门谱系' in line and line.startswith('#'):
            in_lineage = True
            continue
        if in_lineage:
            if line.startswith('## ') and '师门谱系' not in line:
                break
            if line.startswith('### '):
                current_subsection = line.strip('# ').strip()
                continue
            
            person_name, person_inst = extract_person_from_line(line)
            if not person_name:
                continue
            
            # Skip if it's "本人" marker or empty
            if '本人' in line or '←' in line:
                continue
            # Skip section headers that got caught
            if person_name in ('导师', '同门', '频繁合作者', '导师的导师'):
                continue
            
            person_slug = slugify(person_name)
            if not person_slug or person_slug == slug:
                continue
            
            # Determine edge type and direction
            if '导师' in current_subsection and '同门' not in current_subsection:
                edge = {
                    'source': person_slug,
                    'target': slug,
                    'type': 'advisor',
                    'evidence': f'Advisor mentioned in {slug} profile'
                }
                if person_inst:
                    edge['evidence'] = f'{current_subsection} at {person_inst}'
                result['edges'].append(edge)
                result['mentions'].append((person_slug, person_name, person_inst))
                
            elif '同门' in current_subsection:
                edge = {
                    'source': slug,
                    'target': person_slug,
                    'type': 'sibling',
                    'evidence': f'Same advisor, listed in {slug} profile'
                }
                result['edges'].append(edge)
                result['mentions'].append((person_slug, person_name, person_inst))
                
            elif '合作' in current_subsection:
                edge = {
                    'source': slug,
                    'target': person_slug,
                    'type': 'collaborator',
                    'evidence': f'Frequent collaborator in {slug} profile'
                }
                result['edges'].append(edge)
                result['mentions'].append((person_slug, person_name, person_inst))
                
            elif any(k in current_subsection for k in ('学生', 'PhD', 'alumni', '博后')):
                edge = {
                    'source': slug,
                    'target': person_slug,
                    'type': 'advisor',
                    'evidence': f'Student/postdoc listed in {slug} profile'
                }
                if person_inst:
                    edge['evidence'] = f'Student at {person_inst}'
                result['edges'].append(edge)
                result['mentions'].append((person_slug, person_name, person_inst))
    
    return result


def extract_from_overviews() -> list:
    """Extract special edges (couple, rival) from overview files."""
    edges = []
    if not OVERVIEW_DIR.exists():
        return edges
    
    for f in OVERVIEW_DIR.glob('*.md'):
        text = f.read_text(encoding='utf-8')
        
        # Look for couple signals
        couple_patterns = [
            r'(\w[\w-]+)\s*[×x]\s*(\w[\w-]+).*(?:couple|伴侣|关系)',
            r'极高可能为伴侣',
        ]
        # Simple heuristic: find "X × Y 关系" patterns in section headers
        for m in re.finditer(r'###?\s+(.+?)\s*[×x]\s*(.+?)\s+关系', text):
            name_a = m.group(1).strip()
            name_b = m.group(2).strip()
            slug_a = slugify(name_a)
            slug_b = slugify(name_b)
            if slug_a and slug_b:
                edges.append({
                    'source': slug_a,
                    'target': slug_b,
                    'type': 'couple',
                    'evidence': f'Relationship analysis in {f.stem}'
                })
        
        # Look for rival/competition signals
        if '竞争关系' in text or '直接竞争' in text:
            # This is harder to parse generically; skip for now
            pass
    
    return edges


def merge_graph(extractions: list, overview_edges: list) -> dict:
    """Merge all extractions into a single graph, preserving existing data."""
    # Load existing graph
    if GRAPH_PATH.exists():
        with open(GRAPH_PATH, 'r', encoding='utf-8') as f:
            graph = json.load(f)
    else:
        graph = {'nodes': [], 'edges': []}
    
    # Index existing
    node_map = {n['id']: n for n in graph['nodes']}
    edge_set = {(e['source'], e['target'], e['type']) for e in graph['edges']}
    
    stats = {'nodes_added': 0, 'nodes_updated': 0, 'edges_added': 0}
    
    # Process extractions
    for ext in extractions:
        node = ext['node']
        nid = node['id']
        
        # Merge node
        if nid in node_map:
            existing = node_map[nid]
            updated = False
            for field in ('name', 'chinese_name', 'institution'):
                if node.get(field) and node[field] != existing.get(field, ''):
                    if not existing.get(field):  # only update if existing is empty
                        existing[field] = node[field]
                        updated = True
            existing['has_profile'] = node['has_profile']
            if updated:
                stats['nodes_updated'] += 1
        else:
            node_map[nid] = node
            stats['nodes_added'] += 1
        
        # Merge edges
        for edge in ext['edges']:
            key = (edge['source'], edge['target'], edge['type'])
            reverse_key = (edge['target'], edge['source'], edge['type'])
            if key not in edge_set and reverse_key not in edge_set:
                graph['edges'].append(edge)
                edge_set.add(key)
                stats['edges_added'] += 1
        
        # Merge mentions (create unprofiled nodes)
        for mention_slug, mention_name, mention_inst in ext['mentions']:
            if mention_slug not in node_map:
                node_map[mention_slug] = {
                    'id': mention_slug,
                    'name': mention_name,
                    'institution': mention_inst,
                    'has_profile': os.path.exists(PROFILE_DIR / f'{mention_slug}.md'),
                    'mentioned_in': [nid],
                }
                stats['nodes_added'] += 1
            else:
                # Update mentioned_in
                existing = node_map[mention_slug]
                if 'mentioned_in' not in existing:
                    existing['mentioned_in'] = []
                if nid not in existing['mentioned_in']:
                    existing['mentioned_in'].append(nid)
    
    # Process overview edges
    for edge in overview_edges:
        key = (edge['source'], edge['target'], edge['type'])
        reverse_key = (edge['target'], edge['source'], edge['type'])
        if key not in edge_set and reverse_key not in edge_set:
            graph['edges'].append(edge)
            edge_set.add(key)
            stats['edges_added'] += 1
    
    # Update has_profile for all nodes
    for nid, node in node_map.items():
        node['has_profile'] = (PROFILE_DIR / f'{nid}.md').exists()
    
    # Remove orphans (no edges, no profile, no mentions)
    edge_nodes = set()
    for e in graph['edges']:
        edge_nodes.add(e['source'])
        edge_nodes.add(e['target'])
    
    final_nodes = []
    for nid, node in sorted(node_map.items()):
        if node.get('has_profile') or nid in edge_nodes or node.get('mentioned_in'):
            final_nodes.append(node)
    
    # Sort
    graph['nodes'] = sorted(final_nodes, key=lambda n: n['id'])
    graph['edges'] = sorted(graph['edges'], key=lambda e: (e['source'], e['target'], e['type']))
    
    return graph, stats


def main():
    # Collect all profiles
    profiles = [f for f in PROFILE_DIR.glob('*.md') if f.stem not in SKIP_SLUGS]
    print(f"Scanning {len(profiles)} profile files...")
    
    # Extract from each
    extractions = []
    errors = []
    for p in profiles:
        try:
            ext = extract_from_profile(p)
            extractions.append(ext)
        except Exception as e:
            errors.append(f"{p.stem}: {e}")
    
    if errors:
        print(f"Extraction errors ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")
    
    # Extract from overviews
    overview_edges = extract_from_overviews()
    print(f"Found {len(overview_edges)} special edges from overviews")
    
    # Merge
    graph, stats = merge_graph(extractions, overview_edges)
    
    # Write
    with open(GRAPH_PATH, 'w', encoding='utf-8') as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    
    # Summary
    profiled = sum(1 for n in graph['nodes'] if n.get('has_profile'))
    print(f"\n=== Sync Complete ===")
    print(f"Nodes: {len(graph['nodes'])} ({profiled} profiled)")
    print(f"Edges: {len(graph['edges'])}")
    print(f"Changes: +{stats['nodes_added']} nodes, ~{stats['nodes_updated']} updated, +{stats['edges_added']} edges")


if __name__ == '__main__':
    main()
```

## Usage

```bash
python3 ~/unbox-output/scripts/graph_sync.py
```

## Notes

- v2 handles 7+ format variants (bullets, trees, tables, paragraphs, colon-headers, CJK names)
- Edges that were manually added to graph.json are preserved (additive only)
- `mentioned_in` arrays are deduplicated
- Orphan nodes (no profile, no edges, no mentions) are removed during cleanup
- Idempotent: running multiple times produces the same output
- Strict `is_person_name()` filter rejects institutions, projects, years, and descriptions
- CJK-only names automatically swap with parenthesized English names for valid slugs

## Known Limitations

- Does not parse `## 发表` section for co-authorship edges (too noisy)
- Does not extract temporal data (start/end years) from edges — future enhancement
- `rival` edges must be added manually or from overview analysis
- `couple` edges from overviews require specific `### X × Y 关系` header format
- Profiles with no lineage section at all (e.g., `pingchuan-ma`) will have zero edges
