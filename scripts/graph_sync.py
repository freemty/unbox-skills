#!/usr/bin/env python3
"""
unbox-graph sync v2: Extract nodes and edges from profiles, merge into graph.json.

Handles ALL format variants:
1. Standard bullet lists with ### subsections (person per bullet)
2. Colon-in-header: ### 导师: Name (Inst) — person in header, bullets are descriptions
3. Code block trees with ├── └── │ characters
4. Tables with | Name | Role | ... |
5. No subsection headers (classify from context)
6. Alternative section names (师承与学术网络, etc.)

Idempotent — running twice produces the same result.
"""

import json
import os
import re
from pathlib import Path
from collections import defaultdict

_REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = _REPO_ROOT / "profiles"
GRAPH_PATH = _REPO_ROOT / "graph.json"
OVERVIEW_DIR = _REPO_ROOT / "overviews"

SKIP_SLUGS = {'README', '1ce0ear', 'annevi', 'baimeow', 'li4n0', 'wuhan005', 'xzhou'}

LINEAGE_KEYWORDS = [
    '师门', '谱系', '师承', '学术网络', '关系网', '合作网',
    'Mentorship', '师徒', '导师谱系', '人际关系网络', '研究生谱系',
    '师门关系', '师门网络',
    'Academic Lineage', 'Lineage',
]

# ── Relationship type constants ──────────────────────────────────
REL_ADVISOR = 'advisor'
REL_STUDENT = 'student'
REL_SIBLING = 'sibling'
REL_COLLABORATOR = 'collaborator'
REL_COLLEAGUE = 'colleague'
REL_COUPLE = 'couple'
REL_GRAND_ADVISOR = 'grand-advisor'
REL_UNKNOWN = 'unknown'

BIDIRECTIONAL_TYPES = frozenset({REL_SIBLING, REL_COLLABORATOR, REL_COLLEAGUE, REL_COUPLE})

# Shared keyword → relation type mapping
_RELATION_KEYWORDS = {
    REL_GRAND_ADVISOR: ['导师的导师', '师祖', 'grand-advisor', "advisor's advisor"],
    REL_ADVISOR: ['导师', 'advisor', 'mentor', '博导', '硕导', '上级',
                  'supervisor', 'supervised', '实习', '暑研', 'phd 导师',
                  '博后导师', '联合导师', '合作导师',
                  'phd committee', '委员会', 'phd advisor', 'postdoc advisor'],
    REL_STUDENT: ['学生', 'alumni', '博后', 'postdoc', '门生',
                  '毕业', 'student', '实验室成员', 'lab member',
                  '在读', '培养', '博士生', '下游', 'downstream',
                  'mentees', 'phd students', 'graduates'],
    REL_SIBLING: ['同门', 'sibling', '同组', '同期', '同班'],
    REL_COLLABORATOR: ['合作', 'collaborator', 'co-author', '合著',
                       '关系网', '学术网络', '核心合作', '密切合作',
                       '频繁合作'],
    REL_COLLEAGUE: ['同事', 'colleague', '团队成员'],
}

MAX_SLUG_LEN = 35
MIN_SLUG_LEN = 3
MAX_SLUG_PARTS = 4
EVIDENCE_TRUNCATE = 200
INST_TRUNCATE = 100


def _classify_text(text: str) -> str:
    t = text.lower()
    for rel_type, keywords in _RELATION_KEYWORDS.items():
        if any(k in t for k in keywords):
            return rel_type
    return REL_UNKNOWN


def edge_keys(source: str, target: str, etype: str) -> set:
    keys = {(source, target, etype)}
    if etype in BIDIRECTIONAL_TYPES:
        keys.add((target, source, etype))
    return keys


# ── Slug function ──────────────────────────────────────────────────

def slugify(name: str) -> str:
    s = name.lower().strip()
    # Check if outer text (outside parentheses) has Latin chars
    outer = re.sub(r'[（(][^)）]*[)）]', '', s).strip()
    outer_latin = re.sub(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\s]', '', outer)
    if not outer_latin:
        # Outer is pure CJK/empty — try to use parenthetical English as name
        # e.g., "陈丹琦 (Danqi Chen)" → "danqi chen"
        paren_match = re.search(r'[（(]([^)）]+)[)）]', s)
        if paren_match:
            paren_content = paren_match.group(1).strip()
            # Only use if it looks like a person name (2+ words, not institution)
            paren_slug = re.sub(r'[^a-z0-9\s-]', '', paren_content)
            paren_slug = re.sub(r'[\s_]+', '-', paren_slug.strip()).strip('-')
            paren_parts = paren_slug.split('-')
            if len(paren_parts) >= 2 and not (set(paren_parts) & NON_PERSON_WORDS):
                return re.sub(r'-+', '-', paren_slug)
    # Default: remove parentheticals, strip CJK
    s = re.sub(r'[（(][^)）]*[)）]', '', s)
    s = re.sub(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', '', s)
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s.strip())
    s = re.sub(r'-+', '-', s).strip('-')
    return s


