# CS506 statistical EDA: Bryan model review

This is an extension of the statistical EDA using Bryan's supplied Boston model tables.
It preserves his source tables, crash labels, modeling cohort, and frozen spatial split.
English results are in `reports/model_review.html` and the executed notebook
`notebooks/07_statistical_model_review.ipynb`.

Measured results: archived logistic AP **0.3524**; the training-CV-selected variant,
`separate_lr_raw_C1`, AP **0.3698** on the same 5,368 test segments. Mean training-block
CV AP increased from **0.3431** to **0.3847**. The paired 16-test-block bootstrap interval
for the AP difference is **[0.0056, 0.0321]**. This is promising exploratory evidence,
not confirmation on a new untouched test set. Raw and screened AADT variants were close
in training CV; this does not establish that default AADT values are accurate.

The original raw-AADT exposure is intentional. The review checks AADT availability,
clarifies the `traffic_counted` flag, explores segment length, and compares nine predefined
models using only training-block cross-validation for selection. The existing test comparison
is exploratory because the team has previously inspected this test set.

## Reproduce

Use Python 3.12 (the executed version) and a virtual environment. From this directory:

```sh
python -m pip install -r requirements.txt
python scripts/prepare_inputs.py /path/to/bryan_model_files.zip
python scripts/model_review.py
```

Alternatively, select your environment's Python kernel and run every cell of
`notebooks/07_statistical_model_review.ipynb`. The notebook calls the same functions;
it recomputes cross-validation, freezes the selected configuration, evaluates the selected
model, and rebuilds the report. No Git checkout, API key, or database is required.

The expected archive SHA-256 is
`de21dc73d63bbe0f8e08c270281407a3cb94a8828f3c59af8c010466abc549d3`.
The input preparer checks the archive and refuses to overwrite different existing inputs.
The analysis rechecks all seven CSV hashes on every run.

## Outputs

- `reports/model_review.html`: standalone English report with embedded plots.
- `reports/tables/`: aggregated EDA, fold results, test metrics, and descriptive subgroups.
- `reports/experiment_protocol.json`: candidate grid and prespecified selection rule.
- `reports/selection_freeze.json`: chosen model, timestamp, and input/fold/CV hashes,
  written before the selected model's test evaluation.
- `reports/model_review_summary.json`: machine-readable results and environment versions.
- `reports/figures/`: exportable scientific figures.
- `data/processed/`: local keyed EDA cohort, fold assignments, predictions, bootstrap draws.
  These row-level outputs and all original data are ignored by Git and excluded from the sharing ZIP.

The freeze file records this run; it cannot make the previously explored test set pristine.
GroupKFold separates original 2 km blocks without a spatial buffer. The paired block bootstrap
has only 16 test blocks and does not capture all sources of uncertainty.

## Integration

These are proposed additional files, not a replacement for Bryan's notebook or the earlier road EDA.
Notebook number 07 should be checked against the team's current file names before merging.
Retain the repository's existing `.gitignore`; add the relevant local-data/cache rules if absent.
Do not replace unrelated team ignore rules with this standalone package's file.

The source `traffic_counted` column is preserved. The EDA-only alias `aadt_available_screened`
states its actual formula; a verified direct measurement requires the source derivation metadata.
No street-view detections are used, no imagery benefit is claimed, and upstream spatial matching
cannot be independently reconstructed from these CSVs alone.

Prepared with AI coding assistance. All numerical claims come from executed analysis of the
supplied data; the analysis does not contain synthetic observations.
