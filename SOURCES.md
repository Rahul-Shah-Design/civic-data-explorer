# Data Sources

Checklist of sources for the index. Checked = harvested and in the current index (Nov 25, 2026).
Many federal agencies also publish into data.gov, so before harvesting a new source, check how much of it is already in the index.

## Harvested

- [x] **data.gov catalog**: federal agencies plus the state, city, county and university records data.gov harvests. 533,970 records → 99,581 search results.
- [x] **Census API catalog**: 555 dataset families, indexed as 7,848 tables (ACS, Decennial, SAIPE, County Business Patterns, etc.).
- [x] **Socrata portals** (mainly for column dictionaries; 91% overlap with data.gov):
  - [x] NYC (data.cityofnewyork.us)
  - [x] Chicago (data.cityofchicago.org)
  - [x] Los Angeles (data.lacity.org)
  - [x] CDC (data.cdc.gov)
  - [x] New York State (data.ny.gov)
  - [x] Texas (data.texas.gov)
  - [x] Washington State (data.wa.gov)
  - [x] Connecticut (data.ct.gov)
  - [x] Maryland (opendata.maryland.gov)
  - [x] Pennsylvania (data.pa.gov)
  - [x] Colorado (data.colorado.gov)
  - [x] Montgomery County, MD (data.montgomerycountymd.gov)
  - [ ] San Francisco: only 4 datasets returned; portal appears to have moved
  - [ ] Seattle: 0 returned; portal appears to have moved
  - [ ] Austin: 0 returned; portal appears to have moved

## Next: local and state portals

- [ ] All remaining Socrata portals (expand from the 15 above)
- [ ] ArcGIS Hub (many cities and counties publish only here)
- [ ] State CKAN portals not harvested by data.gov
- [ ] OpenDataSoft and other portal platforms

## Next: health

- [ ] CMS Provider Data / Care Compare (hospital star ratings, patient surveys; not on data.gov)
- [ ] data.cms.gov (Medicare utilization, spending)
- [ ] CDC WONDER (mortality, natality; query system)
- [ ] HRSA Data Warehouse (health centers, shortage areas)
- [ ] openFDA (drug and device adverse events, recalls)

## Next: statistical series (organized by series, not datasets)

- [ ] BLS (employment, wages, prices)
- [ ] BEA (GDP, personal income by county)
- [ ] FRED (economic series, aggregated)
- [ ] EIA (energy)
- [ ] USDA ERS and NASS Quick Stats (food, agriculture)

## Next: education

- [ ] NCES (Common Core of Data, IPEDS)
- [ ] College Scorecard
- [ ] Civil Rights Data Collection
- [ ] Urban Institute Education Data API (non-government; aggregates the above)

## Next: housing, safety, transportation, elections

- [ ] HUD User (Fair Market Rents, CHAS)
- [ ] FBI Crime Data Explorer
- [ ] Bureau of Justice Statistics
- [ ] Bureau of Transportation Statistics, NHTSA FARS (traffic deaths)
- [ ] FEC (campaign finance)

## Deliberately excluded for now ("coming soon")

- [ ] Research science data (NASA planetary, NOAA surveys and cruises, paleoclimate, chemistry, patents). Flagged in the data, easy to re-include.
- [ ] Imagery, raster and tile series (aerial photos, satellite, lidar and elevation tiles)
- [ ] Broken link checking
