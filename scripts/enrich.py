"""Rule-based enrichment of merged records.

Usage: python3 -I scripts/enrich.py <repo_root>
Reads index/records.jsonl, writes index/enriched.jsonl
Adds: display_title, states, geo_levels, coverage_years, map_type, freshness, access, search_text.
Every derived field is rule-based; provenance is recorded in `derived`.
"""
import json, os, re, sys, collections as C

root = sys.argv[1]
P = lambda *a: os.path.join(root, *a)
THIS_YEAR = 2026

STATES = {'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA','colorado':'CO','connecticut':'CT','delaware':'DE',
 'district of columbia':'DC','florida':'FL','georgia':'GA','hawaii':'HI','idaho':'ID','illinois':'IL','indiana':'IN','iowa':'IA','kansas':'KS',
 'kentucky':'KY','louisiana':'LA','maine':'ME','maryland':'MD','massachusetts':'MA','michigan':'MI','minnesota':'MN','mississippi':'MS',
 'missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV','new hampshire':'NH','new jersey':'NJ','new mexico':'NM','new york':'NY',
 'north carolina':'NC','north dakota':'ND','ohio':'OH','oklahoma':'OK','oregon':'OR','pennsylvania':'PA','rhode island':'RI',
 'south carolina':'SC','south dakota':'SD','tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT','virginia':'VA','washington':'WA',
 'west virginia':'WV','wisconsin':'WI','wyoming':'WY','puerto rico':'PR','guam':'GU'}
ABBR = set(STATES.values())
STATE_RE = re.compile(r'\b(' + '|'.join(sorted(STATES, key=len, reverse=True)) + r')\b', re.I)
ABBR_RE = re.compile(r',\s*(' + '|'.join(ABBR) + r')\b')
# Non-federal publishers (data.gov organization names and Socrata domains) -> state
PUB_STATE = {'City of New York':'NY','City of Chicago':'IL','City of Austin':'TX','City of Los Angeles':'CA','District of Columbia':'DC',
 'Lake County, Illinois':'IL','City of Seattle':'WA','City of San Francisco':'CA','City and County of San Francisco':'CA','Montgomery County, Maryland':'MD',
 'City of Baton Rouge':'LA','City of New Orleans':'LA','City of Boston':'MA','City of Hartford':'CT','Cook County, Illinois':'IL','City of Providence':'RI',
 'City of Somerville':'MA','City of Bloomington':'IN','City of Tempe':'AZ','City of Honolulu':'HI','Arlington County, Virginia':'VA','Fairfax County, Virginia':'VA',
 'data.cityofnewyork.us':'NY','data.cityofchicago.org':'IL','data.lacity.org':'CA','data.ny.gov':'NY','data.texas.gov':'TX','data.wa.gov':'WA',
 'data.ct.gov':'CT','opendata.maryland.gov':'MD','data.pa.gov':'PA','data.colorado.gov':'CO','data.montgomerycountymd.gov':'MD','data.sfgov.org':'CA','data.sf.gov':'CA'}

GEO = [  # (level, pattern) checked against title + description + column names. Kept strict: these feed filters.
 ('block group', r'\bblock groups?\b'), ('tract', r'\bcensus tracts?\b'), ('zip code', r'\bzip ?codes?\b|\bzcta\b'),
 ('county', r'\bby county\b|\bcounty[- ]level\b|\bcount(y|ies) (name|fips|code)\b|\beach county\b|\ball counties\b|\bcounties\b'),
 ('city', r'\bby city\b|\bcity[- ]level\b|\bmunicipalit(y|ies)\b|\bcities\b'),
 ('school district', r'\bschool districts?\b'), ('congressional district', r'\bcongressional districts?\b'),
 ('metro area', r'\bmetro(politan)? (statistical )?areas?\b|\bmsa\b|\bcbsa\b'),
 ('state', r'\bby state\b|\bstate[- ]level\b|\beach state\b|\ball states\b|\b50 states\b|\bstate (name|abbreviation|fips|code)\b'),
 ('national', r'\bnational[- ]level\b|\bnationwide\b|\bnational (estimates?|totals?)\b|\bu\.s\. totals?\b'),
 ('address / point', r'\blatitude\b|\blongitude\b|\bstreet address\b|\baddresses\b|\blocations of\b|\bpoint locations?\b|\bx ?coordinate\b'),
 ('neighborhood / ward', r'\bneighborhoods?\b|\bwards?\b|\bcommunity areas?\b|\bprecincts?\b|\bcommunity districts?\b'),
]
GEO = [(l, re.compile(p, re.I)) for l, p in GEO]
CENSUS_GEO = {'acs/acs5': ['national', 'state', 'county', 'city', 'tract', 'block group', 'zip code', 'congressional district', 'school district', 'metro area'],
              'acs/acs1': ['national', 'state', 'county', 'city', 'congressional district', 'metro area'],
              'dec/dhc': ['national', 'state', 'county', 'city', 'tract', 'block group', 'zip code']}
