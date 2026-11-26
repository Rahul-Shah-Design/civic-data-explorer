"""Merge data.gov groups, Census tables and Socrata datasets into one record per search result.

Usage: python3 -I scripts/merge.py <repo_root>
Reads clean/datagov_grouped.jsonl, raw/census_catalog.json, raw/census_groups/, raw/socrata.jsonl
Writes index/records.jsonl
"""
import json, os, re, sys, glob, hashlib, collections as C

root = sys.argv[1]
P = lambda *a: os.path.join(root, *a)
os.makedirs(P('index'), exist_ok=True)
EXCL = {'imagery', 'science', 'document'}
FOURBYFOUR = re.compile(r'\b([a-z0-9]{4}-[a-z0-9]{4})\b')

# ---------- Socrata: load, keyed by 4x4 ----------
soc = {}
for line in open(P('raw', 'socrata.jsonl')):
    x = json.loads(line)
    soc[x['resource']['id']] = x

def soc_columns(x):
    r = x['resource']
    names, fields = r.get('columns_name') or [], r.get('columns_field_name') or []
    descs, types = r.get('columns_description') or [], r.get('columns_datatype') or []
    out = []
    for i, f in enumerate(fields):
        out.append({'field': f, 'name': names[i] if i < len(names) else f,
                    'description': (descs[i] if i < len(descs) else '') or None,
                    'type': types[i] if i < len(types) else None, 'label_source': 'official'})
    return out

# ---------- data.gov: aggregate groups ----------
def year_of(s):
    m = re.match(r'(\d{4})', str(s or ''))
    y = int(m.group(1)) if m else None
    return y if y and 1900 <= y <= 2026 else None

def temporal_years(t):
    ys = [int(y) for y in re.findall(r'\b(1[89]\d\d|20\d\d)\b', str(t or '')) if 1800 <= int(y) <= 2030]
    return (min(ys), max(ys)) if ys else (None, None)

groups = {}
for line in open(P('clean', 'datagov_grouped.jsonl')):
    x = json.loads(line)
    if EXCL & set(x['flags']):
        continue
    k = x['group_key']
    g = groups.get(k)
    my = x.get('modified_year')
    if g is None:
        g = groups[k] = {'n': 0, 'rep': None, 'rep_score': None, 'formats': set(), 'years': [None, None],
                         'mod_latest': None, 'members': [], 'socrata_ids': set(), 'pop': 0, 'flags': C.Counter()}
    g['n'] += 1
    if len(g['members']) < 5:
        g['members'].append({'id': x['id'], 'title': x['title'], 'landing': x.get('landing')})
    for d in x['distribution']:
        f = (d.get('format') or d.get('mediaType') or '').upper()
        if f:
            g['formats'].add(f[:30])
    a, b = temporal_years(x.get('temporal'))
    for v in (a, b):
        if v:
            g['years'][0] = v if g['years'][0] is None else min(g['years'][0], v)
            g['years'][1] = v if g['years'][1] is None else max(g['years'][1], v)
    if my and (g['mod_latest'] is None or my > g['mod_latest']):
        g['mod_latest'] = my
    g['pop'] += x.get('popularity') or 0
    for f in x['flags']:
        g['flags'][f] += 1
    blob = ' '.join([str(x.get('id')), str(x.get('landing'))] + [str(d.get('downloadURL') or d.get('accessURL')) for d in x['distribution']])
    for fx in FOURBYFOUR.findall(blob):
        if fx in soc:
            g['socrata_ids'].add(fx)
    # representative member: most recently modified, then most popular
    score = (my or 0, x.get('popularity') or 0)
    if g['rep_score'] is None or score > g['rep_score']:
        g['rep_score'] = score
        g['rep'] = x

def norm_formats(fs):
    out = set()
    for f in fs:
        if 'CSV' in f: out.add('CSV')
        elif 'JSON' in f and 'GEO' not in f: out.add('JSON')
        elif 'GEOJSON' in f: out.add('GeoJSON')
        elif 'SHAPE' in f or f == 'SHP' or 'ZIP' in f and 'SHAPE' in f: out.add('Shapefile')
        elif 'KML' in f or 'KMZ' in f: out.add('KML')
        elif 'XLS' in f or 'EXCEL' in f or 'SPREADSHEET' in f: out.add('Excel')
        elif 'API' in f or 'ESRI REST' in f or 'ARCGIS' in f or f.startswith('WMS') or f.startswith('WFS'): out.add('API')
        elif 'PDF' in f: out.add('PDF')
        elif 'XML' in f: out.add('XML')
        elif 'ZIP' in f: out.add('ZIP')
        elif 'HTML' in f: out.add('Web page')
        else: out.add('Other')
    return sorted(out)

