#!/usr/bin/env python3
"""Train the pretrained anomaly classifier on a synthetic transactions CSV.

Target: ``synthetic_anomaly_label`` (1 = injected anomaly scenario).

Leakage controls (these columns would reveal the label and are never used):
  * every ``synthetic_*`` column, ``reconciliation_*``, expected/observed
    settlement fields (they are written from the scenario that made the row)
  * free text that names the scenario (``transaction_description``,
    ``transaction_purpose``)
  * identifiers (transaction, reference, account, customer, merchant, device)
  * raw timestamps (the model sees only the derived features in the file)

Split: time-based. The first 80% of transactions by ``initiated_at_utc`` train
the model, the last 20% score it, so no future behaviour leaks into training.

Outputs (under data/artifacts/anomaly_model/):
  * model.joblib        the fitted pipeline
  * metrics.json        holdout metrics, a trivial-rule baseline, feature importance

Usage:
    python scripts/train_anomaly_model.py --csv data/synthetic_1m.csv
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)

ROOT = Path(__file__).resolve().parent.parent
TARGET = "synthetic_anomaly_label"
TIME_COL = "initiated_at_utc"

# Generator-mechanics fields are excluded too: net_* amounts, exchange fees and
# processing/settlement durations are computed from how each row was built, so
# they encode the label (anomaly rows never carry an exchange fee, for example).
NUMERIC = [
    "source_amount", "destination_amount", "fx_rate_to_destination", "fee_amount",
    "source_account_age_days", "destination_account_age_days",
    "src_txn_count_30d", "dst_txn_count_30d", "src_incoming_count_30d",
    "src_outgoing_count_30d", "src_avg_amount_30d", "src_volume_30d",
    "src_unique_counterparties_30d", "dst_unique_counterparties_30d",
    "seconds_since_previous_source", "src_days_since_last_activity",
    "retry_count", "is_cross_border", "is_reversal", "is_refund",
]
CATEGORICAL = [
    "transaction_status", "transaction_category", "source_currency",
    "destination_currency", "source_country", "destination_country",
    "source_account_type", "destination_account_type", "source_customer_type",
    "destination_customer_type", "source_customer_segment",
    "destination_customer_segment", "source_account_status",
    "destination_account_status", "payment_rail", "payment_channel",
    "payment_provider", "source_institution_type", "destination_institution_type",
    "device_country", "ip_country",
]


def load(csv_path: Path) -> pd.DataFrame:
    usecols = [TARGET, TIME_COL, "transaction_id", *NUMERIC, *CATEGORICAL]
    df = pd.read_csv(csv_path, usecols=usecols, low_memory=False)
    # Drop intentionally broken rows (unparseable dates) and exact id duplicates.
    df[TIME_COL] = pd.to_datetime(df[TIME_COL], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    df = df.dropna(subset=[TIME_COL])
    df = df.drop_duplicates(subset=["transaction_id"], keep="first")
    df = df.sort_values(TIME_COL).reset_index(drop=True)
    for col in NUMERIC:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in CATEGORICAL:
        df[col] = df[col].fillna("unknown").astype(str).astype("category")
    df[TARGET] = pd.to_numeric(df[TARGET], errors="coerce").fillna(0).astype(int)
    return df


def trivial_rule_baseline(test: pd.DataFrame) -> dict:
    """What a human could do with one threshold: flag amounts in the band
    where structuring is injected. Reported so the model score can be read
    against it."""
    flag = test["source_amount"].between(88_000, 100_000).astype(int)
    y = test[TARGET].to_numpy()
    tp = int(((flag == 1) & (y == 1)).sum())
    fp = int(((flag == 1) & (y == 0)).sum())
    fn = int(((flag == 0) & (y == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"rule": "source_amount in [88000, 100000]", "precision": round(precision, 4),
            "recall": round(recall, 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=ROOT / "data" / "synthetic_1m.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "artifacts" / "anomaly_model")
    ap.add_argument("--max-iter", type=int, default=300)
    args = ap.parse_args()

    t0 = time.time()
    print(f"loading {args.csv} ...", flush=True)
    df = load(args.csv)
    print(f"  {len(df):,} rows, positives={int(df[TARGET].sum()):,}", flush=True)

    cut = int(len(df) * 0.8)
    train, test = df.iloc[:cut], df.iloc[cut:]
    features = NUMERIC + CATEGORICAL
    X_tr, y_tr = train[features], train[TARGET].to_numpy()
    X_te, y_te = test[features], test[TARGET].to_numpy()

    model = HistGradientBoostingClassifier(
        max_iter=args.max_iter,
        learning_rate=0.08,
        max_leaf_nodes=63,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=20,
        categorical_features="from_dtype",
        random_state=42,
    )
    t_fit = time.time()
    model.fit(X_tr, y_tr)
    fit_seconds = time.time() - t_fit
    print(f"  fitted in {fit_seconds:.1f}s over {model.n_iter_} iterations", flush=True)

    proba = model.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_te, pred, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y_te, pred, labels=[0, 1]).ravel()

    # Permutation importance on a fixed sample keeps this fast on 1M rows.
    sample = test.sample(n=min(20_000, len(test)), random_state=42)
    imp = permutation_importance(model, sample[features], sample[TARGET],
                                 n_repeats=3, random_state=42, scoring="average_precision")
    importance = sorted(
        ({"feature": f, "importance": round(float(m), 6)}
         for f, m in zip(features, imp.importances_mean)),
        key=lambda d: d["importance"], reverse=True)[:15]

    metrics = {
        "target": TARGET,
        "model": "HistGradientBoostingClassifier",
        "rows_total": int(len(df)),
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "positive_rate_test": round(float(y_te.mean()), 5),
        "split": f"time-based 80/20 on {TIME_COL}",
        "iterations": int(model.n_iter_),
        "fit_seconds": round(fit_seconds, 1),
        "holdout": {
            "roc_auc": round(float(roc_auc_score(y_te, proba)), 4),
            "average_precision": round(float(average_precision_score(y_te, proba)), 4),
            "precision_at_0_5": round(float(precision), 4),
            "recall_at_0_5": round(float(recall), 4),
            "f1_at_0_5": round(float(f1), 4),
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        },
        "trivial_rule_baseline": trivial_rule_baseline(test),
        "feature_importance_permutation_ap": importance,
        "leakage_excluded": [
            "synthetic_* columns", "reconciliation_* and settlement expected/observed fields",
            "transaction_description", "transaction_purpose", "identifiers", "raw timestamps",
            "generator-mechanics fields (net_* amounts, exchange fee, processing/settlement durations)",
        ],
        "caveat": ("Labels come from the generator's injected scenarios. High scores show the "
                   "model recovers those scenarios, not that it detects real fraud."),
        "trained_on": str(args.csv.name),
        "wall_seconds": round(time.time() - t0, 1),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "features": features, "categorical": CATEGORICAL,
                 "numeric": NUMERIC, "target": TARGET}, args.out / "model.joblib")
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics["holdout"], indent=2))
    print(f"baseline: {metrics['trivial_rule_baseline']}")
    print(f"saved {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