BOUNDARY_RE = re.compile(r'\bboundar(y|ies)\b|\btiger\b|\bdistricts?\b|\bzones?\b|\bparcels?\b|\bwards?\b|\bprecincts?\b|\bcartographic\b|\bpolygons?\b|\bfootprints?\b', re.I)
MAP_FMT = {'Shapefile', 'KML', 'GeoJSON'}
YEAR_RE = re.compile(r'\b(19[5-9]\d|20[0-2]\d)\b')
MASK_STATE = re.compile(r',?\s*\b(state|county),\s*', re.I)

def display_title(r):
    t = r['title'] or ''
    if r['source'] == 'census' or r['series_count'] <= 1:
        return t
    if t.lower().startswith('tiger/line shapefile'):
        m = re.match(r'tiger/line shapefile, \d{4}, ?(?:\w+, )?(?:.*?, [A-Z]{2}, )?(.*)', t, re.I)
        layer = m.group(1) if m else t
        layer = re.sub(r'(county|state|nation)-based|shapefile|relationship file', '', layer, flags=re.I).strip(' ,')
        return 'TIGER/Line: %s' % layer
    ex = r.get('series_examples') or []
    def varies(rx):
        vals = {tuple(m.lower() for m in rx.findall(e)) for e in ex}
        return len(vals) > 1
    s = t
    if varies(STATE_RE): s = re.sub(r'\bfor STATE\b', 'by state', STATE_RE.sub('STATE', s)).replace('STATE', '')
    cty = re.compile(r"[A-Z][\w.'\- ]+ (?:County|Parish|Borough|Census Area), [A-Z]{2}\b")
    if varies(cty): s = cty.sub('', s)
    yr = re.compile(r'\b(?:FY ?)?(?:19|20)\d\d(?:-\d{2,4})?\b')
    if varies(yr): s = yr.sub('', s)
    if s == t: return t
    for _ in range(2):
        s = re.sub(r'\(\s*\)', '', s)
        s = re.sub(r',(\s*,)+', ',', s)
        s = re.sub(r'\s+,', ',', s)
        s = re.sub(r'\s{2,}', ' ', s).strip(' ,-:')
        s = re.sub(r'\b(for|in|of|and|the|from|to|fiscal year|fy|year)\s*([,)]|$)', r'\2', s, flags=re.I)
        s = re.sub(r'^(and|of|for)\s+', '', s, flags=re.I)
        s = re.sub(r'-\)', ')', s)
    return s if len(s) >= 8 else t

def states_of(r, text):
    found = set()
    pub = r.get('publisher') or ''
    if pub in PUB_STATE: found.add(PUB_STATE[pub])
    if r.get('socrata_domain') in PUB_STATE: found.add(PUB_STATE[r['socrata_domain']])
    m = re.match(r'(State|Commonwealth) of (.+)', pub)
    if m and m.group(2).lower() in STATES: found.add(STATES[m.group(2).lower()])
    if r['source'] == 'census' or (r['series_count'] > 5 and r.get('org_type') == 'Federal Government'):
        return ['US'], 'publisher_scope'
    if found: return sorted(found), 'publisher'
    hits = {STATES[x.lower()] for x in STATE_RE.findall(text[:600])} | set(ABBR_RE.findall(r['title'] or ''))
    hits.discard('WA') if 'washington, d' in text.lower()[:600] else None
    if hits and len(hits) <= 3: return sorted(hits), 'text'
    if r.get('org_type') == 'Federal Government': return ['US'], 'publisher_scope'
    return [], None

def geo_levels(r, text):
    if r['source'] == 'census':
        lv = set()
        for p in (r.get('census') or {}).get('products', {}):
            lv |= set(CENSUS_GEO.get(p, []))
        return sorted(lv) if lv else ['national', 'state'], 'census_product'
    lv = [l for l, rx in GEO if rx.search(text)]
    return lv, 'text' if lv else None

