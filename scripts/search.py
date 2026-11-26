"""Search the index from the command line.

Usage:
  python scripts/search.py index/search.db "asthma rates by county in Ohio"
  python scripts/search.py index/search.db "evictions in chicago since 2020" --n 5 --json
  python scripts/search.py index/search.db "..." --mode keyword|vector|hybrid   (default hybrid)

How ranking works:
  1. Parse the question with rules: state, years, geography level, map intent.
  2. Candidates: keyword search (SQLite FTS5 / BM25) and meaning search (bge-small embeddings), 300 each.
  3. Merge the two lists with Reciprocal Rank Fusion: score = sum of 1 / (60 + rank).
  4. Hard filters: drop results for a different state, or whose data ends before the requested years.
  5. Adjust: boosts for matching state, geography level and real data access; penalties for
     documents-only, stale and unknown-access records.
"""
import argparse, json, math, os, re, sqlite3, sys
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

STATES = {'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA','colorado':'CO','connecticut':'CT','delaware':'DE',
 'district of columbia':'DC','florida':'FL','georgia':'GA','hawaii':'HI','idaho':'ID','illinois':'IL','indiana':'IN','iowa':'IA','kansas':'KS',
 'kentucky':'KY','louisiana':'LA','maine':'ME','maryland':'MD','massachusetts':'MA','michigan':'MI','minnesota':'MN','mississippi':'MS',
 'missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV','new hampshire':'NH','new jersey':'NJ','new mexico':'NM','new york state':'NY',
 'north carolina':'NC','north dakota':'ND','ohio':'OH','oklahoma':'OK','oregon':'OR','pennsylvania':'PA','rhode island':'RI',
 'south carolina':'SC','south dakota':'SD','tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT','virginia':'VA','washington state':'WA',
 'west virginia':'WV','wisconsin':'WI','wyoming':'WY','puerto rico':'PR'}
CITIES = {'new york city':'NY','nyc':'NY','new york':'NY','chicago':'IL','los angeles':'CA','san francisco':'CA','seattle':'WA','austin':'TX',
 'houston':'TX','dallas':'TX','philadelphia':'PA','pittsburgh':'PA','baltimore':'MD','boston':'MA','denver':'CO','detroit':'MI','flint':'MI',
 'columbus':'OH','cleveland':'OH','atlanta':'GA','miami':'FL','phoenix':'AZ','new orleans':'LA','washington dc':'DC','dc':'DC'}
NAME_OF = {v: k.title() for k, v in STATES.items()}
GEO_WORDS = [('tract', r'\btracts?\b|\bneighborhoods?\b'), ('block group', r'\bblock groups?\b'), ('zip code', r'\bzip( ?codes?)?\b'),
             ('county', r'\bcount(y|ies)\b'), ('city', r'\bcit(y|ies)\b|\bmunicipal'), ('school district', r'\bschool districts?\b'),
             ('state', r'\bby state\b|\beach state\b|\bstates\b'), ('address / point', r'\blocations?\b|\baddresses\b|\bnear\b')]
STOP = set('a an the in of by for to and or on at with from is are was what which where who how many much do does did my our me i '
           'data dataset datasets find show get about any there since after before between per rates rate level each'.split())
# Value matching: how much a match on a value inside the data counts, and how close it must be (cosine distance)
VAL_WEIGHT = 0.3
VAL_MAX_DIST = 0.22
VAL_GATE = True  # a value must also share a topic word with the question
# Reranker: a small cross-encoder rereads the top candidates together with the question and reorders them
RERANK_MODEL = None          # e.g. 'Xenova/ms-marco-MiniLM-L-6-v2' (small) or 'BAAI/bge-reranker-base' (bigger); None = off
RERANK_TOP = 30
RERANK_MIX = 0.7             # share of the final score that comes from the reranker
_rerankers = {}

def _reranker(name):
    if name not in _rerankers:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _rerankers[name] = TextCrossEncoder(name)
    return _rerankers[name]


def _rerank_text(r):
    parts = [r['display_title'], (r.get('description') or '')[:400]]
    if r.get('contains'):
        parts.append('Contains: ' + '; '.join(r['contains'][:15]))
    cols = ', '.join((c.get('name') or c.get('field') or '') for c in (r.get('columns') or [])[:15])
    if cols:
        parts.append('Columns: ' + cols)
    return '. '.join(p for p in parts if p)[:1200]


