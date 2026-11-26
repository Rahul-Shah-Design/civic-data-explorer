# Open Data Finder

Plain-language search for US public datasets, for people and AI agents. Think data.norge.no for the US.

Status: one-time metadata harvest and cleanup (no automatic refresh).

## Rebuild the data (about 10 minutes, roughly 5 GB of disk)

```bash
mkdir -p raw/census_groups clean
# Census API catalog + table lists
curl -s -o raw/census_catalog.json https://api.census.gov/data.json
python3 -I scripts/census_groups.py raw/census_catalog.json raw/census_groups
# data.gov catalog (resumable; rerun until it prints DONE)
python3 -I scripts/datagov_harvest.py raw/datagov.jsonl 540
python3 -I scripts/profile_datagov.py raw/datagov.jsonl
# Cleanup and grouping
python3 -I scripts/clean_datagov.py raw/datagov.jsonl clean/datagov_flagged.jsonl
python3 -I scripts/group_pass2.py clean/datagov_flagged.jsonl clean/datagov_grouped.jsonl
# Socrata portals (column dictionaries)
python3 -I scripts/socrata_harvest.py raw/socrata.jsonl data.cityofnewyork.us,data.cityofchicago.org,data.sfgov.org,data.seattle.gov,data.lacity.org,data.austintexas.gov,data.cdc.gov,data.ny.gov,data.texas.gov,data.wa.gov,data.ct.gov,opendata.maryland.gov,data.pa.gov,data.colorado.gov,data.montgomerycountymd.gov

# Category values (Measure/Topic/Cause columns) for Socrata datasets, used by enrich.py
python3 -I scripts/fetch_values.py index/enriched.jsonl raw/socrata_values.jsonl
# Merge into one record per search result, then rule-based enrichment
python3 -I scripts/merge.py .
python3 -I scripts/enrich.py .
```

Output: `index/enriched.jsonl`, one record per search result with `display_title`, `states`, `geo_levels`, `coverage_years`, `map_type`, `freshness`, `access`, `columns` and `search_text`. Every derived field records its rule in `derived`.

## Results of the Nov 25, 2026 harvest
- data.gov: 533,970 records, 401,836 kept after excluding duplicates, research science, imagery and FAQ pages, grouped into 99,581 search results.
- Census API: 555 dataset families, 15,088 tables.
- Socrata: 10,861 datasets from 15 portals; 91% already on data.gov, so mainly used for column dictionaries.
- Merged index: 108,507 search results (99,581 data.gov, 7,848 Census tables, 1,078 Socrata-only). 8,734 have column dictionaries.

`prototype/index.html` is a fake-data clickable prototype of the search experience.

## Build the search index (run on a laptop, not a 2-core cloud box)

```bash
pip install fastembed sqlite-vec
python3 scripts/build_index.py index/enriched.jsonl index/search.db
```

Resumable: if it stops, run the same command again. Output is one SQLite file with the records, a keyword (FTS5) index and 384-dimension bge-small embeddings (sqlite-vec).

## Search

```bash
python scripts/search.py index/search.db "asthma rates by county in Ohio"
python scripts/search.py index/search.db "evictions in chicago since 2020" --n 5 --json   # agent-friendly output
python scripts/search.py index/search.db "..." --mode keyword   # or vector, hybrid (default)
```

## Use it from Claude Desktop (MCP server)

1. `pip install -r requirements.txt`
2. Open Claude Desktop → Settings → Developer → Edit Config, and add (Windows paths shown; use your own):

```json
{
  "mcpServers": {
    "civic-data-explorer": {
      "command": "C:\\Users\\YOU\\AppData\\Local\\Programs\\Python\\Python312\\python.exe",
      "args": [
        "C:\\path\\to\\civic-data-explorer\\scripts\\mcp_server.py",
        "C:\\path\\to\\civic-data-explorer\\index\\search.db"
      ]
    }
  }
}
```

3. Fully quit and reopen Claude Desktop. The tools `search_datasets` and `get_dataset` appear under the tools menu.

## Update an existing index without rebuilding

```bash
python scripts/update_index.py index/search.db index/patch.jsonl
```
Replaces changed records and re-embeds only those whose text changed.

## Web UI (local)

```bash
python scripts/web.py index/search.db    # open http://localhost:8000
```
Same search as the MCP tools, plus a JSON API at `/api/search?q=...` and `/api/dataset/{id}` (docs at `/docs`).