def coverage(r, text):
    y = r.get('years') or [None, None]
    if y[0]: return y, 'temporal'
    ys = [int(v) for v in YEAR_RE.findall((r['title'] or '') + ' ' + (r.get('description') or '')[:400])]
    ys = [v for v in ys if v <= THIS_YEAR]
    if ys: return [min(ys), max(ys)], 'title_description'
    return [None, None], None

def freshness(r):
    m = r.get('last_modified_year')
    if not m: return 'unknown'
    age = THIS_YEAR - m
    return 'current' if age <= 1 else 'recent' if age <= 3 else 'stale'

def access(r):
    f = set(r['formats'])
    a = []
    if f & {'CSV', 'JSON', 'Excel', 'XML', 'ZIP', 'Shapefile', 'GeoJSON', 'KML'}: a.append('download')
    if 'API' in f or r.get('socrata_id') or r['source'] == 'census': a.append('api')
    if not a and f & {'PDF', 'Web page'}: a.append('documents_only')
    return a or ['unknown']

# Category values (Measure, Topic, Cause...) fetched by scripts/fetch_values.py, keyed by Socrata id
VALUES = {}
if os.path.exists(P('raw', 'socrata_values.jsonl')):
    for line in open(P('raw', 'socrata_values.jsonl')):
        x = json.loads(line)
        vals = []
        for k, v in x['values'].items():
            if k != '_errors':
                vals += v
        if vals:
            VALUES[x['socrata_id']] = list(dict.fromkeys(vals))[:80]
RESEARCH = re.compile(r'scihub|\bet al\b|^dataset ?[-:]|supporting dataset|^data (for|from|and code)\b|^data supporting|manuscript|\bjournal\b|supplementa', re.I)

stats = C.Counter()
with open(P('index', 'enriched.jsonl'), 'w') as out:
    for line in open(P('index', 'records.jsonl')):
        r = json.loads(line)
        cols = r.get('columns') or []
        coltext = ' '.join((c.get('name') or '') + ' ' + (c.get('description') or '') for c in cols[:60])
        text = ' '.join([r['title'] or '', r.get('description') or '', ' '.join(r.get('keywords') or []), r.get('spatial_text') or '', coltext])
        d = {}
        r['display_title'] = display_title(r)
        r['states'], d['states'] = states_of(r, text)
        r['geo_levels'], d['geo_levels'] = geo_levels(r, text)
        r['coverage_years'], d['coverage_years'] = coverage(r, text)
        fm = set(r['formats'])
        if fm & MAP_FMT or re.search(r'shapefile|\(shp\)|\bkml\b|geodatabase|cartographic boundary', r['title'] or '', re.I) or (r.get('has_spatial') and BOUNDARY_RE.search(r['title'] or '') and 'API' in fm):
            r['map_type'] = 'boundary' if BOUNDARY_RE.search(r['title'] or '') else 'features'
        else:
            r['map_type'] = None
        r['freshness'] = freshness(r)
        r['access'] = access(r)
        r['contains'] = VALUES.get(r.get('socrata_id')) or None
        if r['contains']: d['contains'] = 'socrata_category_values'
        r['research_like'] = bool(RESEARCH.search(r['title'] or '')) or None
        r['derived'] = {k: ('rule:' + v if v else None) for k, v in d.items()}
        kw = ', '.join((r.get('keywords') or [])[:15])
        colnames = ', '.join((c.get('name') or c.get('field')) for c in cols[:40])
        univ = (r.get('census') or {}).get('universe')
        r['search_text'] = '\n'.join(x for x in [r['display_title'], (r.get('description') or '')[:1500],
                                                  'Universe: ' + univ if univ else '', 'Keywords: ' + kw if kw else '',
                                                  'Contains: ' + '; '.join(r['contains']) if r['contains'] else '',
                                                  'Columns: ' + colnames if colnames else '', 'Publisher: ' + (r.get('publisher') or '')] if x)
        out.write(json.dumps(r) + '\n')
        stats['records'] += 1
        stats['has_states'] += bool(r['states']); stats['us_wide'] += r['states'] == ['US']
        stats['has_geo_levels'] += bool(r['geo_levels']); stats['has_years'] += bool(r['coverage_years'][0])
        stats['map_' + str(r['map_type'])] += 1; stats['fresh_' + r['freshness']] += 1
        for a in r['access']: stats['access_' + a] += 1
        stats['has_columns'] += bool(cols)
        stats['retitled'] += r['display_title'] != r['title']
        stats['has_contains'] += bool(r['contains']); stats['research_like'] += bool(r['research_like'])
for k in sorted(stats): print(k, stats[k])
