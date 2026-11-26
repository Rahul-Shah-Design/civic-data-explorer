import json,sys,re,collections as C
src,dst=sys.argv[1],sys.argv[2]
IMG=re.compile(r'\b(lidar|orthoimag\w*|orthophoto\w*|aerial (photo|imag)\w*|imagery|raster|digital elevation|elevation model|\bdem\b|naip|landsat|satellite imag\w*|geotiff|point cloud|laz|tile index|quarter quad)',re.I)
SCI_T=re.compile(r'(hydrographic survey|\bcruise\b|\bctd\b|vmadcp|\badcp\b|\bsubstance \d|orbiter|mars |comet|lunar|jupiter|saturn|cassini|spectrometer|mission\b.*\bv\d|seafloor|bathymetr|sediment core|plankton|telemetry)',re.I)
SCI_PUB=('National Aeronautics and Space Administration','National Institute of Standards and Technology')
mask=lambda t:re.sub(r'\b(19|20)\d\d\b|\d+','#',re.sub(r'\s+',' ',t.lower())).strip()
seen=set(); st=C.Counter(); groups=C.defaultdict(int); kept_groups=C.defaultdict(int)
with open(dst,'w') as out:
    for line in open(src):
        x=json.loads(line); st['in']+=1
        i=x.get('identifier')
        if i in seen: st['dup_id']+=1; continue
        seen.add(i)
        d=x.get('dcat') or {}; t=x.get('title') or ''; kw=' '.join(x.get('keyword') or [])
        org=(x.get('organization') or {}); pub=org.get('name') or ''
        fmts=[(di.get('format') or di.get('mediaType') or '').upper() for di in d.get('distribution') or []]
        flags=[]
        if IMG.search(t+' '+kw) or any(f in('TIFF','GEOTIFF','LAZ','LAS','JPEG2000','MRSID') for f in fmts): flags.append('imagery')
        if pub in SCI_PUB or SCI_T.search(t): flags.append('science')
        m=re.match(r'(\d{4})',str(d.get('modified') or ''))
        yr=int(m.group(1)) if m and 1990<=int(m.group(1))<=2026 else None
        if yr is None: flags.append('bad_date')
        elif yr<2023: flags.append('stale')
        dist=[di for di in d.get('distribution') or [] if 'PLACEHOLDER' not in (di.get('format') or '').upper()]
        gkey=x.get('parent_identifier') or (pub+'|'+mask(t))
        excluded=('imagery' in flags) or ('science' in flags)
        groups[gkey]+=1
        if excluded: st['excluded_'+('imagery' if 'imagery' in flags else 'science')]+=1
        else: kept_groups[gkey]+=1; st['kept_records']+=1
        rec={'id':i,'title':t,'description':x.get('description'),'publisher':pub,'org_type':org.get('organization_type'),'keywords':x.get('keyword'),'theme':x.get('theme'),
             'modified':d.get('modified'),'modified_year':yr,'temporal':d.get('temporal'),'spatial':d.get('spatial'),'has_spatial':x.get('has_spatial'),
             'access_level':x.get('access_level'),'landing':d.get('landingPage'),'distribution':[{k:di.get(k) for k in('title','format','mediaType','downloadURL','accessURL')} for di in dist],
             'parent':x.get('parent_identifier'),'group_key':gkey,'flags':flags,'slug':x.get('slug'),'popularity':x.get('popularity')}
        out.write(json.dumps(rec)+'\n')
for k,v in st.items(): print(k,v)
print('groups (all)',len(groups),'| groups kept (search results)',len(kept_groups))
sizes=C.Counter('1' if v==1 else '2-10' if v<=10 else '11-100' if v<=100 else '100+' for v in kept_groups.values()); print('kept group sizes',dict(sizes))
