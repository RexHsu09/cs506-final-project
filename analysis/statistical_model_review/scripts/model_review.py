"""Statistical EDA and bounded model comparison for Bryan's frozen Boston cohort.

All source tables remain unchanged. Candidate selection uses training blocks only.
Run from the project root: python scripts/model_review.py
"""
from pathlib import Path
import base64
import hashlib
import html
import json
import os
import platform
import sys
from datetime import datetime, timezone

# A CPU cap also avoids unsupported physical-core discovery in restricted runtimes.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import MissingIndicator, SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/bryan"
TABLES = ROOT / "reports/tables"
FIGURES = ROOT / "reports/figures"
LOCAL = ROOT / "data/processed"
SEED = 506
SELECTION_MIN_GAIN = 0.005
BLUE, ORANGE, GREEN, GRAY = "#2563a6", "#d66b27", "#23816b", "#667085"


def setup():
    for directory in [TABLES, FIGURES, LOCAL]:
        directory.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(value, path):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def load_data():
    setup()
    manifest = json.loads((RAW / "manifest.json").read_text())
    for name, metadata in manifest["files"].items():
        assert sha256(RAW / name) == metadata["sha256"], f"Input changed: {name}"
    names = ["roads_initial_clean_attributes", "model_features", "segment_labels",
             "segment_split", "model_a_test_predictions", "model_a_results"]
    tables = {name: pd.read_csv(RAW / f"{name}.csv", low_memory=False) for name in names}
    for name, table in tables.items():
        if "segment_id" in table:
            assert table.segment_id.notna().all() and table.segment_id.is_unique, name
    features, split = tables["model_features"], tables["segment_split"]
    cohort = features.loc[features.road_type.ne("Unknown")].copy()
    assert set(cohort.segment_id) == set(split.segment_id)
    cohort = cohort.merge(split, on="segment_id", how="left", validate="one_to_one")
    road_columns = ["segment_id", "AADT", "aadt_clean", "AADT_Deriv", "AADT_Year",
                    "Length", "Shape__Length", "aadt_is_default"]
    cohort = cohort.merge(tables["roads_initial_clean_attributes"][road_columns],
                          on="segment_id", how="left", validate="one_to_one")
    labels = tables["segment_labels"].set_index("segment_id")
    assert np.array_equal(cohort.had_crash, cohort.segment_id.map(labels.had_crash))
    assert set(cohort.split) == {"train", "test"}
    assert set(cohort.loc[cohort.split.eq("train"), "block"]).isdisjoint(
        cohort.loc[cohort.split.eq("test"), "block"])
    assert np.allclose(cohort.exposure, cohort.AADT * cohort.Length, equal_nan=True)
    assert (cohort.traffic_counted == cohort.aadt_clean.notna().astype(int)).all()
    assert (cohort.Shape__Length > 0).all() and cohort.Shape__Length.notna().all()
    assert cohort.had_crash.isin([0, 1]).all()
    assert cohort[["connections", "traffic_counted"]].notna().all().all()
    for col in ["AADT", "aadt_clean"]:
        assert (cohort[col].dropna() >= 0).all()
    cohort["log_exposure"] = np.log1p(cohort.exposure)
    cohort["log_length_m"] = np.log1p(cohort.Shape__Length)
    cohort["log_aadt_raw"] = np.log1p(cohort.AADT)
    cohort["log_aadt_screened"] = np.log1p(cohort.aadt_clean)
    cohort["connections_x_arterial"] = cohort.connections * cohort.road_type.str.contains("arterial")
    # Honest alias in the EDA copy. Keep Bryan's original column for exact reproduction.
    cohort["aadt_available_screened"] = cohort.traffic_counted
    cohort["crash_count"] = cohort.segment_id.map(labels.crash_count)
    archived = tables["model_a_test_predictions"]
    test = cohort.loc[cohort.split.eq("test")]
    assert set(test.segment_id) == set(archived.segment_id)
    aligned = archived.set_index("segment_id").loc[test.segment_id]
    assert np.array_equal(test.had_crash.to_numpy(), aligned.had_crash.to_numpy())
    assert np.array_equal(test.road_type.to_numpy(), aligned.road_type.to_numpy())
    tables.update(cohort=cohort, manifest=manifest)
    return tables