# ── Name validation (strict) ──────────────────────────────────────

# Words that signal "this is NOT a person name" (as slug parts)
NON_PERSON_WORDS = {
    # Institutions / companies
    'google', 'meta', 'openai', 'microsoft', 'waymo', 'nvidia', 'apple', 'amazon',
    'facebook', 'deepmind', 'bytedance', 'tencent', 'baidu', 'alibaba', 'huawei',
    'intel', 'adobe', 'tesla', 'uber', 'twitter', 'ibm', 'xai', 'anthropic',
    'inceptive', 'noetik', 'robbyant', 'clarifai', 'meshcapade',
    # Academic institutions
    'mit', 'stanford', 'berkeley', 'princeton', 'cmu', 'harvard', 'yale', 'caltech',
    'oxford', 'cambridge', 'cornell', 'columbia', 'nyu', 'ucla', 'uiuc', 'uw',
    'tsinghua', 'peking', 'zju', 'sjtu', 'ustc', 'fudan', 'nus', 'eth',
    'hkust', 'cuhk', 'usc', 'upenn', 'uchicago', 'gatech', 'umich', 'purdue',
    'duke', 'brown', 'rice', 'jhu', 'unc', 'ttic',
    # Labs / groups
    'csail', 'bair', 'fair', 'msr', 'lab', 'group', 'team', 'center',
    'institute', 'department', 'school', 'division', 'unit',
    # Roles/titles
    'professor', 'assistant', 'associate', 'postdoc', 'researcher', 'engineer',
    'director', 'manager', 'scientist', 'fellow', 'lecturer', 'instructor',
    'advisor', 'student', 'intern', 'visitor', 'ceo', 'cto', 'cfo', 'vp',
    # Academic terms
    'phd', 'thesis', 'paper', 'conference', 'journal', 'award', 'prize',
    'neurips', 'icml', 'iclr', 'cvpr', 'eccv', 'iccv', 'acl', 'emnlp', 'naacl',
    'aaai', 'ijcai', 'siggraph', 'sigkdd', 'www', 'arxiv', 'pmlr',
    'ieee', 'acm', 'aaas', 'pami', 'tpami',
    'benchmark', 'dataset', 'workshop', 'tutorial', 'keynote', 'oral', 'spotlight',
    # Technical terms / project names (NOT people)
    'model', 'models', 'dataset', 'algorithm', 'framework', 'library', 'system',
    'transformer', 'attention', 'diffusion', 'generative', 'adversarial',
    'neural', 'network', 'learning', 'training', 'inference',
    'consistency', 'contrastive', 'reinforcement',
    'vision', '3d', '2d', 'slam', 'nerf', 'vit', 'llm', 'vlm', 'gan', 'vae',
    'detection', 'segmentation', 'generation', 'recognition', 'tracking',
    'perception', 'reasoning', 'optimization', 'architecture',
    'pretraining', 'finetuning', 'alignment', 'distillation',
    'co-author', 'coauthor', 'contributor',
    # Misc non-person
    'tenure', 'track', 'sabbatical', 'emeritus',
    'chapter', 'section', 'appendix', 'table', 'figure',
    'github', 'issues', 'score', 'demo', 'blog', 'podcast',
    'pnas', 'nature', 'science', 'communications',
    # Ambiguous short words that are usually not person slugs
    'affiliated', 'butterfly', 'factorizations',
    'sports', 'music', 'audio', 'video', 'image', 'text',
    'robotics', 'autonomous', 'driving', 'navigation',
    'medical', 'clinical', 'health', 'biology', 'chemistry', 'physics',
}

# Single-word slugs that are institution abbreviations, not person names
_SINGLE_WORD_REJECTS = {
    'ucsd', 'ucsb', 'ucsc', 'uci', 'ucd', 'msra', 'cuhk', 'hkust',
    'genforce', 'mapreduce', 'kokoni', 'gps', 'ivg',
    'industry', 'sensor', 'mmlab', 'megvii',
    'sensetime', 'pjlab', 'shanghaitech', 'westlake',
}

# Compiled patterns for efficiency
_YEAR_PATTERN = re.compile(r'^\d{4}')
_ALL_DIGITS = re.compile(r'^\d+$')
_URL_PATTERN = re.compile(r'https?://')


