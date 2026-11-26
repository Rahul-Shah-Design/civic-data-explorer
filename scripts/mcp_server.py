"""MCP server: lets AI agents (Claude Desktop, Claude Code, etc.) search the civic data index.

Run (Claude Desktop starts it for you; see README):
  python scripts/mcp_server.py index/search.db

Tools:
  search_datasets  find public datasets for a plain-language question, with optional filters
  get_dataset      full details for one result: description, columns, coverage, access links, caveats
"""
import json, os, sys
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import search as S
from mcp.server.mcpserver import MCPServer

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'index', 'search.db')
db = S.open_db(DB_PATH)
_model = None


def model():
    global _model
    has_vec = db.execute('SELECT count(*) FROM vec').fetchone()[0] > 0
    if _model is None and has_vec:
        from fastembed import TextEmbedding
        _model = TextEmbedding(db.execute("SELECT v FROM meta WHERE k='model'").fetchone()[0])
    return _model


INSTRUCTIONS = """Search index of ~108,000 US public datasets (data.gov federal/state/city records, Census API tables,
city and state open data portals). Use it to FIND the right dataset; it does not return the data values themselves.
Typical flow: search_datasets -> pick the best fit -> get_dataset for columns and download/API links -> fetch the data.
Results carry provenance: fields marked rule:* were inferred by rules, not stated by the publisher.
If nothing fits, say so plainly. Never invent dataset names or URLs."""

server = MCPServer(name='civic-data-explorer', instructions=INSTRUCTIONS)

LEVELS = ['national', 'state', 'county', 'city', 'tract', 'block group', 'zip code', 'school district',
          'congressional district', 'metro area', 'neighborhood / ward', 'address / point']


def _compact(r, why):
    cy = r.get('coverage_years') or [None, None]
    out = {
        'id': r['id'],
        'title': r['display_title'],
        'publisher': r.get('publisher'),
        'covers': 'all states' if r.get('states') == ['US'] else (', '.join(r.get('states') or []) or 'unknown'),
        'levels': r.get('geo_levels') or [],
        'years': 'not listed by publisher' if not cy[0] else (str(cy[0]) if cy[0] == cy[1] else '%s-%s' % (cy[0], cy[1])),
        'freshness': r.get('freshness'),
        'access': ['not listed by publisher'] if r.get('access') == ['unknown'] else r.get('access'),
        'why': why,
    }
    if r.get('series_count', 1) > 1:
        out['grouped_files'] = r['series_count']
    if r.get('map_type'):
        out['map_data'] = r['map_type']
    if r.get('columns'):
        out['column_count'] = len(r['columns'])
    if r.get('contains'):
        out['contains'] = r['contains'][:8]
    if r.get('research_like'):
        out['note'] = 'Looks like data from a single research study, not an ongoing data series.'
    return out


@server.tool()
def search_datasets(query: str, state: str | None = None, level: str | None = None,
                    year_from: int | None = None, year_to: int | None = None, limit: int = 5) -> str:
    """Find US public datasets that can answer a question, in plain language.

    Args:
        query: What the data should be about, in everyday words, e.g. "asthma rates", "evictions",
            "restaurant inspections". Place, years and level can be in the query or in the filters.
        state: Two-letter state code to restrict results, e.g. "OH". National datasets that cover all
            states are still included.
        level: Geographic detail needed: national, state, county, city, tract, block group, zip code,
            school district, congressional district, metro area, neighborhood / ward, address / point.
        year_from: Earliest year the data should cover.
        year_to: Latest year the data should cover.
        limit: Number of results, 1 to 20 (default 5).

    Returns JSON: what the query was understood as, how many results filters removed, and ranked results
    with coverage, freshness, access type and why each matched. Use get_dataset(id) for details.
    """
    if level and level not in LEVELS:
        return json.dumps({'error': 'unknown level %r' % level, 'valid_levels': LEVELS})
    years = (year_from or 1900, year_to or 2026) if (year_from or year_to) else None
    ov = {'state': state.upper() if state else None, 'geo': level, 'years': years}
    p, hits, hidden = S.search(db, query, max(1, min(limit, 20)), 'hybrid', model(), ov)
    res = {
        'understood': {k: v for k, v in {'state': p['state'], 'level': p['geo'], 'years': p['years'],
                                          'wants_map_data': p['map'] or None}.items() if v},
        'hidden_by_filters': hidden,
        'results': [_compact(h['record'], h['why']) for h in hits],
    }
    if not hits:
        res['note'] = 'No matching datasets. Try broader words, drop a filter, or tell the user none was found.'
    return json.dumps(res, ensure_ascii=False)


@server.tool()
def get_dataset(id: str) -> str:
    """Full details for one dataset from search_datasets: description, coverage, columns, links and caveats.

    Args:
        id: The id from a search_datasets result, e.g. "dg:places-local-data-for-better-health-county-data".
    """
    row = db.execute('SELECT doc FROM records WHERE id = ?', (id,)).fetchone()
    if not row:
        return json.dumps({'error': 'no dataset with id %r; use an id from search_datasets' % id})
    r = json.loads(row[0])
    cy = r.get('coverage_years') or [None, None]
    cols = r.get('columns') or []
    out = {
        'id': r['id'],
        'title': r['display_title'],
        'original_title': r['title'] if r['title'] != r['display_title'] else None,
        'publisher': r.get('publisher'),
        'source': r['source'],
        'description': (r.get('description') or '')[:1500],
        'covers': r.get('states'),
        'levels': r.get('geo_levels'),
        'years': cy if cy[0] else None,
        'last_updated_year': r.get('last_modified_year'),
        'freshness': r.get('freshness'),
        'access': r.get('access'),
        'formats': r.get('formats'),
        'url': S.url_of(r),
        'map_data': r.get('map_type'),
        'grouped_files': r.get('series_count') if r.get('series_count', 1) > 1 else None,
        'example_files': r.get('series_examples') or None,
        'columns': [{k: v for k, v in {'field': c.get('field'), 'name': c.get('name'), 'description': c.get('description'),
                                        'type': c.get('type')}.items() if v} for c in cols[:60]] or None,
        'more_columns': max(0, len(cols) - 60) or None,
        'socrata_api': ('https://%s/resource/%s.json' % (r['socrata_domain'], r['socrata_id'])) if r.get('socrata_id') else None,
        'contains': (r.get('contains') or [])[:40] or None,
        'sample_rows': r.get('sample_rows'),
        'census_table': (r.get('census') or {}).get('table'),
        'census_universe': (r.get('census') or {}).get('universe'),
        'census_products': (r.get('census') or {}).get('products'),
        'provenance': r.get('derived'),
        'caveats': [c for c in [
            'Documents only (PDF or web page); may not contain downloadable data.' if 'documents_only' in (r.get('access') or []) else None,
            'Not updated in 3+ years.' if r.get('freshness') == 'stale' else None,
            'Census API: data values are fetched per variable from the API.' if r['source'] == 'census' else None,
        ] if c] or None,
    }
    return json.dumps({k: v for k, v in out.items() if v not in (None, [], {})}, ensure_ascii=False)


if __name__ == '__main__':
    server.run('stdio')
