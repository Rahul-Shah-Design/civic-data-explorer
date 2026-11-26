import json,sys,re,collections as C
f=sys.argv[1]; n=0
ids=C.Counter(); titles=C.Counter(); orgtype=C.Counter(); orgs=C.Counter(); fmts=C.Counter(); dl=C.Counter(); sp=C.Counter()
desc_len=C.Counter(); has_mod=0; years=C.Counter(); parent=0; has_temporal=0; has_spatial_field=0; kw0=0; types=C.Counter()
img=0; imgpat=re.compile(r'\b(lidar|orthoimag|orthophoto|aerial imag|imagery|raster|dem\b|digital elevation|tile|tiles|naip|landsat|satellite imag|geotiff|point cloud|laz\b)',re.I)
normt=lambda t:re.sub(r'\b(19|20)\d\d\b|\d+','#',t.lower()).strip()
tmpl=C.Counter(); samples=[]
for line in open(f):
    x=json.loads(line); n+=1; d=x.get('dcat') or {}
    ids[x.get('identifier')]+=1; t=x.get('title') or ''; titles[t.lower()]+=1; tmpl[normt(t)]+=1
    o=x.get('organization') or {}; orgtype[o.get('organization_type') or '?']+=1; orgs[o.get('title') or '?']+=1
    types[x.get('type') or '?']+=1
    for di in d.get('distribution') or []: fmts[(di.get('format') or di.get('mediaType') or '?').upper()[:20]]+=1
    dl[bool(x.get('has_download'))]+=1; sp[bool(x.get('has_spatial'))]+=1
    L=len(x.get('description') or ''); desc_len['<50' if L<50 else '<200' if L<200 else '<1000' if L<1000 else '1000+']+=1
    m=d.get('modified') or ''; yy=re.match(r'(\d{4})',str(m))
    if yy: has_mod+=1; years[yy.group(1)]+=1
    if x.get('parent_identifier'): parent+=1
    if d.get('temporal'): has_temporal+=1
    if d.get('spatial'): has_spatial_field+=1
    if not x.get('keyword'): kw0+=1
    if imgpat.search(t+' '+' '.join(x.get('keyword') or [])): img+=1
print('records',n,'| unique identifiers',len(ids),'| dup identifiers',sum(v-1 for v in ids.values() if v>1))
print('unique exact titles',len(titles),'| unique title templates (years/numbers masked)',len(tmpl))
print('top repeated title templates',tmpl.most_common(12))
print('org types',orgtype.most_common())
print('top publishers',orgs.most_common(15))
print('record type',types.most_common(5))
print('has download',dict(dl),'| has spatial',dict(sp))
print('formats',fmts.most_common(15))
print('description length',dict(desc_len))
print('has modified',has_mod,'| has temporal',has_temporal,'| has spatial field',has_spatial_field,'| no keywords',kw0,'| in a collection (parent)',parent)
print('modified year',sorted(years.items())[-12:])
print('stale (modified before 2023)',sum(v for k,v in years.items() if k<'2023'))
print('imagery/tile-like titles or keywords',img)
