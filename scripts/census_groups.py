import json,sys,os,urllib.request,concurrent.futures as cf
cat=json.load(open(sys.argv[1]))['dataset']; out=sys.argv[2]
latest={}
for d in cat:
    fam='/'.join(d.get('c_dataset',[])); v=d.get('c_vintage') or 0
    if fam not in latest or v>(latest[fam].get('c_vintage') or 0): latest[fam]=d
def get(item):
    fam,d=item; fn=os.path.join(out,fam.replace('/','__')+'.json')
    if os.path.exists(fn): return fam,'cached'
    url=d.get('c_groupsLink')
    if not url: return fam,'nogroups'
    try:
        with urllib.request.urlopen(url,timeout=60) as r: data=r.read()
        open(fn,'wb').write(data); return fam,'ok'
    except Exception as e: return fam,'err '+str(e)[:60]
from collections import Counter
res=Counter()
with cf.ThreadPoolExecutor(8) as ex:
    for fam,s in ex.map(get,latest.items()): res[s.split()[0]]+=1
print('families',len(latest),dict(res))