def run_audit(data):
    d = data["cohort"]
    summary = d.groupby("split").agg(
        segments=("segment_id", "size"), positive_segments=("had_crash", "sum"),
        positive_share=("had_crash", "mean"), spatial_blocks=("block", "nunique"),
        raw_aadt_missing_share=("AADT", lambda x: x.isna().mean()),
        screened_aadt_missing_share=("aadt_clean", lambda x: x.isna().mean()))
    summary.to_csv(TABLES / "cohort_audit.csv")
    d["aadt_status"] = np.select([d.AADT.isna(), d.aadt_clean.isna()],
        ["Missing raw AADT", "Masked by team screening"], default="Available after screening")
    availability = d.groupby(["split", "aadt_status"]).agg(
        segments=("segment_id", "size"), positive_segments=("had_crash", "sum"),
        positive_share=("had_crash", "mean"), median_length_m=("Shape__Length", "median"))
    availability.to_csv(TABLES / "aadt_availability.csv")
    by_road = d.groupby(["split", "road_type"]).agg(
        segments=("segment_id", "size"), positive_segments=("had_crash", "sum"),
        positive_share=("had_crash", "mean"), median_length_m=("Shape__Length", "median"),
        raw_aadt_missing_share=("AADT", lambda x: x.isna().mean()),
        screened_aadt_missing_share=("aadt_clean", lambda x: x.isna().mean()))
    by_road.to_csv(TABLES / "road_type_eda.csv")
    # Fixed descriptive bins, not chosen to maximize separation in the outcomes.
    d["length_bin_m"] = pd.cut(d.Shape__Length, [0, 25, 50, 100, 200, 500, np.inf],
        labels=["0–25", "25–50", "50–100", "100–200", "200–500", ">500"])
    lengths = d.groupby(["split", "length_bin_m"], observed=True).agg(
        segments=("segment_id", "size"), positive_segments=("had_crash", "sum"),
        positive_share=("had_crash", "mean"))
    lengths.to_csv(TABLES / "length_eda.csv")
    derivations = d.groupby(["split", "aadt_available_screened", "AADT_Deriv"], dropna=False).size()
    derivations.rename("segments").to_csv(TABLES / "aadt_derivation_codes.csv")
    attrition = pd.DataFrame([
        ("Road attributes supplied", len(data["roads_initial_clean_attributes"])),
        ("Bryan modeling features supplied", len(data["model_features"])),
        ("Excluded Unknown road type (existing team choice)",
         int(data["model_features"].road_type.eq("Unknown").sum())),
        ("Frozen modeling cohort", len(d)),
    ], columns=["stage", "segments"])
    attrition.to_csv(TABLES / "cohort_flow.csv", index=False)
    audit = {"cohort_rows": len(d), "road_rows": len(data["roads_initial_clean_attributes"]),
             "feature_rows": len(data["model_features"]), "unknown_excluded": int(
                 data["model_features"].road_type.eq("Unknown").sum()),
             "exposure_formula_verified": True, "traffic_flag_formula_verified": True,
             "unique_ids_and_target_agreement_verified": True,
             "train_test_blocks_disjoint": True,
             "shape_length_unit": "meters", "source_Length_unit": "miles",
             "split_summary": summary.reset_index().to_dict("records")}
    save_json(audit, ROOT / "reports/data_audit.json")
    d.to_csv(LOCAL / "eda_model_cohort.csv", index=False)
    return audit


def candidate_configs():
    configs = [{"name": "original_lr", "family": "original", "aadt": "raw", "C": 1.0}]
    for source in ["raw", "screened"]:
        for c in [0.1, 1.0]:
            configs.append({"name": f"separate_lr_{source}_C{c:g}", "family": "separate_lr",
                            "aadt": source, "C": c})
        for leaves in [7, 15]:
            configs.append({"name": f"boost_{source}_{leaves}", "family": "boost",
                            "aadt": source, "max_leaf_nodes": leaves})
    return configs


