import json,sys,os,time,urllib.request,urllib.parse
out=sys.argv[1]; state=out+'.cursor'; DROP={'harvest_record_raw','spatial_shape','_score','_sort'}
after=open(state).read().strip() if os.path.exists(state) else None
n=sum(1 for _ in open(out)) if os.path.exists(out) else 0
t0=time.time(); budget=float(sys.argv[2]) if len(sys.argv)>2 else 540
with open(out,'a') as f:
    while time.time()-t0<budget:
        q={'per_page':1000}
        if after: q['after']=after
        url='https://catalog.data.gov/search?'+urllib.parse.urlencode(q)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url,timeout=90) as r: d=json.load(r); break
            except Exception as e:
                print('retry',attempt,str(e)[:80],flush=True); time.sleep(3*(attempt+1))
        else: sys.exit('failed')
        res=d.get('results',[])
        for x in res: f.write(json.dumps({k:v for k,v in x.items() if k not in DROP})+'\n')
        n+=len(res); f.flush()
        after=d.get('after')
        if not res or not after: open(state,'w').write('DONE'); print('DONE',n); break
        open(state,'w').write(after)
        if n%20000<1000: print('records',n,round(time.time()-t0),'s',flush=True)
print('total so far',n)
