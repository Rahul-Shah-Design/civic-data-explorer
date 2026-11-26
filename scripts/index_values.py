"""Embed the values found inside datasets as their own search targets (run once, after build_index.py).

Usage: python scripts/index_values.py index/search.db index/values.jsonl
"""
import json, os, sys, time
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_index import open_db, MODEL


def main():
    import sqlite_vec
    from fastembed import TextEmbedding
    db = open_db(sys.argv[1])
    db.executescript('''
    DROP TABLE IF EXISTS vals;
    DROP TABLE IF EXISTS vec_vals;
    CREATE TABLE vals (vid INTEGER PRIMARY KEY, text TEXT, rowids TEXT);
    CREATE VIRTUAL TABLE vec_vals USING vec0(embedding float[384] distance_metric=cosine);
    ''')
    rowid_of = dict(db.execute('SELECT id, rowid FROM records'))
    rows = []
    for line in open(sys.argv[2], encoding='utf-8'):
        x = json.loads(line)
        rids = [rowid_of[i] for i in x['ids'] if i in rowid_of]
        if rids:
            rows.append((len(rows) + 1, x['text'], json.dumps(rids)))
    db.executemany('INSERT INTO vals VALUES (?,?,?)', rows)
    db.commit()
    print('values', len(rows), flush=True)
    model = TextEmbedding(MODEL)
    t0 = time.time()
    for i in range(0, len(rows), 4096):
        chunk = rows[i:i + 4096]
        vecs = list(model.embed([t for _, t, _ in chunk], batch_size=128, parallel=0))
        db.executemany('INSERT INTO vec_vals(rowid, embedding) VALUES (?, ?)',
                       [(vid, sqlite_vec.serialize_float32([float(v) for v in vec])) for (vid, _, _), vec in zip(chunk, vecs)])
        db.commit()
        done = i + len(chunk)
        rate = done / max(time.time() - t0, 1e-6)
        print(f'embedded {done}/{len(rows)}  {rate:.0f}/s  ~{(len(rows) - done) / rate / 60:.0f} min left', flush=True)
    print('done')


if __name__ == '__main__':
    main()