def build_model(config):
    if config["family"] == "original":
        inputs = ColumnTransformer([
            ("fill", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()),
             ["log_exposure", "surface_wd_clean"]),
            ("missing", MissingIndicator(features="all"), ["log_exposure", "surface_wd_clean"]),
            ("scale", StandardScaler(), ["connections", "connections_x_arterial"]),
            ("keep", "passthrough", ["traffic_counted"]),
            ("onehot", OneHotEncoder(drop=["Local", "both"], handle_unknown="ignore"),
             ["road_type", "sidewalks"])], verbose_feature_names_out=False)
        return make_pipeline(inputs, LogisticRegression(max_iter=1000, C=config["C"]))
    numeric = ["log_length_m", f"log_aadt_{config['aadt']}", "surface_wd_clean",
               "connections", "connections_x_arterial"]
    categorical = ["road_type", "sidewalks"]
    if config["family"] == "separate_lr":
        inputs = ColumnTransformer([
            ("numeric", make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                                       StandardScaler()), numeric),
            ("missing", MissingIndicator(features="all"), numeric),
            ("available", "passthrough", ["aadt_available_screened"]),
            ("categories", OneHotEncoder(drop="first", handle_unknown="ignore",
                                         sparse_output=False), categorical)])
        return make_pipeline(inputs, LogisticRegression(C=config["C"], max_iter=1000))
    inputs = ColumnTransformer([
        ("numeric", "passthrough", numeric + ["aadt_available_screened"]),
        ("categories", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical)])
    # No random internal early-stopping split: training/validation separation is by block.
    classifier = HistGradientBoostingClassifier(
        max_leaf_nodes=config["max_leaf_nodes"], max_iter=150, learning_rate=0.06,
        min_samples_leaf=40, l2_regularization=5.0, early_stopping=False, random_state=SEED)
    return make_pipeline(inputs, classifier)


def run_cross_validation(data):
    train = data["cohort"].loc[lambda x: x.split.eq("train")].reset_index(drop=True)
    configs = candidate_configs()
    protocol = {"candidate_configs": configs, "folds": 4, "group": "original 2 km block",
                "selection_metric": "unweighted mean fold average precision",
                "selection_rule": "highest mean CV AP; retain original unless improvement >= 0.005",
                "threshold": SELECTION_MIN_GAIN,
                "test_role": "fixed exploratory comparison after selection; already explored by team",
                "archive_sha256": data["manifest"]["archive_sha256"]}
    save_json(protocol, ROOT / "reports/experiment_protocol.json")
    folds = list(GroupKFold(n_splits=4).split(train, train.had_crash, groups=train.block))
    assignments = train[["segment_id", "block"]].copy()
    assignments["validation_fold"] = -1
    for fold, (fit_idx, valid_idx) in enumerate(folds, 1):
        fit, valid = train.iloc[fit_idx], train.iloc[valid_idx]
        assert set(fit.block).isdisjoint(valid.block)
        assert fit.had_crash.nunique() == valid.had_crash.nunique() == 2
        assignments.loc[valid_idx, "validation_fold"] = fold
    assert assignments.validation_fold.ge(1).all()
    assignments.to_csv(LOCAL / "training_fold_assignments.csv", index=False)
    oof = train[["segment_id", "block", "had_crash"]].copy()
    results = []
    with threadpool_limits(limits=2):
        for config in configs:
            predictions = np.full(len(train), np.nan)
            for fold, (fit_idx, valid_idx) in enumerate(folds, 1):
                fit, valid = train.iloc[fit_idx], train.iloc[valid_idx]
                model = build_model(config).fit(fit, fit.had_crash)
                score = model.predict_proba(valid)[:, 1]
                predictions[valid_idx] = score
                results.append({"candidate": config["name"], "fold": fold,
                    "fit_segments": len(fit), "validation_segments": len(valid),
                    "validation_blocks": valid.block.nunique(),
                    "prevalence": valid.had_crash.mean(),
                    "average_precision": average_precision_score(valid.had_crash, score),
                    "brier": brier_score_loss(valid.had_crash, score)})
            assert np.isfinite(predictions).all()
            oof[config["name"]] = predictions
            print(f"CV finished: {config['name']}", flush=True)
    detail = pd.DataFrame(results)
    detail.to_csv(TABLES / "cv_fold_results.csv", index=False)
    summary = detail.groupby("candidate", sort=False).agg(
        mean_cv_ap=("average_precision", "mean"), sd_cv_ap=("average_precision", "std"),
        min_cv_ap=("average_precision", "min"), max_cv_ap=("average_precision", "max"),
        mean_cv_brier=("brier", "mean"))
    summary["pooled_oof_ap"] = [average_precision_score(train.had_crash, oof[name])
                                for name in summary.index]
    baseline = float(summary.loc["original_lr", "mean_cv_ap"])
    summary["delta_cv_ap_vs_original"] = summary.mean_cv_ap - baseline
    summary = summary.sort_values("mean_cv_ap", ascending=False, kind="stable")
    summary.to_csv(TABLES / "cv_summary.csv")
    oof.to_csv(LOCAL / "training_oof_predictions.csv", index=False)
    return summary


