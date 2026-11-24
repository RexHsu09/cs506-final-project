# Road Inventory EDA and Feature Quality

Statistical exploration of the 2022 MassDOT road inventory in the same 13 municipalities used
by the team's current geospatial pilot. This work extends Molly's initial road-data audit with
group comparisons, AADT provenance, predictor relationships and filtering effects. It does not
use crash labels, images, or teammates' local processed datasets.

## Read the results

- `notebooks/02_eda.ipynb`: English notebook with executed tables, figures and interpretation.
- `reports/road_eda_report.html`: standalone English report, including embedded figures.
- `reports/tables/`: machine-readable summaries with explicit denominators.
- `figures/`: six exported research figures.

The HTML report opens without installing Python. The notebook is the authoritative analysis.

## Reproduce

Use Python 3.12 and an isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-eda.txt
python scripts/download_roads.py
python scripts/run_eda.py
```

Alternatively, choose this environment in Jupyter or VS Code and run `notebooks/02_eda.ipynb`
from top to bottom. The downloader requires internet only for uncached source requests. It needs
no Mapillary token or other credentials. Analysis runs offline after a complete download.

## Data and identifiers

The fixed municipality list is Boston, Brookline, Cambridge, Dedham, Everett, Milton, Needham,
Newton, Quincy, Revere, Somerville, Watertown and Winthrop. Geographic selection uses the
inventory's reported `City` field, mapped to the official municipal IDs. Records are not clipped
to boundary polygons or chosen by crash outcomes. Boundary features are saved as a reference.

- Public source: [MassDOT Road Inventory 2022, layer 8](https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer/8).
- [Municipality reference](https://services8.arcgis.com/o4UVke7qqC8oNJ7j/ArcGIS/rest/services/Massachusetts_Towns_General_Coast/FeatureServer/0).
- [Road inventory dictionary](https://www.mass.gov/doc/road-inventory-data-dictionary/download). The retrieved PDF is labelled **2024**. It supports shared field/length/width definitions; categorical mappings come from the actual **2022 layer metadata**.
- [MAPC Local Access field definitions](https://localaccess.mapc.org/assets/pdfs/LocalAccess_User_Guide.pdf), page 10, for MassDOT posted-speed units.
- [Molly's acquisition and audit](https://github.com/RexHsu09/cs506-final-project/blob/877c5e15b620cfd811aee43b33d9045310cd41f7/notebooks/01_road_inventory_cleaning.ipynb).
- [Chun's municipality selection](https://github.com/RexHsu09/cs506-final-project/blob/a48cc6b96157cd000e4e5ef1f02c28dd9f466366/01_raw_data_preprocessing.ipynb).

`data/raw/manifest.json` records the selection, requested object IDs, acquisition times and file
checksums. Downloaded batches preserve selected original attributes and source geometry. This
fresh extract is not Molly's October snapshot. Do not assume equivalence across extracts without
checking IDs and values. API requests are not an atomic database snapshot.

Outputs under `data/processed/` include `roads_eda.csv`, `roads_screened_out.csv`, and
`segment_id_crosswalk.csv`. `segment_id` equals the source `GlobalID`; `segment_id_objectid`
equals `2022:OBJECTID`. Both original identifiers remain available for a reviewed crosswalk.
One row is one original inventory record. No splitting, merging, imputation, or geometric
deduplication is performed. Length totals are inventoried line lengths, not unique centerline mileage.

## Analysis choices requiring team review

- The road screen excludes invalid/empty/zero-length geometries and `Facility = 12`.
  Unknown facility and functional-class values stay in the provisional EDA population.
- Reported positive AADT remains available even if its reference year is unknown.
  Derivation code 13 explicitly denotes a default. AADT 1154 with missing derivation is only
  a **suspected default**; excluding it is a sensitivity assumption, not an official coding rule.
- Posted speed 99 is flagged and excluded from the working summary as a suspected special value.
  Source values remain unchanged. Opposing-direction zeros are not globally recoded.
- Complete-case filters are alternatives for examining sample composition, not final
  model-inclusion decisions. Any future imputation or feature selection must use training data.
- Predictor correlations do not demonstrate crash prediction or causal effects.

## Sharing

This EDA update is maintained on the team's eda branch.
Keep `data/`, `.venv/`, `.cache/` and credentials out of Git. The source files are the notebook, two scripts, requirements, this guide and `.gitignore`.
Selected figures and summaries can accompany them. Share the original snapshot separately
when teammates need byte-identical reproduction.

AI assistance: OpenAI Codex assisted with the code and draft interpretations. Review the
definitions and findings before submission.
