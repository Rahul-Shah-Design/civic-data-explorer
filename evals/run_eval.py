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
    a = ap.parse_args()
    db = S.open_db(a.db)
    Q = json.load(open(a.questions, encoding='utf-8'))
    model = None
    results = {}
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