def is_person_name(name: str) -> bool:
    """Strict check: does this look like a person's name?"""
    name = name.strip()
    if not name:
        return False

    # Reject names with arrow characters (always descriptions like "A → B")
    if any(c in name for c in '→←↔'):
        return False

    # Reject if original name contains CJK function words indicating description
    _DESC_PATTERNS = re.compile(
        r'[\u4e00-\u9fff].*的[\u4e00-\u9fff]|'  # X的Y pattern
        r'博士生|研究员|研究生|工程师|调度|团队|'
        r'空中三角|测量|课题组|实验室'
    )
    if _DESC_PATTERNS.search(name):
        return False

    slug = slugify(name)
    if not slug or len(slug) < MIN_SLUG_LEN:
        return False

    if len(slug) > MAX_SLUG_LEN:
        return False

    # Reject year-like slugs
    if _YEAR_PATTERN.match(slug):
        return False

    # Reject all-digits
    if _ALL_DIGITS.match(slug):
        return False

    # Reject URLs
    if _URL_PATTERN.search(name):
        return False

    # Reject single-word slugs that are known institution/acronym abbreviations
    if '-' not in slug and slug in _SINGLE_WORD_REJECTS:
        return False

    # Reject if slug contains ANY known non-person word
    slug_parts = set(slug.split('-'))
    if slug_parts & NON_PERSON_WORDS:
        return False

    if len(slug.split('-')) > MAX_SLUG_PARTS:
        return False

    # Reject if name starts with common non-name patterns
    lower = name.lower().strip()
    reject_starts = [
        '清华', '北大', '上海', '中科院', '浙大', '复旦', '中山', '武汉',
        '研究', '合作', '实验室', '论文', '代表', '核心', '关键', '目前',
        '中国', '国际', '全球', '世界', '美国', '日本', '韩国',
        'the ', 'a ', 'an ', 'all ', 'no ', 'yes ', 'this ', 'that ',
        'phd', 'msc', 'bsc', 'postdoc', 'master', 'bachelor',
        '现任', '前任', '曾任', '关于', '注意', '补充',
        'also', 'note', 'see ', 'cf.', 'e.g.', 'i.e.',
    ]
    for prefix in reject_starts:
        if lower.startswith(prefix):
            return False

    # Name should have at least one capitalized word (English) or 2-4 CJK chars
    has_capitalized = bool(re.search(r'[A-Z][a-z]+', name))
    has_cjk_name = bool(re.match(r'^[\u4e00-\u9fff]{2,4}$', name.strip()))
    # Also allow: CJK + English mix like "陈键飞 (Jianfei Chen)"
    has_cjk_mixed = bool(re.search(r'[\u4e00-\u9fff]{2,4}', name))

    if not has_capitalized and not has_cjk_name and not has_cjk_mixed:
        return False

    # Reject if it contains too many connecting words (not a name-like structure)
    connecting_words = ['的', '是', '与', '和', '在', '到', '从', '为', '被',
                        'the', 'and', 'was', 'are', 'for', 'with', 'from',
                        'this', 'that', 'has', 'had', 'will', 'not']
    word_count = sum(1 for w in connecting_words if f' {w} ' in f' {lower} ' or
                     (len(w) == 1 and w in lower))  # CJK single-char words
    if word_count >= 2:
        return False

    # Reject known project/model names that look like person names
    project_names = {
        'llada', 'prolificdreamer', 'vflow', 'flownet', 'unet', 'resnet',
        'maskgit', 'muse', 'dalle', 'sora', 'gpt', 'bert', 'roberta',
        'llava', 'sam', 'dino', 'clip', 'moco', 'mae', 'simclr',
        'eg3d', '3dmatch', 'pointnet', 'nerf', 'gaussians',
        'dreamfusion', 'imagenet', 'coco', 'shapenet', 'scannet',
        'agoraio', 'aiaiai',
    }
    if slug in project_names or slug.replace('-', '') in project_names:
        return False

    # Reject slugs that match "topic-X" patterns (not person names)
    if re.match(r'^(ai|ml|dl|nlp|cv|rl)[-]', slug):
        return False

    # Reject slugs ending with non-person suffixes
    non_person_suffixes = ['-research', '-lab', '-group', '-team', '-center',
                           '-institute', '-award', '-prize', '-course',
                           '-workshop', '-seminar', '-benchmark']
    for suffix in non_person_suffixes:
        if slug.endswith(suffix):
            return False

    return True


# _classify_text and _classify_text unified into _classify_text above


# ── Person extraction from different formats ──────────────────────

