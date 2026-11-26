"""Peek inside data.gov CSV files: download only the first 64KB, read the header and sample rows.

Adds, per search result: column names, simple type guesses, category values (short text columns with few
distinct values) and 3 sample rows. One-time indexing cost. Resumable: skips ids already in the output.

Usage: python3 -I scripts/peek_csv.py <repo_root> raw/csv_peek.jsonl [seconds_budget]
"""
import csv, io, json, os, re, sys, time, urllib.request, concurrent.futures as cf, collections as C
root, dst = sys.argv[1], sys.argv[2]
budget = float(sys.argv[3]) if len(sys.argv) > 3 else 540
done = set()
if os.path.exists(dst):
    for line in open(dst):
        done.add(json.loads(line)['id'])
want = {}
for line in open(os.path.join(root, 'index', 'enriched.jsonl')):
    r = json.loads(line)
    if r['source'] == 'data.gov' and not r.get('columns') and 'CSV' in r['formats'] and r['id'] not in done:
        want[r['raw_ref']['datagov_identifier']] = r['id']
jobs = []
for line in open(os.path.join(root, 'clean', 'datagov_grouped.jsonl')):
    x = json.loads(line)
    rid = want.get(x['id'])
    if not rid:
        continue
    for d in x['distribution']:
        u = d.get('downloadURL') or ''
        if u.startswith('http') and ('csv' in (d.get('format') or '').lower() or 'csv' in (d.get('mediaType') or '').lower() or u.lower().endswith('.csv')):
            jobs.append((rid, u)); break
print('to peek', len(jobs), '| already done', len(done), flush=True)

NUM = re.compile(r'^-?[\d,]*\.?\d+$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}|^\d{1,2}/\d{1,2}/\d{2,4}')

def guess(vals):
    v = [x for x in vals if x]
    if not v: return 'empty'
    if all(NUM.match(x) for x in v): return 'number'
    if all(DATE.match(x) for x in v): return 'date'
    return 'text'

def peek(job):
    rid, url = job
    try:
        req = urllib.request.Request(url, headers={'Range': 'bytes=0-65535', 'User-Agent': 'civic-data-explorer/0.1 (metadata indexing)'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            ctype = resp.headers.get('Content-Type', '')
            raw = resp.read(65536)
    except Exception as e:
        return {'id': rid, 'url': url, 'error': type(e).__name__}
    if b'<html' in raw[:500].lower() or 'html' in ctype:
        return {'id': rid, 'url': url, 'error': 'html'}
    text = raw.decode('utf-8', errors='replace') if raw[:3] != b'\xef\xbb\xbf' else raw[3:].decode('utf-8', errors='replace')
    lines = text.splitlines()
    if len(lines) > 2 and len(raw) == 65536:
        lines = lines[:-1]  # last line is probably cut off
    try:
        dialect = csv.Sniffer().sniff('\n'.join(lines[:20]), delimiters=',;\t|')
    except Exception:
        dialect = csv.excel
    rows = list(csv.reader(lines, dialect))
    if len(rows) < 3 or len(rows[0]) < 2:
        return {'id': rid, 'url': url, 'error': 'not_tabular'}
    header = [h.strip() for h in rows[0]][:200]
    body = [r for r in rows[1:400] if len(r) == len(rows[0])]
    if not body:
        return {'id': rid, 'url': url, 'error': 'no_rows'}
    cols, values = [], {}
    for i, h in enumerate(header):
        colvals = [r[i].strip() for r in body if i < len(r)]
        t = guess(colvals)
        cols.append({'field': h, 'name': h, 'type': t, 'label_source': 'file_header'})
        if t == 'text':
            cnt = C.Counter(v for v in colvals if 2 < len(v) < 100)
            if 1 < len(cnt) <= 60 and sum(cnt.values()) >= 2 * len(cnt):  # repeated categories, not free text or ids
                values[h] = [v for v, _ in cnt.most_common(25)]
    return {'id': rid, 'url': url, 'columns': cols, 'values': values, 'sample_rows': [dict(zip(header, r)) for r in body[:3]], 'rows_seen': len(body)}

t0 = time.time(); stats = C.Counter()
with open(dst, 'a') as f, cf.ThreadPoolExecutor(32) as ex:
    futs = []
    for j in jobs:
        futs.append(ex.submit(peek, j))
    for fu in cf.as_completed(futs):
        res = fu.result()
        f.write(json.dumps(res) + '\n')
        stats['error' if 'error' in res else 'ok'] += 1
        if time.time() - t0 > budget:
            print('time budget reached; rerun to continue', flush=True)
            ex.shutdown(wait=False, cancel_futures=True)
            break
print(dict(stats), round(time.time() - t0), 's', flush=True)
