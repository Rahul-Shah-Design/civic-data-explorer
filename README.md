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
