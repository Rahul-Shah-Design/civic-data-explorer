import json,sys,re,collections as C
src,dst=sys.argv[1],sys.argv[2]
S='alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|district of columbia|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|puerto rico|guam|american samoa|virgin islands|northern mariana islands'
SR=re.compile(r'\b('+S+r')\b')
CTY=re.compile(r"[a-z.'\- ]+ (county|parish|borough|census area|municipio|municipality|city and borough|city), [a-z]{2}\b")
FMT=re.compile(r'\((shp|kml|geodatabase|gdb|csv|xml)\)|\b(shapefile|kml|geodatabase)\b')
NUM=re.compile(r'\b(19|20)\d\d\b|\d+')
SCI2=re.compile(r'^(compound \d+:|patent [a-z]{2}-|substance \d+)|paleoclimatology|multibeam|benthic|\bcoral\b|mooring|\bbuoys?\b|avhrr|underway|magnetotelluric|seismic|volcano|isotop|geochem|biomarker|mussel|sediment|core samples?|ice breakup|tree[- ]ring|itrdb|radiosonde|ocean color|chlorophyll|zooplankton|larva|otolith|genom|sequenc|microb|\bspecies\b.*\b(survey|occurrence)|trawl|acoustic',re.I)
DOC=re.compile(r'^(what|how|who|when|where|why|can|do|does|is|are)\b.*\?$|program instruction|information memorandum|dear colleague|\bfaq\b|press release',re.I)
def key(x):
    p=x['parent']
    if p and 'localhost' not in p: return 'P|'+p
    t=re.sub(r'\s+',' ',x['title'].lower()).strip(); pub=x['publisher']
    m=re.match(r'tiger/line shapefile, \d{4}, ?(?:\w+, )?(?:.*?, [a-z]{2}, )?(.*)',t)
    if m: return 'TIGER|'+re.sub(r'county-based|shapefile|relationship file|\s+',' ',m.group(1)).strip()
    if t.endswith('time series data'): return pub+'|TS'
    t=re.sub(r'^station [\w-]+, ','',t)
    t=CTY.sub('PLACE',t); t=SR.sub('STATE',t); t=FMT.sub('FMT',t); t=re.sub(r', [a-z]{2}\b',', ST',t); t=NUM.sub('#',t)
    return pub+'|'+t
st=C.Counter(); g=C.Counter(); pubg=C.defaultdict(set)
with open(dst,'w') as out:
    for line in open(src):
        x=json.loads(line); f=x['flags']
        if 'imagery' not in f and 'science' not in f:
            if SCI2.search(x['title']): f.append('science')
            elif DOC.search(x['title']): f.append('document')
        x['group_key']=key(x)
        if any(k in f for k in('imagery','science','document')): st['excluded_'+next(k for k in('imagery','science','document') if k in f)]+=1
        else: st['kept']+=1; g[x['group_key']]+=1; pubg[x['publisher']].add(x['group_key'])
        out.write(json.dumps(x)+'\n')
print(dict(st)); print('search results (groups)',len(g))
print('by publisher',sorted(((p[:40],len(v)) for p,v in pubg.items()),key=lambda z:-z[1])[:10])
print('sizes',dict(C.Counter('1' if v==1 else '2-10' if v<=10 else '11-100' if v<=100 else '100+' for v in g.values())))
