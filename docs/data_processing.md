# Boston Road Inventory: Data Preparation

## Scope and status

This preliminary preparation covers 22,627 Boston records from the
MassDOT Road Inventory 2022 layer, filtered by City = 35.

Boston is the initial working area, not the finalized Greater Boston cohort.
This output is not yet a final modeling dataset.

## Source

https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer/8

Records were downloaded in ordered batches of up to 1,000.
All source attributes and returned geometries were retained.

The downloaded count matched the API count, and OBJECTIDs were unique.

## Files

- Notebook: `notebooks/01_data_cleaning.ipynb`
- Raw snapshot: `data/raw/boston_roads_2022_raw_20261016T170046534733Z.json`
- Preliminary outputs: `data/processed/boston_preliminary_<timestamp>/`

Each output folder contains:

- `roads_preliminary_attributes.csv`: source attributes and added preparation fields.
- `source_features_esri.json`: source records, geometries, and metadata; not GeoJSON.
- `quality_flags.csv`: counts and percentages of flagged records.

Datasets are excluded from Git. Teammates need the raw snapshot through
an agreed shared location, or must run the acquisition section.

## Environment and execution

Used Python 3.12.3 and pandas 2.2.2. API acquisition also requires requests.

To reuse the saved snapshot:
1. Place the raw JSON in `data/raw/`.
2. Run the local-file loading cell.
3. Run the preliminary preparation and export cell.

The notebook currently includes exploratory cells. Do not use Run All
unless you intend to repeat the API download.

## Preparation performed

- Created `segment_id` by copying `GlobalID`.
- Confirmed that segment_id is present and unique in this snapshot.
- Trimmed leading and trailing whitespace from street names.
- Converted blank street names to missing values in `street_name_clean`.
- Preserved original source fields.
- Added missing-value and basic geometry-completeness flags.
- Retained all 22,627 records without imputation or eligibility filtering.

## Initial findings

| Check | Records | Percent |
| --- | ---: | ---: |
| Missing or blank street name | 2,800 | 12.37% |
| Missing AADT | 4,206 | 18.59% |
| Missing AADT measurement year | 14,104 | 62.33% |
| Missing facility type | 3,288 | 14.53% |
| Missing or insufficient geometry paths | 35 | 0.15% |

Flags may overlap and should not be added together.

Among the records, 9,899 have AADT but lack its measurement year.
Reported AADT years range from 2009 to 2021; none exceed 2022.
A 2022 inventory snapshot does not imply a 2022 traffic measurement.

## Limitations and pending decisions

- Verify field units and special codes against the official data dictionary.
- Confirm the meanings of Speed_Lim values 0 and 99.
- Agree on eligible facility types and treatment of unknown facility types.
- Perform full geometry validation and spatial duplicate checks.
- Resolve the 35 records that failed basic geometry completeness checks.
- Align segment identifiers with teammates before joining datasets.
- Finalize Greater Boston coverage and data-sharing arrangements.

The geometry check only tests for at least one path containing two points.
Passing it does not establish full geometric validity.

Missing-value flags currently identify null values and blank street names;
they do not resolve undocumented special codes.

Crash matching, crash labels, image matching, and modeling have not been
completed in this notebook. Any model imputation must be fitted using
training data only.