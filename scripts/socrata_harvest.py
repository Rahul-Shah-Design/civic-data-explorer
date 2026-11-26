import json,sys,urllib.request,urllib.parse,time
doms=sys.argv[2].split(','); out=sys.argv[1]
with open(out,'w') as f:
    for dom in doms:
        n=0;scroll=None
        while True:
            q={'domains':dom,'search_context':dom,'only':'dataset','limit':1000,'order':'page_views_total'} if False else {'domains':dom,'only':'dataset','limit':1000}
            if scroll: q['scroll_id']=scroll
            url='https://api.us.socrata.com/api/catalog/v1?'+urllib.parse.urlencode(q)
            for a in range(3):
                try:
                    with urllib.request.urlopen(url,timeout=90) as r: d=json.load(r);break
                except Exception as e: time.sleep(3); d=None
            if not d: print(dom,'FAILED');break
            res=d.get('results',[])
            if not res: break
            for x in res: f.write(json.dumps(x)+'\n')
            n+=len(res); scroll=res[-1]['resource']['id']
            if len(res)<1000: break
        print(dom,n,flush=True)
