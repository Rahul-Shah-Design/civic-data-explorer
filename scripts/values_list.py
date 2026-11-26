"""List the meaningful values found inside datasets (measures, topics, causes, offense types...), each linked
to the search results that contain it. index_values.py embeds them so a question can match a value directly:
'asthma rates' -> value 'Current asthma among adults' -> CDC PLACES.

Usage: python3 -I scripts/values_list.py <repo_root>   (writes index/values.jsonl)
"""
import json, os, re, sys, collections as C
root = sys.argv[1]
P = lambda *a: os.path.join(root, *a)
COL = re.compile(r'(measure|indicator|question|topic|category|cause|condition|disease|outcome|metric|variable|offense|crime|complaint|'
                 r'violation|type|program|service|description|class|reason|activity|subject)', re.I)
GENERIC = re.compile(r'^(yes|no|total|male|female|unknown|other|none|n/?a|all|both|overall|true|false|null|missing|not applicable|[\d.,/ :-]+)$', re.I)
soc_to_rec, rec_ids = {}, set()
for line in open(P('index', 'enriched.jsonl')):
    r = json.loads(line)
    rec_ids.add(r['id'])
    if r.get('socrata_id'):
        soc_to_rec.setdefault(r['socrata_id'], r['id'])
vals = C.defaultdict(set)
display = {}
def add(text, rid):
    t = re.sub(r'\s+', ' ', text).strip()
    k = t.lower()
    if len(k) < 5 or len(k) > 150 or GENERIC.match(k) or not re.search('[a-z]{4}', k):
        return
    vals[k].add(rid); display.setdefault(k, t)
for line in open(P('raw', 'socrata_values.jsonl')):
    x = json.loads(line)
    rid = soc_to_rec.get(x['socrata_id'])
    if rid:
        for k, v in x['values'].items():
            if k != '_errors':
                for s in v: add(s, rid)
for line in open(P('raw', 'csv_peek.jsonl')):
    x = json.loads(line)
    if x['id'] in rec_ids:
        for k, v in (x.get('values') or {}).items():
            if COL.search(k):
                for s in v: add(s, x['id'])
n = 0
with open(P('index', 'values.jsonl'), 'w') as f:
    for k, ids in vals.items():
        if len(ids) <= 15:  # values shared by many datasets (weekdays, 'white', 'active') carry no signal
            f.write(json.dumps({'text': display[k], 'ids': sorted(ids)}) + '\n'); n += 1
print('values', n)
