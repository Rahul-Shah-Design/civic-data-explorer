"""Build the SQLite search index: records + FTS5 keyword index + sqlite-vec embeddings.

Usage:
  pip install fastembed sqlite-vec
  python scripts/build_index.py index/enriched.jsonl index/search.db

Resumable: rerun after an interruption (Ctrl+C is fine) and it continues where it stopped.
Uses every CPU core by default (--workers 0). On a 16-core laptop expect a few hundred records/second.
"""
import json, os, sqlite3, time, argparse
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

MODEL = 'BAAI/bge-small-en-v1.5'  # 384 dimensions


def embed_text(r):
    # Short on purpose: title + first part of description + column names. Long inputs are slow and add little.
    cols = ', '.join((c.get('name') or c.get('field') or '') for c in (r.get('columns') or [])[:25])
    univ = (r.get('census') or {}).get('universe')
    parts = [r['display_title'], (r.get('description') or '')[:500]]
    if univ:
        parts.append('Universe: ' + univ)
    if r.get('contains'):
        parts.append('Contains: ' + '; '.join(r['contains'])[:600])
    if cols:
        parts.append('Columns: ' + cols)
    return '. '.join(p for p in parts if p)


def open_db(path):
    import sqlite_vec
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def build_fts(db):
    """(Re)build the keyword index from the records table. Three columns, weighted at query time:
    title (high), main text (normal), values inside the data such as measures and Census labels (low)."""
    db.executescript('''
    DROP TABLE IF EXISTS fts;
    CREATE VIRTUAL TABLE fts USING fts5(display_title, search_text, contains_text, content='', tokenize='porter unicode61');
    ''')
    db.execute("""INSERT INTO fts(rowid, display_title, search_text, contains_text)
                  SELECT rowid, display_title, json_extract(doc,'$.search_text'),
                         coalesce((SELECT group_concat(value, '; ') FROM json_each(doc, '$.contains')), '')
                  FROM records""")
    db.commit()


def load_records(db, src, limit):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS records (rowid INTEGER PRIMARY KEY, id TEXT UNIQUE, source TEXT, display_title TEXT,
      publisher TEXT, states TEXT, geo_levels TEXT, year_min INT, year_max INT, freshness TEXT, access TEXT,
      map_type TEXT, popularity REAL, has_columns INT, doc TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS vec USING vec0(embedding float[384] distance_metric=cosine);
    CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
    ''')
    if db.execute('SELECT count(*) FROM records').fetchone()[0]:
        return
    rows = []
    sql = 'INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
    with open(src, encoding='utf-8') as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            r = json.loads(line)
            y = r.get('coverage_years') or [None, None]
            rows.append((i + 1, r['id'], r['source'], r['display_title'], r.get('publisher'), ','.join(r.get('states') or []),
                         ','.join(r.get('geo_levels') or []), y[0], y[1], r.get('freshness'), ','.join(r.get('access') or []),
                         r.get('map_type'), r.get('popularity') or 0, 1 if r.get('columns') else 0, line))
            if len(rows) == 5000:
                db.executemany(sql, rows)
                rows = []
    if rows:
        db.executemany(sql, rows)
    build_fts(db)
    db.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (MODEL,))
    db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('db')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--batch', type=int, default=4096, help='records per database commit')
    ap.add_argument('--no-embed', action='store_true', help='build records + keyword index only')
    ap.add_argument('--workers', type=int, default=0, help='embedding processes; 0 = one per CPU core')
    a = ap.parse_args()

    import sqlite_vec
    from fastembed import TextEmbedding

    db = open_db(a.db)
    load_records(db, a.src, a.limit)
    total = db.execute('SELECT count(*) FROM records').fetchone()[0]
    print('records', total, flush=True)
    if a.no_embed:
        return

    model = TextEmbedding(MODEL)
    done = db.execute('SELECT count(*) FROM vec').fetchone()[0]
    last = db.execute('SELECT coalesce(max(rowid), 0) FROM vec').fetchone()[0]
    t0, start = time.time(), done
    while True:
        batch = db.execute('SELECT rowid, doc FROM records WHERE rowid > ? ORDER BY rowid LIMIT ?', (last, a.batch)).fetchall()
        if not batch:
            break
        texts = [embed_text(json.loads(d)) for _, d in batch]
        vecs = list(model.embed(texts, batch_size=64, parallel=a.workers))
        db.executemany('INSERT INTO vec(rowid, embedding) VALUES (?, ?)',
                       [(rid, sqlite_vec.serialize_float32([float(x) for x in v])) for (rid, _), v in zip(batch, vecs)])
        db.commit()
        done += len(batch)
        last = batch[-1][0]
        rate = (done - start) / max(time.time() - t0, 1e-6)
        print(f'embedded {done}/{total}  {rate:.1f}/s  ~{(total - done) / max(rate, 1e-6) / 60:.0f} min left', flush=True)
    print('done')


if __name__ == '__main__':  # required on Windows: worker processes re-import this file
    main()
