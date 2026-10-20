"""
Parses the free-text prerequisite strings in the UF course catalog into structured data.

    "Prereq: MAC 2312 and (MAC 2512 or MAC 3473) with a minimum grade of C. Coreq: MAS 3114"

becomes

    {
      "prereq":  [["MAC2312"], ["MAC2512", "MAC3473"]],   # AND of OR groups
      "coreq":   [["MAS3114"]],
      "minGrade": "C",
      ...
    }

Course requirements are stored as an AND of OR groups: every inner list is a group of which
at least one course must be satisfied (same shape the planner uses). Anything that is not a
course (majors, class standing, instructor permission, credit counts) is kept as plain text in
`requirements`, and a group that can also be satisfied by one of those lands in `softPrereq`.
"""

import re
from itertools import product

CODE_RE = re.compile(r'\b[A-Z]{3}\s?\d{4}[A-Z]?\b')
MAX_CLAUSES = 48

SEGMENT_RE = re.compile(
    r'(prereq(?:uisites?)?\s*(?:or|/)\s*coreq(?:uisites?)?|prereq(?:uisites?)?|coreq(?:uisites?)?)\s*[:;]',
    re.I,
)
GRADE_RE = re.compile(
    r'(?:,?\s*(?:all\s+(?:courses\s+)?)?with\s+)?(?:an?\s+)?(?:minimum|min\.?)\s+grades?\s+of\s+'
    r'([A-E][+-]?)(?:\s+(?:or\s+higher|in\s+(?:each|all|every)(?:\s+courses?)?|in))?',
    re.I,
)
CREDITS_RE = re.compile(
    r'(?:\bat\s+least\s+|\bminimum\s+)?\b\d+\s+(?:semester\s+)?credits?\b(?:(?!\sand\s)[^;.,])*', re.I
)
CREDITS_PREFIX_RE = re.compile(
    r'(?:\bat\s+least\s+)?\b(\d+)\s+(?:semester\s+)?credits?\s+(?:minimum\s+)?(?:from|of|in)\s+', re.I
)
EQUIVALENT_RE = re.compile(r',?\s*\bor\s+(?:the\s+|an\s+)?equivalents?\b(?:\s+(?:courses?|credits?))?', re.I)
RECOMMENDED_RE = re.compile(r'(' + CODE_RE.pattern + r')\s+recommended', re.I)
STANDING_PHRASE_RE = re.compile(
    r'\b(?:freshman|sophomore|junior|senior|graduate)\s+standing(?:\s+or\s+(?:higher|above|better))?', re.I
)
HIGHER_RE = re.compile(r'\s+or\s+(?:higher|greater|above)\b', re.I)
STANDING_RE = re.compile(r'\b(freshman|sophomore|junior|senior|graduate)\s+standing', re.I)

TOKEN_RE = re.compile(
    r'(?P<code>\b[A-Z]{3}\s?\d{4}[A-Z]?\b)'
    r'|(?P<and>(?i:\band\b)|&)'
    r'|(?P<or>(?i:\bor\b))'
    r'|(?P<comma>,)'
    r'|(?P<semi>;)'
    r'|(?P<lp>\()'
    r'|(?P<rp>\))'
)


def normalize_code(code):
    return re.sub(r'\s+', '', code)


# ---------------------------------------------------------------------------
# Tokenizing
# ---------------------------------------------------------------------------

def tokenize(text):
    tokens = []
    pos = 0

    def push_text(chunk):
        chunk = chunk.strip(' \t\n.;:-')
        if chunk:
            tokens.append(('text', chunk))

    for m in TOKEN_RE.finditer(text):
        push_text(text[pos:m.start()])
        kind = m.lastgroup
        tokens.append((kind, normalize_code(m.group()) if kind == 'code' else m.group()))
        pos = m.end()
    push_text(text[pos:])
    return tokens


def resolve_commas(tokens):
    """A comma is OR when its list ends in ", or X" (or "or X" after a comma); otherwise AND."""
    out = list(tokens)
    # Work level by level: find paren-matched ranges, innermost first.
    def resolve_range(lo, hi):
        depth = 0
        i = lo
        level_idx = []
        while i < hi:
            kind = out[i][0]
            if kind == 'lp':
                j, d = i, 0
                while j < hi:
                    if out[j][0] == 'lp':
                        d += 1
                    elif out[j][0] == 'rp':
                        d -= 1
                        if d == 0:
                            break
                    j += 1
                resolve_range(i + 1, j)
                i = j + 1
                continue
            level_idx.append(i)
            i += 1
        has_comma_or = any(
            out[k][0] == 'comma' and k + 1 < hi and out[k + 1][0] == 'or' for k in level_idx
        )
        for k in level_idx:
            if out[k][0] == 'comma':
                nxt = out[k + 1][0] if k + 1 < hi else None
                if nxt in ('or', 'and'):
                    out[k] = ('skip', '')      # ", or" / ", and": the keyword carries the meaning
                else:
                    out[k] = ('or' if has_comma_or else 'and', ',')

    resolve_range(0, len(out))
    return [t for t in out if t[0] != 'skip']


