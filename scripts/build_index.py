"""Build the SQLite search index: records + FTS5 keyword index + sqlite-vec embeddings.

Usage:
  pip install fastembed sqlite-vec
  python3 scripts/build_index.py index/enriched.jsonl index/search.db [--limit N]

Resumable: rerun after an interruption and it continues embedding where it stopped.
Speed depends on the machine: a recent laptop does roughly 50-300 records/second;
a 2-core cloud box does about 5.
"""
import json, sqlite3, sys, time, argparse
import sqlite_vec
from fastembed import TextEmbedding

ap = argparse.ArgumentParser()
ap.add_argument('src'); ap.add_argument('db'); ap.add_argument('--limit', type=int, default=0)
ap.add_argument('--batch', type=int, default=256)
a = ap.parse_args()

MODEL = 'BAAI/bge-small-en-v1.5'  # 384 dimensions
db = sqlite3.connect(a.db)
db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
db.executescript('''
CREATE TABLE IF NOT EXISTS records (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, source TEXT, display_title TEXT,
  publisher TEXT, states TEXT, geo_levels TEXT, year_min INT, year_max INT, freshness TEXT, access TEXT,
  map_type TEXT, popularity REAL, has_columns INT, doc TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(display_title, search_text, content='', tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0(embedding float[384] distance_metric=cosine);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
''')

def embed_text(r):
    # Short on purpose: title + first part of description + column names. Long inputs are slow and add little.
    cols = ', '.join((c.get('name') or c.get('field') or '') for c in (r.get('columns') or [])[:25])
    univ = (r.get('census') or {}).get('universe')
    parts = [r['display_title'], (r.get('description') or '')[:500]]
    if univ: parts.append('Universe: ' + univ)
    if cols: parts.append('Columns: ' + cols)
    return '. '.join(p for p in parts if p)

# 1) load records + FTS (fast, idempotent)
n_have = db.execute('SELECT count(*) FROM records').fetchone()[0]
if n_have == 0:
    rows = []
    for i, line in enumerate(open(a.src)):
        if a.limit and i >= a.limit: break
        r = json.loads(line)
        y = r.get('coverage_years') or [None, None]
        rows.append((i + 1, r['id'], r['source'], r['display_title'], r.get('publisher'), ','.join(r.get('states') or []),
                     ','.join(r.get('geo_levels') or []), y[0], y[1], r.get('freshness'), ','.join(r.get('access') or []),
                     r.get('map_type'), r.get('popularity') or 0, 1 if r.get('columns') else 0, line))
        if len(rows) == 5000:
            db.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows); rows = []
    if rows: db.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
    db.execute("INSERT INTO fts(rowid, display_title, search_text) SELECT rowid, display_title, json_extract(doc,'$.search_text') FROM records")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (MODEL,))
    db.commit()
total = db.execute('SELECT count(*) FROM records').fetchone()[0]
print('records', total, flush=True)

# 2) embeddings (slow, resumable)
model = TextEmbedding(MODEL)
done = db.execute('SELECT count(*) FROM vec').fetchone()[0]
t0 = time.time(); start = done
while True:
    batch = db.execute('SELECT rowid, doc FROM records WHERE rowid NOT IN (SELECT rowid FROM vec) ORDER BY rowid LIMIT ?', (a.batch,)).fetchall()
    if not batch: break
    texts = [embed_text(json.loads(d)) for _, d in batch]
    vecs = list(model.embed(texts, batch_size=64))
    db.executemany('INSERT INTO vec(rowid, embedding) VALUES (?, ?)',
                   [(rid, sqlite_vec.serialize_float32(list(map(float, v)))) for (rid, _), v in zip(batch, vecs)])
    db.commit()
    done += len(batch)
    rate = (done - start) / max(time.time() - t0, 1e-6)
    print(f'embedded {done}/{total}  {rate:.1f}/s  ~{(total - done) / max(rate, 1e-6) / 60:.0f} min left', flush=True)
print('done')