n_out = C.Counter()
used_socrata = set()
with open(P('index', 'records.jsonl'), 'w') as out:
    for k, g in groups.items():
        r = g['rep']
        cols, soc_id = None, None
        if g['socrata_ids']:
            soc_id = sorted(g['socrata_ids'])[0]
            cols = soc_columns(soc[soc_id])
            used_socrata |= g['socrata_ids']
        rec = {
            'id': 'dg:' + (r.get('slug') or r['id']),
            'source': 'data.gov',
            'title': r['title'],
            'description': r.get('description'),
            'publisher': r.get('publisher'),
            'org_type': r.get('org_type'),
            'keywords': r.get('keywords') or [],
            'themes': r.get('theme') or [],
            'spatial_text': r.get('spatial') if isinstance(r.get('spatial'), str) else None,
            'has_spatial': r.get('has_spatial'),
            'years': g['years'],
            'last_modified_year': g['mod_latest'],
            'formats': norm_formats(g['formats']),
            'landing_url': r.get('landing') or ('https://catalog.data.gov/dataset/' + r['slug'] if r.get('slug') else None),
            'series_count': g['n'],
            'series_examples': [m['title'] for m in g['members'][:3]] if g['n'] > 1 else [],
            'popularity': g['pop'],
            'columns': cols,
            'socrata_id': soc_id,
            'socrata_domain': soc[soc_id]['metadata']['domain'] if soc_id else None,
            'raw_ref': {'datagov_identifier': r['id'], 'group_key': k},
        }
        out.write(json.dumps(rec) + '\n')
        n_out['data.gov'] += 1
        if cols: n_out['data.gov with columns'] += 1

    # ---------- Socrata-only datasets ----------
    for sid, x in soc.items():
        if sid in used_socrata:
            continue
        r = x['resource']
        upd = year_of(r.get('data_updated_at') or r.get('updatedAt'))
        rec = {
            'id': 'soc:' + x['metadata']['domain'] + ':' + sid,
            'source': 'socrata',
            'title': r.get('name'),
            'description': r.get('description'),
            'publisher': (x.get('owner') or {}).get('display_name') or x['metadata']['domain'],
            'org_type': None,
            'keywords': (x.get('classification') or {}).get('domain_tags') or [],
            'themes': [c for c in [(x.get('classification') or {}).get('domain_category')] if c],
            'spatial_text': None, 'has_spatial': None,
            'years': [upd, upd], 'last_modified_year': upd,
            'formats': ['CSV', 'JSON', 'API'],
            'landing_url': x.get('permalink') or x.get('link'),
            'series_count': 1, 'series_examples': [], 'popularity': r.get('page_views', {}).get('page_views_total') or 0,
            'columns': soc_columns(x), 'socrata_id': sid, 'socrata_domain': x['metadata']['domain'],
            'raw_ref': {'socrata_id': sid},
        }
        out.write(json.dumps(rec) + '\n')
        n_out['socrata-only'] += 1

    # ---------- Census tables ----------
    cat = json.load(open(P('raw', 'census_catalog.json')))['dataset']
    fam_years = C.defaultdict(list); fam_title = {}; fam_latest = {}
    for d in cat:
        fam = '/'.join(d.get('c_dataset', []))
        v = d.get('c_vintage')
        if v: fam_years[fam].append(v)
        if fam not in fam_latest or (v or 0) >= (fam_latest[fam].get('c_vintage') or 0):
            fam_latest[fam] = d; fam_title[fam] = d.get('title')
    tables = {}
    for f in glob.glob(P('raw', 'census_groups', '*.json')):
        fam = os.path.basename(f)[:-5].replace('__', '/')
        try:
            gs = json.load(open(f)).get('groups', [])
        except Exception:
            gs = []
        d = fam_latest.get(fam, {})
        if len(gs) <= 1:
            # microdata or single-table product: one record for the whole product
            yrs = fam_years.get(fam) or [None]
            tables['FAM|' + fam] = {'title': d.get('title') or fam, 'description': d.get('description'), 'name': None,
                                    'universe': None, 'products': {fam: (min(yrs), max(yrs))},
                                    'microdata': bool(d.get('c_isMicrodata')), 'api': (d.get('distribution') or [{}])[0].get('accessURL')}
            continue
        for g in gs:
            key = g['name'] + '|' + (g.get('description') or '').lower()
            t = tables.setdefault(key, {'title': g.get('description'), 'name': g['name'], 'description': None,
                                        'universe': g.get('universe ') or g.get('universe'), 'products': {}, 'microdata': False,
                                        'api': g.get('variables')})
            yrs = fam_years.get(fam) or [None]
            t['products'][fam] = (min(yrs), max(yrs))
    for key, t in tables.items():
        prods = t['products']
        ys = [y for p in prods.values() for y in p if y]
        prod_names = sorted(fam_title.get(p, p) for p in prods)
        desc = t['description'] or ('Census table %s. Universe: %s. Available in: %s.' % (t['name'], t['universe'] or 'n/a', '; '.join(prod_names[:6])))
        rec = {
            'id': 'census:' + (t['name'] or key.split('|', 1)[1]) + ':' + hashlib.md5(key.encode()).hexdigest()[:8],
            'source': 'census',
            'title': (t['title'] or '').strip() if t['name'] is None else '%s (%s)' % ((t['title'] or '').strip(), t['name']),
            'description': desc,
            'publisher': 'U.S. Census Bureau',
            'org_type': 'Federal Government',
            'keywords': [], 'themes': [],
            'spatial_text': 'United States', 'has_spatial': False,
            'years': [min(ys) if ys else None, max(ys) if ys else None],
            'last_modified_year': max(ys) if ys else None,
            'formats': ['API'],
            'landing_url': t['api'],
            'series_count': len(prods), 'series_examples': prod_names[:3], 'popularity': 0,
            'columns': None, 'socrata_id': None, 'socrata_domain': None,
            'census': {'table': t['name'], 'universe': t['universe'], 'products': {k: list(v) for k, v in prods.items()},
                       'microdata': t['microdata']},
            'raw_ref': {'census_key': key},
        }
        out.write(json.dumps(rec) + '\n')
        n_out['census'] += 1

print(dict(n_out), 'total', sum(v for k, v in n_out.items() if 'with' not in k))
print('socrata ids matched into data.gov groups', len(used_socrata))
