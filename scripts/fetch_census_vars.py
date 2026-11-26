"""Fetch official variable labels for every Census table in the index.

Gives each table (1) a column dictionary (variable code -> plain label) and (2) a 'contains' list of the
distinct label parts, e.g. 'Under 5 years', 'Below poverty level', so searches can match inside the table.

Usage: python3 -I scripts/fetch_census_vars.py index/enriched.jsonl raw/census_vars.jsonl
"""
import json, re, sys, urllib.request, concurrent.futures as cf
src, dst = sys.argv[1], sys.argv[2]
jobs = []
for line in open(src):
    r = json.loads(line)
    if r['source'] == 'census' and (r.get('census') or {}).get('table') and str(r.get('landing_url', '')).endswith('.json'):
        jobs.append((r['id'], r['landing_url']))

def clean(label):
    parts = [p.strip().rstrip(':') for p in label.split('!!')]
    parts = [p for p in parts if p and p.lower() not in ('estimate', 'total', 'margin of error')]
    return parts

def fetch(job):
    rid, url = job
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            v = json.load(resp).get('variables', {})
    except Exception as e:
        return rid, None, str(e)[:80]
    cols, parts = [], {}
    for code in sorted(v):
        acs_style = re.match(r'^[A-Z0-9]+_\d+[A-Z]*$', code)
        if acs_style and (not code.endswith('E') or code.endswith('EA')):
            continue  # ACS-style codes: keep estimates only; skip margins of error and annotations
        if code in ('for', 'in', 'ucgid', 'GEO_ID') or code.endswith('_TTL'):
            continue
        p = clean(v[code].get('label', ''))
        if not p:
            p = ['Total']
        cols.append({'field': code, 'name': ' > '.join(p), 'type': v[code].get('predicateType'), 'label_source': 'official'})
        for x in p:
            parts[x] = parts.get(x, 0) + 1
    return rid, {'columns': cols, 'contains': list(parts)[:80]}, None

ok = err = 0
with open(dst, 'w') as f, cf.ThreadPoolExecutor(8) as ex:
    for rid, data, e in ex.map(fetch, jobs):
        if data:
            f.write(json.dumps({'id': rid, **data}) + '\n'); ok += 1
        else:
            err += 1
print('tables', len(jobs), '| labels fetched', ok, '| errors', err)