def freeze_selection(data, cv):
    winner = cv.index[0]
    chosen = winner if float(cv.loc[winner, "delta_cv_ap_vs_original"]) >= SELECTION_MIN_GAIN else "original_lr"
    config = next(c for c in candidate_configs() if c["name"] == chosen)
    freeze = {"selected": config, "cv_winner": winner,
              "chosen_mean_cv_ap": float(cv.loc[chosen, "mean_cv_ap"]),
              "original_mean_cv_ap": float(cv.loc["original_lr", "mean_cv_ap"]),
              "minimum_cv_gain": SELECTION_MIN_GAIN,
              "selected_at_utc": datetime.now(timezone.utc).isoformat(),
              "archive_sha256": data["manifest"]["archive_sha256"],
              "protocol_sha256": sha256(ROOT / "reports/experiment_protocol.json"),
              "fold_assignments_sha256": sha256(LOCAL / "training_fold_assignments.csv"),
              "cv_summary_sha256": sha256(TABLES / "cv_summary.csv"),
              "split_sha256": sha256(RAW / "segment_split.csv"),
              "selection_did_not_use_test_scores": True}
    save_json(freeze, ROOT / "reports/selection_freeze.json")
    return freeze


def evaluate_selected(data, selection, bootstrap_draws=1000):
    assert selection == json.loads((ROOT / "reports/selection_freeze.json").read_text())
    assert selection["cv_summary_sha256"] == sha256(TABLES / "cv_summary.csv")
    d = data["cohort"]
    train, test = d.loc[d.split.eq("train")], d.loc[d.split.eq("test")].copy()
    archived = data["model_a_test_predictions"].set_index("segment_id").loc[test.segment_id]
    baseline = test.road_type.map(train.groupby("road_type").had_crash.mean())
    assert np.allclose(baseline, archived.baseline)
    with threadpool_limits(limits=2):
        original = build_model(candidate_configs()[0]).fit(train, train.had_crash)
        original_p = original.predict_proba(test)[:, 1]
        chosen = build_model(selection["selected"]).fit(train, train.had_crash)
        chosen_p = chosen.predict_proba(test)[:, 1]
    out = test[["segment_id", "block", "road_type", "had_crash", "aadt_status"]].copy()
    out["road_type_baseline"] = baseline.to_numpy()
    out["original_archived"] = archived.model_a.to_numpy()
    out["original_refit"] = original_p
    out["cv_selected"] = chosen_p
    out.to_csv(LOCAL / "test_predictions_comparison.csv", index=False)
    rows = []
    for name in ["road_type_baseline", "original_archived", "original_refit", "cv_selected"]:
        p = out[name].to_numpy()
        assert np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
        k = int(np.ceil(0.1 * len(out)))
        # Fixed top-10% description, not a threshold tuned on the test outcomes.
        top = np.argsort(-p, kind="stable")[:k]
        rows.append({"model": name, "test_ap": average_precision_score(out.had_crash, p),
                     "brier": brier_score_loss(out.had_crash, p),
                     "top_10pct_segments": k, "top_10pct_precision": out.had_crash.iloc[top].mean(),
                     "top_10pct_recall": out.had_crash.iloc[top].sum() / out.had_crash.sum()})
    metrics = pd.DataFrame(rows).set_index("model")
    metrics.to_csv(TABLES / "test_metrics.csv")
    archived_ap = float(metrics.loc["original_archived", "test_ap"])
    saved_rounded_ap = float(data["model_a_results"].loc[
        data["model_a_results"].model.eq("logistic regression"), "PR-AUC"].iloc[0])
    assert abs(archived_ap - saved_rounded_ap) <= 0.0005
    assert abs(float(metrics.loc["original_refit", "test_ap"]) - archived_ap) < 0.002
    # Paired cluster bootstrap: resample whole original test blocks, not individual roads.
    block_idx = [np.flatnonzero(out.block.eq(b).to_numpy()) for b in sorted(out.block.unique())]
    rng, differences = np.random.default_rng(SEED), []
    y = out.had_crash.to_numpy()
    for _ in range(bootstrap_draws):
        idx = np.concatenate([block_idx[i] for i in rng.integers(0, len(block_idx), len(block_idx))])
        if len(np.unique(y[idx])) < 2:
            continue
        differences.append(average_precision_score(y[idx], chosen_p[idx]) -
                           average_precision_score(y[idx], out.original_archived.to_numpy()[idx]))
    low, high = np.quantile(differences, [0.025, 0.975])
    pd.DataFrame({"ap_delta_vs_archived": differences}).to_csv(LOCAL / "paired_block_bootstrap.csv", index=False)
    strata = []
    for (kind, value), part in pd.concat([
        out.assign(stratum_type="AADT status", stratum_value=out.aadt_status),
        out.assign(stratum_type="Road type", stratum_value=out.road_type)]).groupby(
            ["stratum_type", "stratum_value"]):
        row = {"stratum_type": kind, "stratum": value, "segments": len(part),
               "positive_segments": int(part.had_crash.sum()), "prevalence": part.had_crash.mean()}
        for name in ["original_archived", "cv_selected"]:
            row[f"{name}_ap"] = (average_precision_score(part.had_crash, part[name])
                                     if part.had_crash.nunique() == 2 else np.nan)
        strata.append(row)
    pd.DataFrame(strata).to_csv(TABLES / "test_subgroups_descriptive.csv", index=False)
    result = {"selected_candidate": selection["selected"]["name"],
              "test_segments": len(out), "test_positive_segments": int(y.sum()),
              "test_prevalence": float(y.mean()), "test_blocks": len(block_idx),
              "metrics": metrics.reset_index().to_dict("records"),
              "original_reproduction_max_probability_difference": float(
                  np.max(np.abs(original_p - out.original_archived))),
              "selected_minus_archived_test_ap": float(metrics.loc["cv_selected", "test_ap"] - archived_ap),
              "paired_block_bootstrap": {"draws": len(differences), "seed": SEED,
                  "percentile_95_interval": [float(low), float(high)],
                  "limitations": "16 test blocks; adjacent blocks may remain correlated; prior test exploration and matching uncertainty are not captured."},
              "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__,
                           "pandas": pd.__version__, "numpy": np.__version__},
              "test_comparison_status": "Exploratory: the existing team test has previously been inspected."}
    save_json(result, ROOT / "reports/model_review_summary.json")
    return result