QUERY_PREFIX = 'Represent this sentence for searching relevant passages: '  # bge retrieval prefix


def parse(q):
    l = ' ' + q.lower() + ' '
    p = {'state': None, 'place': None, 'years': None, 'geo': None, 'map': bool(re.search(r'\bmaps?\b|boundar|shapefile|gis\b', l))}
    for c, st in sorted(CITIES.items(), key=lambda x: -len(x[0])):
        if re.search(r'\b' + re.escape(c) + r'\b', l):
            p['state'], p['place'] = st, c.title(); break
    if not p['state']:
        for n, st in sorted(STATES.items(), key=lambda x: -len(x[0])):
            base = n.replace(' state', '')
            if re.search(r'\b' + re.escape(base) + r'\b', l):
                p['state'], p['place'] = st, base.title(); break
    if not p['state']:
        m = re.search(r'\b([A-Z]{2})\b', q)
        if m and m.group(1) in NAME_OF:
            p['state'], p['place'] = m.group(1), NAME_OF[m.group(1)]
    m = re.search(r'\b(since|after|from)\s+((?:19|20)\d\d)\b', l)
    r = re.search(r'\b((?:19|20)\d\d)\s*(?:-|to|through)\s*((?:19|20)\d\d)\b', l)
    one = re.search(r'\b((?:19|20)\d\d)\b', l)
    if r: p['years'] = (int(r.group(1)), int(r.group(2)))
    elif m: p['years'] = (int(m.group(2)), 2026)
    elif one: p['years'] = (int(one.group(1)), int(one.group(1)))
    for lvl, rx in GEO_WORDS:
        if re.search(rx, l):
            p['geo'] = lvl; break
    return p


def fts_query(q, p):
    words = re.findall(r"[a-z0-9]+", q.lower())
    drop = set((p['place'] or '').lower().split())
    toks = [w for w in words if w not in STOP and w not in drop and not re.fullmatch(r'(19|20)\d\d', w) and len(w) > 1]
    return ' OR '.join('"%s"' % w for w in toks), toks


def open_db(path):
    db = sqlite3.connect(path, check_same_thread=False)  # MCP server calls tools from worker threads
    try:
        import sqlite_vec
        db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    except Exception:
        pass
    return db