def extract_name_and_inst(text: str) -> tuple:
    """
    Extract (name, inst_or_info) from text like:
      "Name (inst)" or "中文名 (English Name)" or "**Name** (inst)"

    IMPORTANT: If the primary name (before parens) produces an empty slug
    (e.g., pure CJK name like 朱军), try using the parenthesized content
    as the name (e.g., "Jun Zhu").

    Returns (display_name, info) where display_name is chosen to produce a valid slug.
    """
    text = text.strip()
    if not text:
        return ('', '')

    # Remove bold markers
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)

    # Try: Name (content)
    m = re.match(r'^([^(（\[\n]+?)\s*[（(]([^)）]+)[)）]', text)
    if m:
        primary = m.group(1).strip().rstrip(',;:：，；')
        paren = m.group(2).strip()

        # If primary produces valid slug, use it
        if slugify(primary):
            return (primary, paren)

        # If primary is CJK-only, try using paren content as the name
        # e.g., 朱军 (Jun Zhu) → name="Jun Zhu", info="朱军"
        if slugify(paren):
            return (paren, primary)

        # Neither produces a slug
        return (primary, paren)

    # Try: Name [content]
    m = re.match(r'^([^(\[\n]+?)\s*\[([^\]]+)\]', text)
    if m:
        primary = m.group(1).strip().rstrip(',;:：，；')
        bracket = m.group(2).strip()
        if slugify(primary):
            return (primary, bracket)
        if slugify(bracket):
            return (bracket, primary)
        return (primary, bracket)

    # Just a name — up to common delimiters
    m = re.match(r'^([^(（\[\n,;—→]+)', text)
    if m:
        name = m.group(1).strip().rstrip(',;:：，；')
        return (name, '')

    return ('', '')


def extract_person_from_bullet(line: str) -> tuple:
    """Extract (name, institution) from a bullet line. Returns ('', '') if not a person.

    Also returns a role_hint (str) when the bullet uses label:value format.
    """
    m = re.match(r'[-*•]\s+(.+)', line.strip())
    if not m:
        return ('', '')
    content = m.group(1).strip()

    # Pattern 1: **Label**: Person Name (inst)
    # e.g., "**导师**: Yann LeCun (2018 Turing Award)"
    # e.g., "**重要合作者**: Xiang Zhang"
    m_label = re.match(r'\*\*([^*]+?)\*\*\s*[:：]\s*(.+)', content)
    if m_label:
        label = m_label.group(1).strip()
        value = m_label.group(2).strip()
        name, inst = extract_name_and_inst(value)
        if name and is_person_name(name):
            return (name, inst)
        # Value might have multiple names separated by commas — try first one
        first_name = re.split(r'[,，;；]', value)[0].strip()
        fn, fi = extract_name_and_inst(first_name)
        if fn and is_person_name(fn):
            return (fn, fi)
        return ('', '')

    # Pattern 2: **Name** (inst) — bold person name
    m2 = re.match(r'\*\*([^*]+?)\*\*\s*(?:[（(]([^)）]+)[)）])?', content)
    if m2:
        name = m2.group(1).strip()
        inst = (m2.group(2) or '').strip()
        if is_person_name(name):
            return (name, inst)
        return ('', '')

    # Pattern 3: Plain — Name (Inst) or Name — description
    name, inst = extract_name_and_inst(content)
    if name and is_person_name(name):
        return (name, inst)

    return ('', '')


def extract_person_from_table_row(row: str) -> tuple:
    """Extract (name, role_hint) from a markdown table row."""
    cells = [c.strip() for c in row.split('|')]
    cells = [c for c in cells if c]

    if len(cells) < 2:
        return ('', '')

    # Skip separator rows
    if any(c.startswith('-') and set(c) <= {'-', ':', ' '} for c in cells):
        return ('', '')

    name = ''
    role_hint = ''

    for i, cell in enumerate(cells):
        # Try bold name extraction
        m = re.search(r'\*\*([^*]+?)\*\*', cell)
        if m and not name:
            candidate = m.group(1).strip()
            if is_person_name(candidate):
                name = candidate
                continue

        # First cell as plain name
        if not name and i == 0:
            clean = re.sub(r'\*+', '', cell).strip()
            if is_person_name(clean):
                name = clean
                continue

        # Also check second cell as name (some tables have Role | Name)
        if not name and i == 1:
            clean = re.sub(r'\*+', '', cell).strip()
            if is_person_name(clean):
                name = clean
                continue

        # Collect role hints from remaining cells
        if name:
            role_hint += ' ' + cell

    return (name, role_hint.strip())


def extract_people_from_tree_line(line: str) -> list:
    """Extract people from a tree-format line (├── or └──)."""
    results = []

    # Match tree branch lines only
    m = re.match(r'^[\s│]*[├└]──\s+(.+)', line)
    if not m:
        return results

    content = m.group(1).strip()

    # A person entry must start with a capitalized English name or CJK name
    if not re.match(r'^[A-Z\u4e00-\u9fff]', content):
        return results

    # Skip lines that are clearly metadata/descriptions, not person entries
    skip_patterns = [
        r'^(PhD|PhD:|研究|Awards?|Lab:|合作:|现任|Postdocs?:|实习|暑研)',
        r'^(ICML|NeurIPS|ICLR|CVPR|ECCV|ICCV|ACL|EMNLP|NAACL)',
        r'^\d{4}\b',
        r'^http',
        r'^→\s',
        r'^[A-Z]{3,}:',  # Acronym labels like "CSAIL:", "BAIR:"
        r'^同门\s',  # Section labels
        r'^Postdocs:', r'^Students:', r'^PhD学生',
    ]
    for pat in skip_patterns:
        if re.match(pat, content, re.IGNORECASE):
            return results

    # Extract name + optional info in parens
    name, info = extract_name_and_inst(content)
    if name and is_person_name(name):
        results.append((name, info, content))

    return results