def make_figures(data, cv, result):
    d = data["cohort"]
    paths = []
    def save(fig, name):
        fig.savefig(FIGURES / name, dpi=160, bbox_inches="tight")
        paths.append(FIGURES / name)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(2)
    a = pd.read_csv(TABLES / "cohort_audit.csv").set_index("split").loc[["train", "test"]]
    ax.bar(x - .18, a.raw_aadt_missing_share, .36, label="Raw AADT", color=BLUE)
    ax.bar(x + .18, a.screened_aadt_missing_share, .36, label="Screened AADT", color=ORANGE)
    for i, row in enumerate(a.itertuples()):
        ax.text(i-.18, row.raw_aadt_missing_share+.015, f"{row.raw_aadt_missing_share:.1%}", ha="center")
        ax.text(i+.18, row.screened_aadt_missing_share+.015, f"{row.screened_aadt_missing_share:.1%}", ha="center")
    ax.set(xticks=x, xticklabels=["Training: 14,924 segments", "Test: 5,368 segments"],
           ylim=(0, .78), ylabel="Share with missing AADT", title="Screening changes coverage substantially")
    ax.yaxis.set_major_formatter(PercentFormatter(1)); ax.legend(frameon=False, loc="upper left")
    save(fig, "01_aadt_coverage.png")
    fig, ax = plt.subplots(figsize=(8, 4))
    q = pd.read_csv(TABLES / "length_eda.csv")
    for split, color in [("train", BLUE), ("test", ORANGE)]:
        p = q.loc[q.split.eq(split)]
        ax.plot(p.length_bin_m, p.positive_share, marker="o", label=split.capitalize(), color=color)
        for xpos, row in enumerate(p.itertuples()):
            ax.annotate(f"n={row.segments:,}", (xpos, row.positive_share),
                        xytext=(0, 9 if split == "test" else -17), textcoords="offset points",
                        ha="center", fontsize=8, color=color)
    ax.set(xlabel="Geometric segment length (meters)", ylabel="Share with ≥1 matched crash",
           title="Length is associated with the chance of observing a crash")
    ax.yaxis.set_major_formatter(PercentFormatter(1)); ax.legend(frameon=False)
    ax.margins(y=.2); save(fig, "02_length_and_outcome.png")
    fig, ax = plt.subplots(figsize=(9, 5))
    order = cv.sort_values("mean_cv_ap")
    ax.errorbar(order.mean_cv_ap, np.arange(len(order)), xerr=order.sd_cv_ap,
                fmt="o", color=BLUE, capsize=3, label="Mean ± fold SD (not a confidence interval)")
    idx = list(order.index).index(result["selected_candidate"])
    ax.scatter([order.loc[result["selected_candidate"], "mean_cv_ap"]], [idx], color=ORANGE, zorder=3)
    ax.set(yticks=np.arange(len(order)), yticklabels=order.index, xlabel="Average precision",
           title="Model choice used only four training-block validation folds")
    ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0, -.17))
    save(fig, "03_training_cv.png")
    pred = pd.read_csv(LOCAL / "test_predictions_comparison.csv")
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    for name, label, color in [("road_type_baseline", "Road-type baseline", GRAY),
                                ("original_archived", "Bryan archived logistic", BLUE),
                                ("cv_selected", "Training-CV selected", ORANGE)]:
        precision, recall, _ = precision_recall_curve(pred.had_crash, pred[name])
        ap = average_precision_score(pred.had_crash, pred[name])
        ax.step(recall, precision, where="post", color=color, label=f"{label}: AP {ap:.3f}")
    ax.axhline(pred.had_crash.mean(), ls="--", color="#b0b8c4", label="Test prevalence")
    ax.set(xlabel="Recall", ylabel="Precision", xlim=(0, 1), ylim=(0, 1),
           title="Fixed test comparison — exploratory")
    ax.legend(frameon=False, fontsize=8); save(fig, "04_test_precision_recall.png")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for name, label, color in [("original_archived", "Bryan archived", BLUE),
                                ("cv_selected", "CV selected", ORANGE)]:
        observed, predicted = calibration_curve(pred.had_crash, pred[name], n_bins=8, strategy="quantile")
        axes[0].plot(predicted, observed, marker="o", label=label, color=color)
    axes[0].plot([0, 1], [0, 1], ls="--", color=GRAY, lw=1)
    axes[0].set(xlabel="Mean predicted probability", ylabel="Observed positive share",
                title="Calibration (8 quantile bins)", xlim=(0, .4), ylim=(0, .4))
    axes[0].legend(frameon=False, fontsize=8)
    draws = pd.read_csv(LOCAL / "paired_block_bootstrap.csv").ap_delta_vs_archived
    axes[1].hist(draws, bins=35, color=GREEN, alpha=.8)
    axes[1].axvline(0, color=GRAY, ls="--")
    lo, hi = result["paired_block_bootstrap"]["percentile_95_interval"]
    axes[1].axvline(lo, color=ORANGE); axes[1].axvline(hi, color=ORANGE)
    axes[1].set(xlabel="AP difference vs Bryan archived", ylabel="Bootstrap draws",
                title=f"Paired block bootstrap\n95% interval [{lo:.3f}, {hi:.3f}]")
    fig.tight_layout(); save(fig, "05_calibration_and_uncertainty.png")
    return paths