def search(db, q, n=10, mode='hybrid', model=None, overrides=None):
    p = parse(q)
    for k, v in (overrides or {}).items():
        if v is not None:
            p[k] = v
    if (overrides or {}).get('state') and not (overrides or {}).get('place'):
        p['place'] = NAME_OF.get(p['state'], p['state'])
    fq, toks = fts_query(q, p)
    ranks = {}  # rowid -> {'kw': rank, 'vec': rank}
    if mode in ('hybrid', 'keyword') and fq:
        if p['state']:
            # filter inside SQL so state-specific matches are not crowded out by other states
            rows = db.execute("""SELECT fts.rowid FROM fts JOIN records r ON r.rowid = fts.rowid
                                 WHERE fts MATCH ? AND (',' || r.states || ',' LIKE ? OR r.states = 'US')
                                 ORDER BY bm25(fts, 4.0, 1.0, 0.6) LIMIT 300""", (fq, '%,' + p['state'] + ',%')).fetchall()
        else:
            rows = db.execute('SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY bm25(fts, 4.0, 1.0, 0.6) LIMIT 300', (fq,)).fetchall()
        for i, (rid,) in enumerate(rows):
            ranks.setdefault(rid, {})['kw'] = i + 1
        if len(toks) > 1:
            # results containing ALL topic words get an extra vote, so 'asthma prevalence' beats 'autism prevalence'
            aq = ' AND '.join('"%s"' % w for w in toks)
            arows = db.execute('SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY bm25(fts, 4.0, 1.0, 0.6) LIMIT 100', (aq,)).fetchall()
            for i, (rid,) in enumerate(arows):
                ranks.setdefault(rid, {})['all'] = i + 1
    has_vec = db.execute('SELECT count(*) FROM vec').fetchone()[0] > 0 if mode != 'keyword' else False
    if mode in ('hybrid', 'vector') and has_vec:
        if model is None:
            from fastembed import TextEmbedding
            model = TextEmbedding(db.execute("SELECT v FROM meta WHERE k='model'").fetchone()[0])
        import sqlite_vec
        qv = list(model.embed([QUERY_PREFIX + q]))[0]
        k = 2000 if p['state'] else 300  # over-fetch when a state filter will discard many
        rows = db.execute('SELECT rowid, distance FROM vec WHERE embedding MATCH ? AND k = ?',
                          (sqlite_vec.serialize_float32([float(x) for x in qv]), k)).fetchall()
        if p['state']:
            ok = set()
            ids_ = [r_[0] for r_ in rows]
            for c in range(0, len(ids_), 500):
                part = ids_[c:c + 500]
                ok |= {x[0] for x in db.execute("SELECT rowid FROM records WHERE rowid IN (%s) AND (',' || states || ',' LIKE ? OR states = 'US')"
                                                 % ','.join('?' * len(part)), part + ['%,' + p['state'] + ',%'])}
            rows = [r_ for r_ in rows if r_[0] in ok][:300]
        for i, (rid, dist) in enumerate(rows):
            ranks.setdefault(rid, {})['vec'] = i + 1
        # values inside datasets (e.g. 'Current asthma among adults') matched directly against the question
        if VAL_WEIGHT > 0 and db.execute("SELECT count(*) FROM sqlite_master WHERE name='vec_vals'").fetchone()[0]:
            vrows = db.execute('SELECT v.rowid, v.distance, x.text, x.rowids FROM vec_vals v JOIN vals x ON x.vid = v.rowid '
                               'WHERE v.embedding MATCH ? AND k = 60', (sqlite_vec.serialize_float32([float(x) for x in qv]),)).fetchall()
            seen = 0
            stems = {w[:5] for w in toks if len(w) >= 4}
            for vid, dist, text, rids in vrows:
                if dist > VAL_MAX_DIST:  # only close matches count
                    continue
                if VAL_GATE and not stems & {w[:5] for w in re.findall(r'[a-z]+', text.lower()) if len(w) >= 4}:
                    continue  # semantically close but shares no topic word: usually noise
                for rid in json.loads(rids):
                    if 'val' not in ranks.get(rid, {}):
                        seen += 1
                        ranks.setdefault(rid, {})['val'] = seen
                        ranks[rid]['val_text'] = text
    if not ranks:
        return p, [], 0
    ids = list(ranks)
    recs = {}
    for chunk in range(0, len(ids), 500):
        part = ids[chunk:chunk + 500]
        for row in db.execute('SELECT rowid, doc FROM records WHERE rowid IN (%s)' % ','.join('?' * len(part)), part):
            recs[row[0]] = json.loads(row[1])
    out, hidden = [], 0
    for rid, rk in ranks.items():
        r = recs[rid]
        score = sum((VAL_WEIGHT if k == 'val' else 1.0) / (60 + v) for k, v in rk.items() if k != 'val_text')
        why = []
        if 'all' in rk: why.append('contains all your key words')
        if 'val' in rk: why.append('has data on "%s"' % rk['val_text'][:80])
        if 'kw' in rk and 'vec' in rk: why.append('matches your words and meaning')
        elif 'kw' in rk or 'all' in rk: why.append('matches your words')
        elif 'vec' in rk: why.append('similar in meaning')
        st = r.get('states') or []
        if p['state']:
            if st and p['state'] not in st and 'US' not in st:
                hidden += 1; continue
            if p['state'] in st:
                score *= 1.5; why.append('specific to ' + (p['place'] or p['state']))
            elif 'US' in st:
                why.append('covers all states')
        cy = r.get('coverage_years') or [None, None]
        if p['years'] and cy[1] and cy[1] < p['years'][0]:
            hidden += 1; continue
        if p['years'] and cy[0]:
            score *= 1.1; why.append('covers %s-%s' % (cy[0], cy[1]))
        if p['geo']:
            if p['geo'] in (r.get('geo_levels') or []):
                score *= 1.4; why.append('has %s-level data' % p['geo'])
        acc = r.get('access') or []
        if 'documents_only' in acc: score *= 0.55
        elif 'unknown' in acc: score *= 0.75
        if r.get('freshness') == 'stale': score *= 0.85
        if r.get('research_like'): score *= 0.6
        kind = (r.get('census') or {}).get('kind')
        if kind == 'imputation': score *= 0.4
        elif kind == 'race_iteration': score *= 0.8
        if r.get('columns'): score *= 1.1
        if r.get('map_type') and not p['map']: score *= 0.85
        if p['map'] and r.get('map_type'): score *= 1.3; why.append('map data')
        if r.get('supporting_file'): score *= 0.5
        score *= 1 + 0.07 * math.log1p(r.get('popularity') or 0)  # well-used datasets rank higher
        out.append((score, r, why, rk))
    out.sort(key=lambda x: -x[0])
    if RERANK_MODEL and len(out) > 1:
        head, tail = out[:RERANK_TOP], out[RERANK_TOP:]
        ce = list(_reranker(RERANK_MODEL).rerank(q, [_rerank_text(r) for _, r, _, _ in head]))
        lo, hi = min(ce), max(ce)
        top_s = head[0][0] or 1.0
        mixed = []
        for (sc, r, w, rk), c in zip(head, ce):
            cn = (c - lo) / (hi - lo) if hi > lo else 0.5
            mixed.append((RERANK_MIX * cn + (1 - RERANK_MIX) * (sc / top_s), r, w, rk))
        mixed.sort(key=lambda x: -x[0])
        out = mixed + tail
    return p, [dict(score=round(s, 5), why=w, ranks={k: v for k, v in rk.items() if k != 'val_text'}, record=r) for s, r, w, rk in out[:n]], hidden