# ── Main lineage section finder ───────────────────────────────────

def find_lineage_section(text: str) -> str:
    """Find the lineage/mentorship section in a profile."""
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if not line.startswith('## '):
            continue
        if any(k in line for k in LINEAGE_KEYWORDS):
            start = i + 1
            end = len(lines)
            for j in range(start, len(lines)):
                if lines[j].startswith('## ') and not any(k in lines[j] for k in LINEAGE_KEYWORDS):
                    end = j
                    break
            return '\n'.join(lines[start:end])
    return ''


# ── Edge extraction from section ──────────────────────────────────

def extract_edges_from_section(section: str, profile_slug: str) -> list:
    """Extract edges from a lineage section, handling ALL format variants."""
    edges = []
    seen = set()

    lines = section.split('\n')
    current_subsection = ''
    current_rel_type = REL_UNKNOWN
    in_code_block = False
    tree_context_type = REL_UNKNOWN
    is_colon_header_section = False

    def add_edge(person_name, person_inst, rel_type, evidence=''):
        slug = slugify(person_name)
        if not slug or len(slug) < MIN_SLUG_LEN or slug == profile_slug:
            return
        if not is_person_name(person_name):
            return

        if rel_type in (REL_ADVISOR, REL_GRAND_ADVISOR):
            source, target = slug, profile_slug
            etype = REL_ADVISOR
        elif rel_type == REL_STUDENT:
            source, target = profile_slug, slug
            etype = REL_ADVISOR
        elif rel_type in BIDIRECTIONAL_TYPES:
            source, target = profile_slug, slug
            etype = rel_type
        else:
            source, target = profile_slug, slug
            etype = REL_COLLABORATOR

        keys = edge_keys(source, target, etype)
        if not keys & seen:
            seen.update(keys)
            edges.append({
                'source': source,
                'target': target,
                'type': etype,
                'evidence': (evidence or f'From {profile_slug} profile')[:EVIDENCE_TRUNCATE],
                'mention_name': person_name,
                'mention_inst': person_inst or '',
            })

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track code blocks
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            if in_code_block:
                tree_context_type = REL_UNKNOWN
            continue

        # Handle ### subsection headers (outside code blocks)
        if stripped.startswith('### ') and not in_code_block:
            current_subsection = stripped[4:].strip()
            current_rel_type = _classify_text(current_subsection)
            is_colon_header_section = False

            # Check for colon-in-header: ### 导师: Name
            colon_m = re.match(r'###\s+[^:：]+[:：]\s*(.+)', stripped)
            if colon_m:
                header_content = colon_m.group(1).strip()
                name, inst = extract_name_and_inst(header_content)
                if name and is_person_name(name):
                    add_edge(name, inst, current_rel_type,
                             f'{current_subsection}')
                    is_colon_header_section = True
                    # Bullets below this header describe this person, not new people
            continue

        # Inside code block — parse tree format
        if in_code_block:
            # Check if this is a "top-level label" line (not indented, no tree chars)
            # These are typically: "Name (inst)" or "Role label:"
            is_tree_branch = bool(re.search(r'[├└│]', stripped))
            is_indented = line.startswith('  ') or line.startswith('\t')

            if stripped and not is_tree_branch and not is_indented:
                # Top-level line in code block
                name, inst = extract_name_and_inst(stripped)
                ctx = _classify_text(stripped)

                if name and is_person_name(name):
                    if ctx != REL_UNKNOWN:
                        tree_context_type = ctx
                    else:
                        tree_context_type = REL_ADVISOR
                    add_edge(name, inst, tree_context_type, f'Tree root: {stripped[:80]}')
                elif ctx != REL_UNKNOWN:
                    # Label like "密切合作者:", "外部重要合作导师:"
                    tree_context_type = ctx
                continue

            # Only process actual tree branch lines (├── or └──)
            if is_tree_branch:
                # First check: is this a section label (not a person)?
                # e.g., "├── 同门 PhD:", "└── Postdocs:", "├── Lab: NeuroAI Lab"
                m_branch = re.match(r'^[\s│]*[├└]──\s+(.+)', stripped)
                if m_branch:
                    branch_content = m_branch.group(1).strip()
                    # Check if this is a label/description (ends with colon, or known metadata)
                    is_label = False
                    # Labels that end with ':'
                    if re.match(r'^(同门|Postdocs?|Students?|PhD|Lab|NeuroAI|合作者|'
                                r'密切合作|外部|内部|实习|暑研|CSAIL|EvLab|'
                                r'研究|Awards?|现任|Affiliated|核心|关键|'
                                r'MSR|Google|OpenAI|Waymo|'
                                r'PhD:|Postdoc:|博士|硕士|本科)', branch_content, re.IGNORECASE):
                        is_label = True
                    # Also treat lines starting with well-known metadata patterns as labels
                    if re.match(r'^(PhD|Postdoc|Awards|Lab|现任|研究|CSAIL|EvLab)[:：\s]',
                                branch_content, re.IGNORECASE):
                        is_label = True

                    if is_label:
                        # Update tree context type based on label
                        label_ctx = _classify_text(branch_content)
                        if label_ctx != REL_UNKNOWN:
                            tree_context_type = label_ctx
                        continue

                people = extract_people_from_tree_line(stripped)
                for name, inst, context in people:
                    line_ctx = _classify_text(context)
                    if line_ctx != REL_UNKNOWN:
                        edge_type = line_ctx
                    elif tree_context_type != REL_UNKNOWN:
                        edge_type = tree_context_type
                    elif current_rel_type != REL_UNKNOWN:
                        edge_type = current_rel_type
                    else:
                        edge_type = REL_COLLABORATOR

                    if '同门' in context:
                        edge_type = REL_SIBLING

                    add_edge(name, inst, edge_type, f'Tree: {context[:80]}')
            continue

        # Outside code block — regular content

        # Skip bullets if we're in a colon-header section (they describe the header person)
        if is_colon_header_section and re.match(r'^[-*•]\s+', stripped):
            # These bullets are descriptions of the person named in the ### header
            # Skip entirely — they are NOT new person entries
            continue

        # Table rows
        if stripped.startswith('|') and '---' not in stripped:
            name, role_hint = extract_person_from_table_row(stripped)
            if name and is_person_name(name):
                # Classify
                combined = current_subsection + ' ' + role_hint
                role_type = _classify_text(role_hint)
                if role_type != REL_UNKNOWN:
                    edge_type = role_type
                elif current_rel_type != REL_UNKNOWN:
                    edge_type = current_rel_type
                else:
                    ctx = _classify_text(combined)
                    edge_type = ctx if ctx != REL_UNKNOWN else 'collaborator'

                add_edge(name, '', edge_type,
                         f'{current_subsection}: {role_hint[:60]}')
            continue

        # Bullet lines (standard format)
        if re.match(r'[-*•]\s+', stripped):
            name, inst = extract_person_from_bullet(stripped)
            if name:
                if current_rel_type != REL_UNKNOWN:
                    edge_type = current_rel_type
                else:
                    ctx = _classify_text(stripped)
                    edge_type = ctx if ctx != REL_UNKNOWN else 'collaborator'
                add_edge(name, inst, edge_type,
                         f'{current_subsection or "lineage"}: {name}')
            continue

        # Paragraph-style: **Name** (info): description
        # e.g., "**Wojciech Matusik** (PhD 导师): 几乎所有..."
        m_para = re.match(r'\*\*([^*]+?)\*\*\s*(?:[（(]([^)）]*)[)）])?\s*[:：]', stripped)
        if m_para:
            name_raw = m_para.group(1).strip()
            info = (m_para.group(2) or '').strip()
            # Handle CJK-only names: swap with info if needed
            name = name_raw
            if not slugify(name) and info and slugify(info):
                name, info = info, name_raw
            if is_person_name(name):
                # Determine type from info and context
                combined = (info + ' ' + stripped[:100]).lower()
                ctx = _classify_text(combined)
                if ctx != REL_UNKNOWN:
                    edge_type = ctx
                elif current_rel_type != REL_UNKNOWN:
                    edge_type = current_rel_type
                else:
                    edge_type = REL_COLLABORATOR
                add_edge(name, info, edge_type,
                         f'{current_subsection or "lineage"}: {name}')
            continue

    return edges


