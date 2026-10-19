# Boston Road Inventory: Data Preparation

## Scope and status

This initial preparation covers 22,627 Boston records from the
MassDOT Road Inventory 2022 layer, filtered by City = 35.

Boston is the initial working area, not the finalized Greater Boston cohort.
These outputs are provisional and are not a final modeling dataset.

Initial cleaning retained 22,592 records and set aside 35 records
for geometry review. No final facility-eligibility filter was applied.

## Source

https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer/8

Records were downloaded in ordered batches of up to 1,000.
The downloaded count matched the API count, and OBJECTIDs were unique.

The original saved snapshot is preserved for reproducibility.
A new API download may differ if the service has changed.

## Files

- Notebook: `notebooks/01_road_inventory_cleaning.ipynb`
- Raw snapshot: `data/raw/boston_roads_2022_raw_20261016T170046534733Z.json`
- Current output folder: `data/processed/boston_cleaning_20261019T012716618731Z/`

Key output files:

| File | Purpose |
| --- | --- |
| `roads_initial_clean_attributes.csv` | Attributes and preparation fields for 22,592 retained records; excludes geometry |
| `roads_needing_geometry_review.csv` | 35 records set aside for geometry review, with review reasons |
| `retained_source_features_esri.json` | Retained source features, including geometry and source metadata; not GeoJSON |
| `field_definitions.json` | Field definitions and available domain information |

Additional CSV reports summarize missing values, identifiers, numeric
checks, AADT completeness, facility distribution, and basic geometry checks.

Datasets are excluded from Git under the current project setup.
Agree on a shared location for the original snapshot and processed outputs.

## Environment and execution

The previously recorded environment used Python 3.12.3 and pandas 2.2.2.
API acquisition also requires requests.

To reuse the saved snapshot:

1. Place the original raw JSON in `data/raw/`.
2. Set `raw_path` in section 1 to the saved snapshot.
3. Run sections 1–3 to load the data, inspect metadata, and audit quality.
4. Run section 4 to perform initial cleaning.
5. Run section 5 to export the results.
6. Review section 6 for findings, limitations, and pending decisions.

Keep `DOWNLOAD_RAW = False` in the optional acquisition appendix
unless intentionally acquiring a new extract.

Each export creates a new timestamped output folder.
The original raw JSON is not modified.

## Quality audit

The audit examined:

- Missing values across source attributes.
- Missing and repeated identifiers.
- Selected numeric fields for non-numeric values, zeros,
  negative values, and ranges.
- AADT and measurement-year completeness.
- AADT measurement-year distribution.
- Facility-type distribution.
- Basic geometry-path completeness and missing `Shape__Length`.

The audit itself did not remove or impute records.
Repeated `Rd_Seg_ID` values were not treated as proof of duplicate roads.

## Initial cleaning performed

- Created `segment_id` by copying `GlobalID`.
- Confirmed that the identifier is present and unique in the input snapshot.
- Preserved original source fields.
- Created `street_name_clean` by trimming leading and trailing whitespace
  and converting blank street names to missing values.
- Set aside 35 records that failed the basic paths check,
  retaining review reasons.
- Added missing-value flags to retained records.
- Exported retained attributes, retained source features,
  review records, field definitions, and audit reports.

No missing-value imputation was performed.
Zeros and other special values were not automatically recoded.
No records were removed solely because a nonessential attribute was missing.

## Audit findings

All counts and percentages below refer to the original 22,627 records,
before setting aside geometry-review records.

| Check | Records | Percent |
| --- | ---: | ---: |
| Missing or blank street name | 2,800 | 12.37% |
| Missing AADT | 4,206 | 18.59% |
| Missing AADT measurement year | 14,104 | 62.33% |
| Missing `Speed_Lim` | 13,597 | 60.09% |
| Missing `Speed` | 22,363 | 98.83% |
| Missing facility type | 3,288 | 14.53% |
| Failed basic paths check | 35 | 0.15% |

Flags may overlap and should not be added together.

Additional observations:

- `OBJECTID` and `GlobalID` were complete and unique.
- 9,899 records had AADT but lacked its measurement year.
- Known AADT measurement years ranged from 2009 to 2021.
- A 2022 inventory does not imply that all traffic counts were measured in 2022.
- The 35 records failing the basic paths check also lacked `Shape__Length`.
- Selected numeric checks found no non-numeric or negative values.
- Lane counts, surface width, and speed limits included zeros;
  `Speed_Lim` also included 99. Their interpretation remains pending.
- The metadata domain defines `F_Class = 0` as Local,
  so it must not be treated as missing solely because it is zero.

## Limitations and pending decisions

- Verify field units and special codes against the official data dictionary.
- Confirm the meanings of `Speed_Lim` values 0 and 99.
- Extend numeric checks to opposing-direction fields,
  including `Opp_Lanes` and `Op_Dir_SL`.
- Validate categorical codes against metadata domains.
- Agree on eligible facility types and treatment of unknown facility types.
- Perform full geometry validation and spatial duplicate checks.
- Investigate the 35 geometry-review records.
- Align segment identifiers with teammates before joining datasets.
- Finalize Greater Boston coverage and data-sharing arrangements.

The basic paths check only tests for at least one path containing
two points. Passing it does not establish full geometric validity.

Missing-value checks do not resolve undocumented special codes.

Crash matching, crash labels, image matching, and modeling have not
been completed in this notebook.

Any model imputation must be fitted using training data only.
AADT and segment length approximate traffic exposure; predicting
at least one crash is not equivalent to estimating a crash rate per traveler.