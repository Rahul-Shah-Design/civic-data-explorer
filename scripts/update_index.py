"""Apply a patch of changed records to an existing search.db, re-embedding only what changed.

Usage:
  python scripts/update_index.py index/search.db index/patch.jsonl

Each line of the patch is a full enriched record. Records are matched by id. The keyword index row is
replaced; the embedding is recomputed only if the embedded text changed. New ids are appended.
"""
import json, os, sys
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_index import embed_text, open_db, MODEL


def main():
    import sqlite_vec
    from fastembed import TextEmbedding
    db_path, patch = sys.argv[1], sys.argv[2]
    db = open_db(db_path)
    todo_embed, n_upd, n_new = [], 0, 0
    for line in open(patch, encoding='utf-8'):
        r = json.loads(line)
        y = r.get('coverage_years') or [None, None]
        vals = (r['source'], r['display_title'], r.get('publisher'), ','.join(r.get('states') or []), ','.join(r.get('geo_levels') or []),
                y[0], y[1], r.get('freshness'), ','.join(r.get('access') or []), r.get('map_type'), r.get('popularity') or 0,
                1 if r.get('columns') else 0, line)
        old = db.execute('SELECT rowid, doc FROM records WHERE id = ?', (r['id'],)).fetchone()
        if old:
            rid, od = old
            o = json.loads(od)
            db.execute("INSERT INTO fts(fts, rowid, display_title, search_text) VALUES('delete', ?, ?, ?)", (rid, o['display_title'], o['search_text']))
            db.execute('UPDATE records SET source=?, display_title=?, publisher=?, states=?, geo_levels=?, year_min=?, year_max=?, freshness=?, '
                       'access=?, map_type=?, popularity=?, has_columns=?, doc=? WHERE rowid=?', vals + (rid,))
            if embed_text(o) != embed_text(r):
                todo_embed.append((rid, r))
            n_upd += 1
        else:
            rid = db.execute('SELECT coalesce(max(rowid),0)+1 FROM records').fetchone()[0]
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (rid, r['id']) + vals)
            todo_embed.append((rid, r))
            n_new += 1
        db.execute('INSERT INTO fts(rowid, display_title, search_text) VALUES (?, ?, ?)', (rid, r['display_title'], r['search_text']))
    db.commit()
    print('updated', n_upd, '| new', n_new, '| re-embedding', len(todo_embed), flush=True)
    if todo_embed:
        model = TextEmbedding(MODEL)
        vecs = list(model.embed([embed_text(r) for _, r in todo_embed], batch_size=64))
        for (rid, _), v in zip(todo_embed, vecs):
            db.execute('DELETE FROM vec WHERE rowid = ?', (rid,))
            db.execute('INSERT INTO vec(rowid, embedding) VALUES (?, ?)', (rid, sqlite_vec.serialize_float32([float(x) for x in v])))
        db.commit()
    print('done')


if __name__ == '__main__':
    main()