# ── Profile extraction ────────────────────────────────────────────

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
        'mentions': [],
    }

    # Extract name from title
    for line in lines[:5]:
        if line.startswith('# '):
            title = line[2:].strip()
            m = re.match(r'^(.+?)\s*[（(](.+?)[)）]', title)
            if m:
                result['node']['name'] = m.group(1).strip()
                result['node']['chinese_name'] = m.group(2).strip()
            else:
                result['node']['name'] = title
            break

    # Extract institution
    in_anchor = False
    for line in lines:
        if '身份锚点' in line:
            in_anchor = True
            continue
        if in_anchor:
            if line.startswith('## ') and '身份锚点' not in line:
                break
            m = re.match(r'[-|]\s*现[任职][:|：]\s*\**(.+?)\**\s*$', line)
            if m:
                inst = m.group(1).strip()
                inst = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', inst)
                inst = re.sub(r'\*+', '', inst)
                result['node']['institution'] = inst[:INST_TRUNCATE]
                break
            m = re.match(r'\|\s*现职\s*\|\s*(.+?)\s*\|', line)
            if m:
                inst = m.group(1).strip()
                inst = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', inst)
                inst = re.sub(r'\*+', '', inst)
                result['node']['institution'] = inst[:INST_TRUNCATE]
                break

    # Find and parse lineage section
    section = find_lineage_section(text)
    if section:
        raw_edges = extract_edges_from_section(section, slug)
        for e in raw_edges:
            mention_name = e.pop('mention_name', '')
            mention_inst = e.pop('mention_inst', '')
            person_slug = e['target'] if e['source'] == slug else e['source']
            result['edges'].append(e)
            result['mentions'].append((person_slug, mention_name, mention_inst))

    return result