def write_report(data, cv, result, paths):
    metrics = pd.read_csv(TABLES / "test_metrics.csv")
    audit = pd.read_csv(TABLES / "cohort_audit.csv")
    availability = pd.read_csv(TABLES / "aadt_availability.csv")
    lo, hi = result["paired_block_bootstrap"]["percentile_95_interval"]
    delta = result["selected_minus_archived_test_ap"]
    archive_ap = next(x["test_ap"] for x in result["metrics"] if x["model"] == "original_archived")
    selected_ap = next(x["test_ap"] for x in result["metrics"] if x["model"] == "cv_selected")
    conclusion = ("The selected model has a higher point estimate, but the interval includes zero; "
                  "the available comparison does not establish a reliable improvement." if lo <= 0 <= hi else
                  "The paired interval excludes zero under block resampling, but prior test exploration "
                  "and neighboring-block dependence still limit confirmation.")
    def table(df):
        return df.to_html(index=False, border=0, float_format=lambda x: f"{x:.4f}")
    def figure(path):
        encoded = base64.b64encode(path.read_bytes()).decode()
        return f'<figure><img src="data:image/png;base64,{encoded}" alt="{html.escape(path.stem)}"></figure>'
    body = f"""<!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>CS506 — statistical model review</title>
    <style>body{{font:16px/1.6 system-ui,sans-serif;color:#1b283b;max-width:1080px;margin:40px auto;padding:0 24px}}
    h1,h2{{line-height:1.2}}h1{{font-size:36px}}h2{{margin-top:42px}}p{{max-width:920px}}
    .note{{background:#edf3f9;padding:16px 20px;border-left:4px solid #2563a6}}table{{border-collapse:collapse;display:block;overflow:auto;font-size:13px}}
    td,th{{padding:9px 12px;border-bottom:1px solid #dce2e9;text-align:left}}th{{background:#f2f5f8}}
    img{{width:100%;height:auto}}figure{{margin:24px 0}}code{{background:#f1f3f5;padding:2px 4px}}
    a{{color:#2563a6}}small{{color:#667085}}</style>
    <small>CS506 · statistical EDA extension · 24 November 2026 · Boston frozen modeling cohort</small>
    <h1>AADT quality, road length, and model validation</h1>
    <p class="note"><b>Measured result:</b> Bryan's archived logistic model has AP {archive_ap:.4f}.
    Training-block CV selected <code>{html.escape(result['selected_candidate'])}</code>, with fixed-test AP
    {selected_ap:.4f} (difference {delta:+.4f}). Paired bootstrap over 16 test blocks: 95% interval
    [{lo:.4f}, {hi:.4f}]. {conclusion}</p>
    <h2>1. What was checked</h2>
    <p>The supplied ZIP contains seven CSVs. Inputs were preserved and hashed. Segment IDs were checked
    for uniqueness; labels and archived predictions were joined by ID with one-to-one validation.
    The 20,292-row benchmark and its original 14,924/5,368 train/test split were retained. There are
    1,194 positive training segments and 541 positive test segments. The target is <b>at least one matched
    crash on a segment</b> in Bryan's observation period, not crash severity, future crash probability,
    or a traffic-adjusted crash rate. This Boston comparison is separate from the earlier 13-town road EDA.</p>
    {table(audit)}
    <p>Starting road attributes contain 22,592 rows; model features contain 20,685. The archive cannot
    independently reconstruct every upstream exclusion or spatial match because it lacks the matching
    geometry and candidate assignments. Bryan's existing exclusion of 393 Unknown-road-type rows was
    preserved for comparability; it must not be interpreted as evidence that unknown roads are safe.</p>
    <h2>2. AADT is a coverage and interpretation issue</h2>
    <p><code>exposure = AADT × Length</code> was verified. Keeping raw AADT is Bryan's intentional
    modeling choice. It preserves coverage; it does not turn team-flagged default values into measured
    traffic. Screening leaves 63.7% of training segments and 64.8% of test segments without AADT, versus
    18.6% and 12.2% with the raw values. Missingness is associated with road types and matched outcomes;
    complete-case comparisons would change the sample.</p>
    <p><code>traffic_counted</code> exactly equals <code>aadt_clean.notna()</code>. In the EDA copy it is
    also named <code>aadt_available_screened</code> to describe what was checked. Neither name establishes
    that the source was a direct traffic count; the supplied <code>AADT_Deriv</code> codes vary within flag=1.
    The 1,154 default-value screen is the team's assumption and needs confirmation from source metadata.
    Raw exposure is a proxy with AADT × miles units, not total observed vehicle-miles across the crash window.</p>
    {figure(paths[0])}{table(availability)}
    <h2>3. Why separate length from AADT?</h2>
    <p>Longer segments offer more opportunity to contain a recorded crash. The alternatives use
    <code>log1p(Shape__Length)</code> in meters and <code>log1p(AADT)</code> separately, allowing distinct
    associations. The original source <code>Length</code> is in miles. Surface width, connections, the
    arterial interaction, road type, sidewalks, and the availability flag remain available. No crash-derived
    feature, test-block identifier, or image detection was added as a predictor.</p>
    {figure(paths[1])}
    <h2>4. Training-only candidate selection</h2>
    <p>Nine predefined candidates: original logistic regression; separate-length/AADT logistic models
    with C=0.1 or 1, using raw or screened AADT; and shallow histogram gradient boosting with 7 or 15 leaves,
    again using raw or screened AADT. Four GroupKFold folds used only the 50 training blocks. Imputation,
    scaling, and encoding were fitted within each training fold. Boosting used 150 iterations, learning rate
    0.06, minimum 40 samples per leaf, L2=5, and no random early-stopping split.</p>
    <p>Selection used the highest mean fold AP, retaining the original unless the improvement reached
    0.005. Fold SD is variability across four areas, not a confidence interval. A timestamped configuration
    and hashes were saved before evaluating the selected candidate on the existing test set.</p>
    {table(cv.reset_index())}{figure(paths[2])}
    <h2>5. Fixed test comparison and limitations</h2>
    <p>The score called “PR-AUC” in the project is computed as scikit-learn average precision (AP),
    not trapezoidal area under the PR curve. Test prevalence {result['test_prevalence']:.3%} is a random-ranking
    reference. Only the training-selected candidate was compared with the original and road-type baseline.
    Original refit maximum probability difference from archived predictions:
    {result['original_reproduction_max_probability_difference']:.6g}.</p>
    {table(metrics)}{figure(paths[3])}{figure(paths[4])}
    <p><b>This is exploratory evidence.</b> The team previously inspected this test set and used outcomes
    in upstream feature decisions. We cannot restore a pristine holdout retrospectively. GroupKFold keeps
    blocks separate but does not buffer adjacent roads, so nearby areas can remain correlated. The paired
    bootstrap resamples whole test blocks (1,000 draws, seed 506); it cannot account for prior exploration,
    matching errors, missing imagery, or causal confounding. Top-10% summaries are descriptive and use an
    arbitrary ordering within tied scores.</p>
    <h2>6. Recommended team handoff</h2>
    <ul><li>Keep raw AADT, screened AADT, the default-value flag, and AADT derivation metadata separately.
    Document exposure as a proxy and describe the availability flag accurately.</li>
    <li>Use the CV-selected variant as an experimental candidate. Before adopting it, agree on a final
    buffered spatial or later-period evaluation that will not be used repeatedly for model selection.</li>
    <li>Ask Bryan to confirm the crash observation window and spatial matching sensitivity. The archive
    supports label agreement checks, but not independent reconstruction of road-to-crash matching.</li>
    <li>Use road-type and AADT-status subgroup tables to describe coverage and failure modes. Do not select
    a model from their test scores; small subgroups are unstable.</li>
    <li>Add Chun's image coverage and detections only after a keyed segment-level handoff; no image benefit
    is claimed here. Statistical EDA, model validation, and geospatial work should remain attributable.</li></ul>
    <h2>Reproduction and sources</h2>
    <p>Run <code>notebooks/07_statistical_model_review.ipynb</code> or <code>python scripts/model_review.py</code>
    after extracting the supplied archive as described in README. Row-level inputs and predictions are
    local and excluded from the sharing ZIP; aggregated tables, plots, code, and the executed notebook
    are included. This review was prepared with AI coding assistance; numerical claims come from executed
    code, not simulated data.</p>
    <p>Source archive SHA-256: <code>{data['manifest']['archive_sha256']}</code>.<br>
    Versions: Python {platform.python_version()}, scikit-learn {sklearn.__version__}, pandas {pd.__version__}, NumPy {np.__version__}.</p>
    <p><a href="https://github.com/RexHsu09/cs506-final-project/pull/5">Bryan modeling PR</a> ·
    <a href="https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html">GroupKFold</a> ·
    <a href="https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html">Histogram gradient boosting</a> ·
    <a href="https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html">Average precision definition</a></p>
    </html>"""
    path = ROOT / "reports/model_review.html"
    path.write_text(body)
    return path


def main():
    data = load_data()
    run_audit(data)
    cv = run_cross_validation(data)
    selection = freeze_selection(data, cv)
    result = evaluate_selected(data, selection)
    paths = make_figures(data, cv, result)
    report = write_report(data, cv, result, paths)
    print(cv.to_string())
    print(json.dumps(result, indent=2))
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