# ---------------------------------------------------------------------------
# Parsing into an AST: ('and', [..]) | ('or', [..]) | ('course', code) | ('text', str)
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0
        self.ambiguous = False

    def peek(self):
        return self.t[self.i][0] if self.i < len(self.t) else None

    def parse_or(self):
        parts = [self.parse_and()]
        while self.peek() == 'or':
            self.i += 1
            parts.append(self.parse_and())
        parts = [p for p in parts if p != ('and', [])]
        if not parts:
            return ('and', [])
        return parts[0] if len(parts) == 1 else ('or', parts)

    def parse_and(self):
        parts = []
        first = True
        while True:
            kind = self.peek()
            if kind == 'and' and not first:
                self.i += 1
            elif kind in ('code', 'text', 'lp') and not first:
                pass  # two operands in a row: implicit AND
            elif not first:
                break
            first = False
            node = self.parse_primary()
            if node is not None:
                parts.append(node)
            if self.peek() is None or self.peek() in ('or', 'rp'):
                break
        if not parts:
            return ('and', [])
        return parts[0] if len(parts) == 1 else ('and', parts)

    def parse_primary(self):
        kind = self.peek()
        if kind == 'lp':
            self.i += 1
            node = self.parse_or()
            if self.peek() == 'rp':
                self.i += 1
            return node
        if kind in ('code', 'text'):
            value = self.t[self.i][1]
            self.i += 1
            return ('course' if kind == 'code' else 'text', value)
        self.i += 1  # stray operator: skip it
        return None


def _mixes_and_or(tokens):
    """True when a paren level contains both and/or with no grouping, which is ambiguous prose."""
    depth_kinds = [set()]
    for kind, _ in tokens:
        if kind == 'lp':
            depth_kinds.append(set())
        elif kind == 'rp':
            if len(depth_kinds) > 1:
                s = depth_kinds.pop()
                if {'and', 'or'} <= s:
                    return True
        elif kind in ('and', 'or'):
            depth_kinds[-1].add(kind)
    return any({'and', 'or'} <= s for s in depth_kinds)


# ---------------------------------------------------------------------------
# AST -> clauses (CNF). An element is a course code or a ('?', text) non-course alternative.
# ---------------------------------------------------------------------------

def to_cnf(node):
    kind = node[0]
    if kind == 'course':
        return [[node[1]]]
    if kind == 'text':
        return [[('?', node[1])]]
    children = [to_cnf(c) for c in node[1]]
    if kind == 'and':
        return [clause for child in children for clause in child]
    # or: distribute
    clauses = [[]]
    for child in children:
        if len(clauses) * len(child) > MAX_CLAUSES:
            raise OverflowError
        clauses = [a + b for a, b in product(clauses, child)]
    return clauses


def minimize(clauses):
    """Drop duplicate clauses and any clause that is implied by a smaller one."""
    sets = []
    for clause in clauses:
        cs = frozenset(clause)
        if cs not in sets:
            sets.append(cs)
    kept = [c for c in sets if not any(o < c for o in sets)]
    order = {}
    for clause in clauses:
        for e in clause:
            order.setdefault(e, len(order))
    return [sorted(c, key=lambda e: order[e]) for c in kept]


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# ---------------------------------------------------------------------------
# Segment parsing
# ---------------------------------------------------------------------------

def _clean_segment(text):
    notes = []
    grade = None

    m = GRADE_RE.search(text)
    if m:
        grade = m.group(1).upper()
    text = GRADE_RE.sub(' ', text)

    if EQUIVALENT_RE.search(text):
        notes.append('equivalent courses are accepted')
        text = EQUIVALENT_RE.sub(' ', text)

    for m in RECOMMENDED_RE.finditer(text):
        notes.append(f'{normalize_code(m.group(1))} recommended')
    text = RECOMMENDED_RE.sub(' ', text)

    credit_phrases = []

    def stash_standing(m):
        credit_phrases.append(m.group().strip(' .;,'))
        return f' ⟦{len(credit_phrases) - 1}⟧ '

    text = STANDING_PHRASE_RE.sub(stash_standing, text)
    text = HIGHER_RE.sub(' ', text)

    def stash_credits(m):
        phrase = m.group()
        if CODE_RE.search(phrase):
            # "6 credits from AAA 1000 or BBB 2000": keep the courses, note the credit count
            prefix = CREDITS_PREFIX_RE.search(phrase)
            if prefix:
                notes.append(f'{prefix.group(1)} credits needed from the courses listed')
                return CREDITS_PREFIX_RE.sub(' ', phrase, count=1)
        credit_phrases.append(phrase.strip(' .;,'))
        return f' ⟦{len(credit_phrases) - 1}⟧ '

    text = CREDITS_RE.sub(stash_credits, text)

    # Parentheses that only hold a remark (no course, no and/or) are plain text, not groups.
    def flatten_remark(m):
        inner = m.group(1)
        if CODE_RE.search(inner) or re.search(r'\b(and|or)\b|[&,]', inner, re.I):
            return m.group()
        return f' {inner} '

    text = re.sub(r'\(([^()]*)\)', flatten_remark, text)
    text = re.sub(r'\(\s*\)', ' ', text)
    return text, grade, notes, credit_phrases