def extract_from_overviews() -> list:
    """Extract special edges from overview files."""
    edges = []
    if not OVERVIEW_DIR.exists():
        return edges
    for f in OVERVIEW_DIR.glob('*.md'):
        text = f.read_text(encoding='utf-8')
        for m in re.finditer(r'###?\s+(.+?)\s*[×x]\s*(.+?)\s+关系', text):
            slug_a = slugify(m.group(1).strip())
            slug_b = slugify(m.group(2).strip())
            if slug_a and slug_b:
                edges.append({
                    'source': slug_a, 'target': slug_b,
                    'type': 'couple',
                    'evidence': f'Relationship analysis in {f.stem}'
                })
    return edges


# ── Merge ─────────────────────────────────────────────────────────

def merge_graph(extractions: list, overview_edges: list, existing_graph=None) -> tuple:
    """Merge all extractions into graph, preserving existing data."""
    if existing_graph is not None:
        graph = existing_graph
    elif GRAPH_PATH.exists():
        with open(GRAPH_PATH, 'r', encoding='utf-8') as f:
            graph = json.load(f)
    else:
        graph = {'nodes': [], 'edges': []}

    node_map = {n['id']: n for n in graph['nodes']}
    edge_set = set()
    for e in graph['edges']:
        t = e.get('type', e.get('relation', ''))
        edge_set.update(edge_keys(e['source'], e['target'], t))

    stats = {'nodes_added': 0, 'nodes_updated': 0, 'edges_added': 0}

    for ext in extractions:
        node = ext['node']
        nid = node['id']

        if nid in node_map:
            existing = node_map[nid]
            updated = False
            for field in ('name', 'chinese_name', 'institution'):
                if node.get(field) and not existing.get(field):
                    existing[field] = node[field]
                    updated = True
            existing['has_profile'] = True
            if updated:
                stats['nodes_updated'] += 1
        else:
            node_map[nid] = node
            stats['nodes_added'] += 1

        for edge in ext['edges']:
            keys = edge_keys(edge['source'], edge['target'], edge['type'])
            if not keys & edge_set:
                graph['edges'].append(edge)
                edge_set.update(keys)
                stats['edges_added'] += 1

        for mention_slug, mention_name, mention_inst in ext['mentions']:
            if not mention_slug or len(mention_slug) < MIN_SLUG_LEN:
                continue
            if mention_slug not in node_map:
                node_map[mention_slug] = {
                    'id': mention_slug,
                    'name': mention_name,
                    'institution': mention_inst,
                    'has_profile': (PROFILE_DIR / f'{mention_slug}.md').exists(),
                    'mentioned_in': [nid],
                }
                stats['nodes_added'] += 1
            else:
                existing = node_map[mention_slug]
                if 'mentioned_in' not in existing:
                    existing['mentioned_in'] = []
                if nid not in existing['mentioned_in']:
                    existing['mentioned_in'].append(nid)

    for edge in overview_edges:
        keys = edge_keys(edge['source'], edge['target'], edge['type'])
        if not keys & edge_set:
            graph['edges'].append(edge)
            edge_set.update(keys)
            stats['edges_added'] += 1

    # Normalize: ensure all edges have 'type' (not 'relation')
    for e in graph['edges']:
        if 'relation' in e and 'type' not in e:
            e['type'] = e.pop('relation')
        elif 'relation' in e:
            del e['relation']

    # Update has_profile
    for nid, node in node_map.items():
        node['has_profile'] = (PROFILE_DIR / f'{nid}.md').exists()

    # Clean garbage nodes: unprofiled nodes whose name fails is_person_name
    # Use id as fallback for validation (blank names are not automatically garbage)
    garbage_ids = set()
    for nid, node in node_map.items():
        if node.get('has_profile'):
            continue
        name = node.get('name') or ''
        # Try name first; if blank or fails, try the slug id itself as a name
        if name and is_person_name(name):
            continue
        # Fallback: if id looks like a valid person slug (2-4 parts, no noise words)
        id_parts = nid.split('-')
        if 2 <= len(id_parts) <= MAX_SLUG_PARTS and not (set(id_parts) & NON_PERSON_WORDS):
            continue
        garbage_ids.add(nid)

    # Remove edges referencing garbage nodes
    graph['edges'] = [e for e in graph['edges']
                      if e['source'] not in garbage_ids and e['target'] not in garbage_ids]

    # Remove garbage from node_map
    for gid in garbage_ids:
        del node_map[gid]

    stats['garbage_removed'] = len(garbage_ids)

    # Remove orphans
    edge_nodes = set()
    for e in graph['edges']:
        edge_nodes.add(e['source'])
        edge_nodes.add(e['target'])

    final_nodes = []
    for nid, node in sorted(node_map.items()):
        if node.get('has_profile') or nid in edge_nodes or node.get('mentioned_in'):
            final_nodes.append(node)

    graph['nodes'] = sorted(final_nodes, key=lambda n: n['id'])
    graph['edges'] = sorted(graph['edges'], key=lambda e: (e['source'], e['target'], e.get('type', '')))

    return graph, stats