def url_of(r):
    u = r.get('landing_url')
    if isinstance(u, dict):
        u = u.get('@id') or u.get('url')
    return u or ''


def fmt_years(y):
    if not y or not y[0]: return 'years unknown'
    return str(y[0]) if y[0] == y[1] else '%s-%s' % (y[0], y[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db'); ap.add_argument('query')
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--mode', default='hybrid', choices=['hybrid', 'keyword', 'vector'])
    ap.add_argument('--json', action='store_true', help='machine-readable output (for agents)')
    ap.add_argument('--rerank', nargs='?', const='Xenova/ms-marco-MiniLM-L-6-v2', default=None, help='rerank the top 30 (optionally name a model)')
    a = ap.parse_args()
    db = open_db(a.db)
    global RERANK_MODEL
    RERANK_MODEL = a.rerank
    res = search(db, a.query, a.n, a.mode)
    p, hits = res[0], res[1]
    hidden = res[2] if len(res) > 2 else 0
    if a.json:
        slim = []
        for h in hits:
            r = h['record']
            slim.append({k: r.get(k) for k in ('id', 'display_title', 'publisher', 'states', 'geo_levels', 'coverage_years',
                                                'freshness', 'access', 'formats', 'map_type', 'series_count', 'derived')}
                        | {'url': url_of(r)}
                        | {'why': h['why'], 'columns': [c.get('name') for c in (r.get('columns') or [])[:15]] or None})
        print(json.dumps({'query': a.query, 'understood': p, 'hidden_by_filters': hidden, 'results': slim}, indent=1))
        return
    u = [x for x in ['place: ' + p['place'] if p['place'] else '', 'years: %s-%s' % p['years'] if p['years'] else '',
                     'level: ' + p['geo'] if p['geo'] else '', 'wants map data' if p['map'] else ''] if x]
    print('\nUnderstood:', ', '.join(u) or 'topic only', '| mode:', a.mode, '| hidden by filters:', hidden, '\n')
    for i, h in enumerate(hits, 1):
        r = h['record']
        print('%2d. %s' % (i, r['display_title'][:110]))
        print('    %s | %s | %s | %s | %s' % ((r.get('publisher') or '')[:45], ','.join(r.get('states') or []) or '?',
              fmt_years(r.get('coverage_years')), r.get('freshness'), ','.join(r.get('access') or [])))
        extra = []
        if r.get('series_count', 1) > 1: extra.append('%d files grouped' % r['series_count'])
        if r.get('columns'): extra.append('%d columns' % len(r['columns']))
        if r.get('geo_levels'): extra.append('levels: ' + ', '.join(r['geo_levels'][:4]))
        print('    why: %s%s' % ('; '.join(h['why']), ('  [' + '; '.join(extra) + ']') if extra else ''))
        print('    %s' % url_of(r))
    if not hits:
        print('No results.')


if __name__ == '__main__':
    main()
