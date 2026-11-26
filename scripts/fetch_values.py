"""Fetch the distinct values of category columns (Measure, Indicator, Topic, Cause...) for Socrata datasets.

Why: many health and city datasets are 'long format'. CDC PLACES never says 'asthma' in its title or
description; asthma is a value in its Measure column. Indexing those values makes the topic searchable.

Usage: python3 -I scripts/fetch_values.py index/enriched.jsonl raw/socrata_values.jsonl
"""
import json, re, sys, urllib.request, urllib.parse, concurrent.futures as cf
src, dst = sys.argv[1], sys.argv[2]
COL = re.compile(r'^(measure|measure_?name|measuredesc|short_question_text|indicator|indicator_?name|question|topic|category|'
                 r'cause|cause_?name|condition|disease|outcome|response|metric|variable|offense|offense_?description|'
                 r'description|type|incident_?type|complaint_?type|violation_?description|program)$', re.I)
jobs = []
for line in open(src):
    r = json.loads(line)
    if not r.get('socrata_id') or not r.get('columns'):
        continue
    cols = [c['field'] for c in r['columns'] if COL.match(c.get('field') or '') and (c.get('type') or 'text').lower() == 'text'][:3]
    if cols:
        jobs.append((r['socrata_domain'], r['socrata_id'], cols))

def fetch(job):
    dom, sid, cols = job
    out = {}
    for c in cols:
        q = {'$select': '`%s`, count(*) AS n' % c, '$group': '`%s`' % c, '$order': 'n DESC', '$limit': '80'}
        url = 'https://%s/resource/%s.json?%s' % (dom, sid, urllib.parse.urlencode(q))
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                rows = json.load(resp)
            vals = [str(x.get(c)).strip() for x in rows if x.get(c)]
            vals = [v for v in vals if 2 < len(v) < 120]
            if len(vals) >= 2:
                out[c] = vals
        except Exception as e:
            out.setdefault('_errors', []).append('%s: %s' % (c, str(e)[:60]))
    return sid, out

ok = 0
with open(dst, 'w') as f, cf.ThreadPoolExecutor(6) as ex:
    for sid, out in ex.map(fetch, jobs):
        f.write(json.dumps({'socrata_id': sid, 'values': out}) + '\n')
        ok += any(k != '_errors' for k in out)
print('datasets checked', len(jobs), '| with category values', ok)