# ── Main ──────────────────────────────────────────────────────────

def main():
    profiles = [f for f in PROFILE_DIR.glob('*.md') if f.stem not in SKIP_SLUGS]
    print(f"Scanning {len(profiles)} profile files...")

    if GRAPH_PATH.exists():
        with open(GRAPH_PATH, 'r', encoding='utf-8') as f:
            old_graph = json.load(f)
        old_edge_set = set()
        old_edge_nodes = set()
        for e in old_graph['edges']:
            old_edge_nodes.add(e['source'])
            old_edge_nodes.add(e['target'])
            t = e.get('type', e.get('relation', ''))
            old_edge_set.add((e['source'], e['target'], t))
        old_profiled = {n['id'] for n in old_graph['nodes'] if n.get('has_profile')}
        old_zero = old_profiled - old_edge_nodes
        print(f"BEFORE: {len(old_profiled)} profiled, {len(old_zero)} zero-edge, "
              f"{len(old_graph['nodes'])} total nodes, {len(old_graph['edges'])} edges")
    else:
        old_graph = None
        old_edge_set = set()
        old_zero = set()

    extractions = []
    errors = []
    edge_counts = {}
    for p in sorted(profiles, key=lambda x: x.stem):
        try:
            ext = extract_from_profile(p)
            extractions.append(ext)
            edge_counts[p.stem] = len(ext['edges'])
        except Exception as e:
            errors.append(f"{p.stem}: {e}")

    if errors:
        print(f"\nExtraction errors ({len(errors)}):")
        for err in errors[:10]:
            print(f"  {err}")

    # Stats: total edges extracted
    total_extracted = sum(len(e['edges']) for e in extractions)
    print(f"\nTotal edges extracted from profiles: {total_extracted}")

    # Report for previously zero-edge profiles
    if old_zero:
        print(f"\n--- Previously zero-edge profiles ---")
        for slug in sorted(old_zero):
            count = edge_counts.get(slug, 0)
            marker = "OK" if count > 0 else "STILL ZERO"
            print(f"  {slug}: {count} edges [{marker}]")

    overview_edges = extract_from_overviews()
    print(f"\nFound {len(overview_edges)} special edges from overviews")

    graph, stats = merge_graph(extractions, overview_edges, existing_graph=old_graph)

    with open(GRAPH_PATH, 'w', encoding='utf-8') as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    # Post-scan
    new_edge_nodes = set()
    for e in graph['edges']:
        new_edge_nodes.add(e['source'])
        new_edge_nodes.add(e['target'])
    new_profiled = {n['id'] for n in graph['nodes'] if n.get('has_profile')}
    new_zero = new_profiled - new_edge_nodes

    print(f"\n=== Sync Complete ===")
    print(f"Nodes: {len(graph['nodes'])} ({len(new_profiled)} profiled)")
    print(f"Edges: {len(graph['edges'])}")
    print(f"Changes: +{stats['nodes_added']} nodes, ~{stats['nodes_updated']} updated, "
          f"+{stats['edges_added']} edges, -{stats.get('garbage_removed', 0)} garbage")
    print(f"\nAFTER: {len(new_profiled)} profiled, {len(new_zero)} zero-edge")

    if new_zero:
        print(f"\nRemaining zero-edge profiles ({len(new_zero)}):")
        for s in sorted(new_zero):
            print(f"  {s}")

    # Verify
    print("\n--- Verification ---")
    for check in ['cheng-lu', 'chenxi-liu', 'chengxu-zhuang', 'chunyuan-li']:
        slug_edges = [e for e in graph['edges']
                      if e['source'] == check or e['target'] == check]
        print(f"  {check}: {len(slug_edges)} edges")
        for e in slug_edges[:5]:
            print(f"    {e['type']}: {e['source']} -> {e['target']}")

    # Spot-check: show a few newly added edges for quality
    print("\n--- Sample new edges (first 20) ---")
    count = 0
    for e in graph['edges']:
        if count >= 20:
            break
        key = (e['source'], e['target'], e.get('type', ''))
        if key not in old_edge_set:
            print(f"  {e['type']:12s} {e['source']:30s} -> {e['target']:30s} | {e.get('evidence','')[:60]}")
            count += 1


if __name__ == '__main__':
    main()
