"""Score search against the eval answer key.

Usage:
  python evals/run_eval.py index/search.db                 # all three modes
  python evals/run_eval.py index/search.db --modes hybrid  # one mode
  python evals/run_eval.py index/search.db --misses        # also list what came up instead, for each miss

Metrics (per mode, overall and per category):
  hit@1 / hit@5 / hit@10: share of questions whose correct dataset is in the top 1 / 5 / 10
  MRR: mean of 1/rank of the first correct result (0 if not in the top 10); rewards ranking it high
No-answer questions are listed separately with their top result, for a human to judge.
"""
import argparse, collections, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))
import search as S


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--questions', default=os.path.join(HERE, 'questions_draft.json'))
    ap.add_argument('--modes', default='keyword,vector,hybrid')
    ap.add_argument('--misses', action='store_true')
    ap.add_argument('--sweep', action='store_true', help='hybrid only: try value-matching and reranker settings and compare')
    ap.add_argument('--rerank-only', action='store_true', help='with --sweep: only the baseline and reranker rows')
    a = ap.parse_args()
    db = S.open_db(a.db)
    Q = json.load(open(a.questions, encoding='utf-8'))
    model = None
    results = {}
    if a.sweep:
        from fastembed import TextEmbedding
        model = TextEmbedding(db.execute("SELECT v FROM meta WHERE k='model'").fetchone()[0])
        print('%-22s %6s %6s %7s %6s  %s' % ('setting', 'hit@1', 'hit@5', 'hit@10', 'MRR', 'PLACES rank for "asthma rates in Ohio"'))
        settings = [(0, 0, True, None), (1.0, 0.3, False, None), (0.5, 0.3, True, None), (1.0, 0.3, True, None), (1.0, 0.35, True, None),
                    (1.0, 0.4, True, None), (0, 0, True, 'Xenova/ms-marco-MiniLM-L-6-v2'), (0, 0, True, 'BAAI/bge-reranker-base')]
        if a.rerank_only:
            settings = [s_ for s_ in settings if s_[3] or s_[0] == 0]
        for w, dmax, gate, rr in settings:
            S.VAL_WEIGHT, S.VAL_MAX_DIST, S.VAL_GATE, S.RERANK_MODEL = w, dmax, gate, rr
            c = collections.Counter()
            for q in Q:
                if q['category'] == 'no_answer':
                    continue
                got = [h['record']['id'] for h in S.search(db, q['question'], 10, 'hybrid', model)[1]]
                exp = {e['id'] for e in q['expected']}
                rank = next((i + 1 for i, g in enumerate(got) if g in exp), None)
                c['n'] += 1; c['h1'] += rank == 1; c['h5'] += bool(rank and rank <= 5); c['h10'] += rank is not None; c['rr'] += 1.0 / rank if rank else 0
            res_ = S.search(db, 'asthma rates in Ohio', 20, 'hybrid', model)
            top = [h['record']['display_title'] for h in res_[1]] + ['(inside) ' + h['record']['display_title'] for h in res_[3]]
            pr = next(((i + 1) if not t.startswith('(inside)') else 'in "found inside"' for i, t in enumerate(top) if 'PLACES' in t), None)
            label = ('rerank ' + rr.split('/')[-1][:14]) if rr else ('values off' if w == 0 else 'w %.2f d %.2f %s' % (w, dmax, 'gated' if gate else 'ungated'))
            print('%-22s %6d %6d %7d %6.2f  %s' % (label, c['h1'], c['h5'], c['h10'], c['rr'] / c['n'], pr or 'not in top 20'), flush=True)
        return
    for mode in a.modes.split(','):
        if mode != 'keyword' and model is None:
            from fastembed import TextEmbedding
            model = TextEmbedding(db.execute("SELECT v FROM meta WHERE k='model'").fetchone()[0])
        stats = collections.defaultdict(lambda: collections.Counter())
        misses, noans = [], []
        for q in Q:
            res = S.search(db, q['question'], 10, mode, model)
            got = [h['record'] for h in res[1]]
            if q['category'] == 'no_answer':
                noans.append((q, got[0]['display_title'] if got else '(no results)'))
                continue
            exp = {e['id'] for e in q['expected']}
            rank = next((i + 1 for i, r in enumerate(got) if r['id'] in exp), None)
            for key in ('ALL', q['category']):
                s = stats[key]
                s['n'] += 1
                s['h1'] += rank == 1
                s['h5'] += bool(rank and rank <= 5)
                s['h10'] += rank is not None
                s['rr'] += 1.0 / rank if rank else 0
            if not rank:
                misses.append((q, [r['display_title'] for r in got[:3]]))
        results[mode] = stats
        print('\n=== %s ===' % mode)
        print('%-10s %5s %7s %7s %7s %6s' % ('category', 'n', 'hit@1', 'hit@5', 'hit@10', 'MRR'))
        for key in ['ALL'] + sorted(k for k in stats if k != 'ALL'):
            s = stats[key]
            print('%-10s %5d %7s %7s %7s %6.2f' % (key, s['n'], '%d' % s['h1'], '%d' % s['h5'], '%d' % s['h10'], s['rr'] / s['n']))
        if a.misses:
            print('\nMisses (correct answer not in top 10):')
            for q, top in misses:
                print('  %s %s\n      wanted: %s\n      got:    %s' % (q['qid'], q['question'], q['expected'][0]['title'][:70], ' | '.join(t[:45] for t in top)))
        print('\nNo-answer questions (top result should clearly NOT be the thing asked for):')
        for q, top in noans:
            print('  %s %s -> %s' % (q['qid'], q['question'], top[:80]))
    if len(results) > 1:
        print('\n=== summary: hit@10 / MRR ===')
        for mode, st in results.items():
            s = st['ALL']
            print('  %-8s %d/%d  MRR %.2f' % (mode, s['h10'], s['n'], s['rr'] / s['n']))


if __name__ == '__main__':
    main()