def _split_top_level_and(text):
    out, depth, i = [], 0, 0
    while i < len(text):
        ch = text[i]
        depth += (ch == '(') - (ch == ')')
        m = re.match(r',\s*(?:and|&)\s+', text[i:], re.I) if ch == ',' and depth <= 0 else None
        if m:
            out.append('; ')
            i += m.end()
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def parse_segment(text):
    """Return (clauses, requirements, minGrade, notes, flags) for one Prereq/Coreq segment."""
    text, grade, notes, credit_phrases = _clean_segment(text)

    text = _split_top_level_and(text)

    # ';' separates clauses that are ANDed together, so each is parsed on its own
    raw_tokens = tokenize(text)
    groups, current = [], []
    for tok in raw_tokens:
        if tok[0] == 'semi':
            groups.append(current)
            current = []
        else:
            current.append(tok)
    groups.append(current)

    tokens = []
    asts = []
    flags = {'ambiguous': False, 'complex': False}
    for group in groups:
        group = resolve_commas(group)
        if not group:
            continue
        flags['ambiguous'] |= _mixes_and_or(group)
        # restore stashed credit phrases
        group = [
            (k, re.sub(r'⟦(\d+)⟧', lambda m: credit_phrases[int(m.group(1))], v) if k == 'text' else v)
            for k, v in group
        ]
        tokens.extend(group)
        asts.append(_Parser(group).parse_or())

    if not asts:
        return [], [], grade, notes, flags

    ast = asts[0] if len(asts) == 1 else ('and', asts)
    try:
        clauses = minimize(to_cnf(ast))
    except OverflowError:
        flags['complex'] = True
        flat = _dedupe(t[1] for t in tokens if t[0] == 'code')
        return [([c], []) for c in flat], [], grade, notes, flags

    hard, requirements = [], []
    for clause in clauses:
        courses = _dedupe(e for e in clause if isinstance(e, str))
        others = _dedupe(e[1] for e in clause if isinstance(e, tuple))
        if courses and others:
            hard.append((courses, others))      # satisfiable by a non-course alternative
        elif courses:
            hard.append((courses, []))
        else:
            requirements.extend(others)
    return hard, requirements, grade, notes, flags


def parse_prerequisites(text):
    """Parse a catalog prerequisite string. Always returns a dict; never raises."""
    result = {
        'prereq': [],
        'softPrereq': [],
        'coreq': [],
        'concurrent': [],
        'minGrade': None,
        'standing': None,
        'requirements': [],
        'notes': [],
        'ambiguous': False,
        'complex': False,
    }
    if not text or not text.strip():
        return result

    text = text.replace('\xa0', ' ')
    text = re.sub(r'(\b[A-Z]{3}\s?\d{4}[A-Z]?)(?=[a-z])', r'\1 ', text)
    text = re.sub(r'\s+', ' ', text)

    parts = SEGMENT_RE.split(text)
    segments = []
    lead = re.sub(r'^\s*credits?\s*:\s*[\d.\-\s]+;?', '', parts[0], flags=re.I)
    if lead.strip(' .;'):
        segments.append(('prereq', lead))  # text with no label counts as a prerequisite
    for i in range(1, len(parts), 2):
        label = parts[i].lower()
        if 'coreq' in label and 'prereq' in label:
            kind = 'concurrent'
        elif 'coreq' in label:
            kind = 'coreq'
        else:
            kind = 'prereq'
        segments.append((kind, parts[i + 1] if i + 1 < len(parts) else ''))

    for kind, body in segments:
        # Trailing "or coreq:" style leftovers or empty bodies produce nothing.
        body = re.sub(r'^\s*(?:or\s+coreq(?:uisites?)?\s*[:;]?)', '', body, flags=re.I)
        if re.fullmatch(r'\s*(none)?\s*\.?\s*', body, flags=re.I):
            continue
        clauses, requirements, grade, notes, flags = parse_segment(body)
        result['minGrade'] = result['minGrade'] or grade
        result['ambiguous'] |= flags['ambiguous']
        result['complex'] |= flags['complex']
        result['notes'].extend(notes)
        result['requirements'].extend(requirements)
        for courses, others in clauses:
            if others:
                result['softPrereq'].append(courses)
                result['notes'].append(f"{' / '.join(courses)} can be replaced by: {'; '.join(others)}")
            else:
                result[kind].append(courses)

    result['requirements'] = _dedupe(result['requirements'])
    for req in result['requirements']:
        m = STANDING_RE.search(req)
        if m:
            result['standing'] = m.group(1).lower()
    return result


def parse_course(course):
    """Parse a course record from the catalog JSON, dropping self references."""
    parsed = parse_prerequisites(course.get('prerequisites', ''))
    own = normalize_code(course.get('code', ''))
    for key in ('prereq', 'softPrereq', 'coreq', 'concurrent'):
        parsed[key] = [g for g in ([c for c in group if c != own] for group in parsed[key]) if g]
    return parsed
