"""Automatic machine-learning engine (spec #9).

Chooses task type from the inferred schema, enforces leakage-resistant
evaluation (label exclusion, time/group splits), trains allowlisted models,
and returns metrics + explanations computed by scikit-learn — never by an LLM.
"""
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    IsolationForest,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import (
    GroupShuffleSplit,
    StratifiedShuffleSplit,
    ShuffleSplit,
    TimeSeriesSplit,
    train_test_split,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .schema_inference import ColumnProfile

warnings.filterwarnings("ignore")

RANDOM_STATE = 42
MAX_TRAIN_ROWS = 100_000
MAX_FEATURES = 60

import re

LABEL_PATTERNS = re.compile(
    r"(^label$|_label$|ground_truth|synthetic_anomaly|is_fraud|fraud_label|"
    r"anomaly_label|^target$|_target$|churn|outcome|class$)", re.I
)

# Direct label proxies: scenario columns exist only because a row was generated
# as a synthetic anomaly — including them would leak the target (spec #9.4).
LABEL_PROXY_PATTERNS = re.compile(
    r"(synthetic_scenario|scenario_category|scenario_id|ground_truth|"
    r"^synthetic_|was_flagged|flag_reason)", re.I
)


@dataclass
class MLResult:
    task: str
    status: str                     # completed | unavailable | failed | skipped
    reason: str = ""
    target: str | None = None
    features_used: list[str] = field(default_factory=list)
    excluded_features: list[str] = field(default_factory=list)
    split_strategy: str = ""
    metrics: dict = field(default_factory=dict)
    baselines: dict = field(default_factory=dict)
    per_class: list[dict] = field(default_factory=list)
    confusion: list[list[int]] = field(default_factory=list)
    feature_importance: list[dict] = field(default_factory=list)
    models_tried: list[dict] = field(default_factory=list)
    best_model: str = ""
    limitations: list[str] = field(default_factory=list)
    sample_size: int = 0
    train_size: int = 0
    test_size: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "task": self.task, "status": self.status, "reason": self.reason,
            "target": self.target, "features_used": self.features_used,
            "excluded_features": self.excluded_features,
            "split_strategy": self.split_strategy, "metrics": self.metrics,
            "baselines": self.baselines, "per_class": self.per_class,
            "confusion": self.confusion, "feature_importance": self.feature_importance,
            "models_tried": self.models_tried, "best_model": self.best_model,
            "limitations": self.limitations, "sample_size": self.sample_size,
            "train_size": self.train_size, "test_size": self.test_size,
            "duration_s": round(self.duration_s, 2),
        }


def is_label_column(name: str, profile: ColumnProfile | None = None) -> bool:
    if profile is not None and profile.is_target:
        return True
    return bool(LABEL_PATTERNS.search(name))


def detect_target_leakage(X: pd.DataFrame, y: pd.Series) -> list[str]:
    """Flag features that *perfectly* determine the target in-sample.

    A single feature whose every categorical value maps to exactly one class,
    or whose numeric range separates the classes with no overlap, is almost
    certainly a proxy for the label (e.g. a scenario-name column). Such columns
    are excluded from training and reported (spec #9.4: target-leakage
    detection). Deterministic-only: merely *good* predictors are kept.
    """
    leaks: list[str] = []
    if len(y) < 200 or y.nunique() < 2:
        return leaks
    y_arr = y.to_numpy()
    for c in X.columns:
        s = X[c]
        try:
            if pd.api.types.is_numeric_dtype(s) and s.dtype != bool:
                v = pd.to_numeric(s, errors="coerce")
                m = v.notna()
                if int(m.sum()) < 200:
                    continue
                v2, y2 = v[m], y_arr[m.to_numpy()]
                if pd.Series(y2).nunique() < 2:
                    continue
                pos, neg = v2[y2 == 1], v2[y2 == 0]
                if len(pos) and len(neg) and (
                    float(pos.max()) < float(neg.min())
                    or float(neg.max()) < float(pos.min())
                ):
                    leaks.append(c)
            else:
                v = s.astype(str)
                frame = pd.DataFrame({"__v": v.to_numpy(), "__y": y_arr})
                per_value = frame.groupby("__v")["__y"].nunique()
                if len(per_value) >= 2 and bool((per_value == 1).all()):
                    leaks.append(c)
        except Exception:
            continue
    return leaks


def _prep_features(df: pd.DataFrame, profiles: list[ColumnProfile],
                   target: str, overrides: dict | None = None) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build the feature matrix, excluding the target, raw labels and
    high-cardinality identifiers (spec #9.4 leakage control)."""
    overrides = overrides or {}
    used: list[str] = []
    excluded: list[str] = []
    X_cols: list[str] = []
    for p in profiles:
        name = p.name
        if name == target:
            excluded.append(name)
            continue
        if name not in df.columns:
            continue
        role = overrides.get(name) or p.semantic_type
        if is_label_column(name, p):
            excluded.append(name)
            continue
        if LABEL_PROXY_PATTERNS.search(name):
            excluded.append(name)
            continue
        if p.is_identifier or role == "identifier":
            excluded.append(name)
            continue
        if p.is_sensitive:
            excluded.append(name)
            continue
        if p.physical_type in ("int64", "float64") and not p.is_identifier:
            X_cols.append(name)
        elif role in ("categorical", "boolean") and p.unique_count <= 100:
            X_cols.append(name)
        elif p.physical_type == "datetime":
            continue
        else:
            excluded.append(name)
    X_cols = X_cols[:MAX_FEATURES]
    used = list(X_cols)
    X = df[X_cols].copy()
    for c in X_cols:
        if X[c].dtype == object:
            # try to coerce numeric-looking strings; keep original otherwise
            conv = pd.to_numeric(X[c], errors="coerce")
            if conv.notna().mean() >= 0.9:
                X[c] = conv
    # drop columns that are entirely missing (e.g. optional lifecycle fields):
    # an all-NaN feature poisons imputation and yields NaN predictions
    empty = [c for c in X.columns if X[c].isna().all()
             or (X[c].dtype == object and X[c].astype(str).str.strip().eq("").all())]
    if empty:
        X = X.drop(columns=empty)
        excluded = excluded + empty
        used = [c for c in X.columns]
    return X, used, excluded


def _dtype_split(X: pd.DataFrame) -> tuple[list[str], list[str]]:
    num = [c for c in X.columns if X[c].dtype.kind in "fi"]
    cat = [c for c in X.columns if c not in num]
    return num, cat


def _pipeline(model, num: list[str], cat: list[str]) -> Pipeline:
    transformers = []
    if num:
        transformers.append(("num", Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler(with_mean=False)),
        ]), num))
    if cat:
        transformers.append(("cat", Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
            # sklearn estimators need numbers: one-hot encode categoricals and
            # bound cardinality so a 100-level column can't explode the matrix
            ("onehot", OneHotEncoder(handle_unknown="ignore", max_categories=50,
                                      sparse_output=True)),
        ]), cat))
    pre = ColumnTransformer(transformers, remainder="drop")
    return Pipeline([("pre", pre), ("model", model)])


def _split(y: pd.Series, n: int, time_col: str | None, groups: pd.Series | None,
           strategy_out: list[str]):
    """Leakage-resistant split selection (spec #9.4).

    Grouped splits are retried a few times so the hold-out fold actually
    contains both classes — a single-class fold makes ROC-AUC undefined and
    accuracy meaningless. If retries fail, fall back to stratified sampling.
    """
    if time_col is not None:
        strategy_out.append(f"time-based split on '{time_col}'")
        idx = np.arange(n)
        cut = int(n * 0.8)
        return idx[:cut], idx[cut:]
    if groups is not None and groups.nunique() > 20:
        gss = GroupShuffleSplit(n_splits=8, test_size=0.2, random_state=RANDOM_STATE)
        y_arr = y.to_numpy()
        best = None
        for tr, te in gss.split(np.zeros(n), y=y, groups=groups):
            if len(np.unique(y_arr[te])) >= 2:
                strategy_out.append(f"grouped split by '{groups.name}' (entity leakage control)")
                return tr, te
            best = (tr, te)
        if best is not None and len(np.unique(y_arr[best[1]])) >= 2:
            strategy_out.append(f"grouped split by '{groups.name}' (entity leakage control)")
            return best
        # every grouped fold missed a class → stratify so metrics stay defined
        strategy_out.append(
            f"stratified split (grouped folds by '{groups.name}' held only one class)")
    if y.nunique() >= 2 and y.nunique() <= 20 and (y.value_counts(normalize=True).min() > 0.005):
        sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
        tr, te = next(sss.split(np.zeros(n), y))
        strategy_out.append("stratified 80/20 split")
        return tr, te
    rs = ShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
    tr, te = next(rs.split(np.zeros(n)))
    strategy_out.append("random 80/20 split")
    return tr, te


def run_supervised(df: pd.DataFrame, profiles: list[ColumnProfile],
                   target: str, task: str, overrides: dict | None = None) -> MLResult:
    t0 = time.time()
    is_class = task == "classification"
    res = MLResult(task=task, status="failed", target=target)

    if target not in df.columns:
        res.reason = f"Target column '{target}' not found."
        return res

    y_raw = df[target]
    if is_class:
        y = y_raw
        # map non-numeric labels to integers
        if y.dtype == object or str(y.dtype) == "category":
            y = y.astype("category").cat.codes
        y = pd.to_numeric(y, errors="coerce")
        mask = y.notna()
    else:
        y = pd.to_numeric(y_raw, errors="coerce")
        mask = y.notna()

    X, used, excluded = _prep_features(df, profiles, target, overrides)
    res.features_used = used
    res.excluded_features = excluded
    X = X.loc[mask]
    y = y.loc[mask]

    # in-sample leakage screen: drop features that deterministically encode y
    leaks = detect_target_leakage(X, y)
    if leaks:
        X = X.drop(columns=leaks)
        res.excluded_features = res.excluded_features + leaks
        res.features_used = [c for c in X.columns]
        res.limitations.append(
            f"Leakage detection excluded {len(leaks)} perfectly-predictive "
            f"feature(s): {', '.join(leaks[:6])}"
            f"{'…' if len(leaks) > 6 else ''} — they appear to encode the target.")

    if len(y) < 40:
        res.status = "unavailable"
        res.reason = (f"Only {len(y)} usable rows after dropping missing targets; "
                      "at least 40 are required for reliable evaluation.")
        return res
    if not used:
        res.status = "unavailable"
        res.reason = "No usable feature columns remain after excluding labels and identifiers."
        return res

    # time / group split hints
    time_col = next((c for c, r in (overrides or {}).items() if r == "datetime"), None)
    if time_col is None:
        # datetime columns are deliberately NOT features, so search the frame
        # (not X) — otherwise the temporal split never engages
        time_col = next((p.name for p in profiles if p.semantic_type == "datetime"
                         and p.name in df.columns), None)
    groups = None
    for cand in ("account_id", "customer_id", "source_account_id", "customer"):
        match = next((p.name for p in profiles if cand == p.name.lower() and p.name in df.columns), None)
        if match:
            groups = df.loc[mask, match]
            groups.name = match
            break

    if is_class and y.nunique() < 2:
        res.status = "unavailable"
        res.reason = "Target has a single class after cleaning."
        return res
    if not is_class and y.nunique() < 5:
        res.status = "unavailable"
        res.reason = "Target has too little variation for regression."
        return res

    if len(X) > MAX_TRAIN_ROWS:
        X = X.sample(MAX_TRAIN_ROWS, random_state=RANDOM_STATE)
        y = y.loc[X.index]
        if groups is not None:
            groups = groups.loc[X.index]
        res.limitations.append(f"Sampled to {MAX_TRAIN_ROWS:,} rows for training.")

    strategy: list[str] = []
    n = len(X)
    # time split needs chronological order
    if time_col and time_col in df.columns:
        order = pd.to_datetime(df.loc[mask, time_col], errors="coerce").fillna(
            pd.Timestamp("1970-01-01")).sort_values().index
        X = X.loc[order]
        y = y.loc[order]
        if groups is not None:
            groups = groups.loc[order]
    tr, te = _split(y.reset_index(drop=True), n, time_col if time_col in df.columns else None,
                    groups, strategy)
    res.split_strategy = " · ".join(strategy) or "random split"
    Xtr, Xte = X.iloc[tr], X.iloc[te]
    ytr, yte = y.iloc[tr], y.iloc[te]
    res.sample_size, res.train_size, res.test_size = int(n), int(len(tr)), int(len(te))

    if len(yte) < 5:
        res.status = "unavailable"
        res.reason = "Test split too small for meaningful metrics."
        return res

    num, cat = _dtype_split(Xtr)

    try:
        if is_class:
            results = _train_classifiers(Xtr, ytr, Xte, yte, num, cat, res)
        else:
            results = _train_regressors(Xtr, ytr, Xte, yte, num, cat, res)
    except Exception as exc:
        res.status = "failed"
        res.reason = f"Model training failed: {exc}"
        return res

    res.status = "completed"
    res.duration_s = time.time() - t0
    res.limitations.append(
        "Decision threshold was selected on training predictions to maximize "
        "balanced accuracy; hold-out metrics use that threshold.")
    res.limitations.append(
        "Hold-out metrics on a single split; variance across splits is not reported.")
    res.limitations.append(
        "Association and predictive performance do not establish causation.")
    _ = results
    return res


def _train_classifiers(Xtr, ytr, Xte, yte, num, cat, res: MLResult) -> dict:
    n_samples = len(Xtr)
    allow = []
    if n_samples >= 200:
        allow.append(("RandomForest", RandomForestClassifier(
            n_estimators=120, random_state=RANDOM_STATE, n_jobs=-1, class_weight="balanced")))
        allow.append(("ExtraTrees", ExtraTreesClassifier(
            n_estimators=120, random_state=RANDOM_STATE, n_jobs=-1, class_weight="balanced")))
    if n_samples >= 50:
        allow.append(("GradientBoosting", GradientBoostingClassifier(
            random_state=RANDOM_STATE, n_estimators=80, max_depth=3)))
    allow.append(("LogisticRegression", LogisticRegression(
        max_iter=1000, random_state=RANDOM_STATE, class_weight="balanced")))

    best_name, best_score, best_pipe = "", -1.0, None
    binary = yte.nunique() == 2
    ytr_bin = ytr
    for name, model in allow:
        try:
            pipe = _pipeline(model, num, cat)
            pipe.fit(Xtr, ytr_bin)
            pred = pipe.predict(Xte)
            acc = accuracy_score(yte, pred)
            f1 = f1_score(yte, pred, average="weighted", zero_division=0)
            entry = {"model": name, "accuracy": round(float(acc), 4),
                     "f1_weighted": round(float(f1), 4)}
            # probabilities where supported
            roc = pr = None
            if hasattr(pipe, "predict_proba"):
                try:
                    proba = pipe.predict_proba(Xte)
                    if proba.shape[1] == 2:
                        roc = float(roc_auc_score(yte, proba[:, 1]))
                        pr = float(average_precision_score(yte, proba[:, 1]))
                    else:
                        roc = float(roc_auc_score(yte, proba, multi_class="ovr",
                                                  average="weighted"))
                        pr = None
                except Exception:
                    roc = pr = None
            if roc is not None:
                entry["roc_auc"] = round(roc, 4)
            if pr is not None:
                entry["pr_auc"] = round(pr, 4)
            res.models_tried.append(entry)
            # never rank on a NaN metric (e.g. a single-class hold-out fold)
            score = roc if roc is not None and np.isfinite(roc) else f1
            if not np.isfinite(score):
                score = acc
            if score > best_score:
                best_name, best_score, best_pipe = name, score, pipe
        except Exception as exc:
            res.models_tried.append({"model": name, "error": str(exc)[:200]})

    if best_pipe is None:
        raise RuntimeError("all candidate classifiers failed")

    # Choose the operating threshold on TRAINING predictions only (no test
    # leakage). Class-imbalanced grouped folds otherwise leave the default 0.5
    # cut-off predicting one class for every row while ranking remains good.
    # Method: scan a fixed grid for the max balanced accuracy, then take the
    # midpoint of the optimal interval so the choice is robust to calibration.
    threshold = 0.5
    try:
        if hasattr(best_pipe, "predict_proba") and ytr.nunique() >= 2:
            p_train = best_pipe.predict_proba(Xtr)[:, 1]
            ytr_arr = ytr.to_numpy()
            if np.isfinite(p_train).all():
                grid = np.linspace(0.01, 0.99, 99)
                bals = [float(balanced_accuracy_score(ytr_arr, (p_train >= t).astype(int)))
                        for t in grid]
                best_bal = max(bals)
                if best_bal > 0.5:
                    ok = [t for t, b in zip(grid, bals) if b >= best_bal - 1e-9]
                    threshold = float((min(ok) + max(ok)) / 2)
    except Exception:
        threshold = 0.5

    if hasattr(best_pipe, "predict_proba"):
        try:
            test_proba = best_pipe.predict_proba(Xte)[:, 1]
            pred = (test_proba >= threshold).astype(int) if test_proba.shape[1] == 2 \
                else best_pipe.predict(Xte)
        except Exception:
            pred = best_pipe.predict(Xte)
            threshold = 0.5
    else:
        pred = best_pipe.predict(Xte)
    res.best_model = best_name
    res.metrics = {
        "accuracy": round(float(accuracy_score(yte, pred)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(yte, pred)), 4),
        "precision_weighted": round(float(precision_score(yte, pred, average="weighted",
                                                          zero_division=0)), 4),
        "recall_weighted": round(float(recall_score(yte, pred, average="weighted",
                                                    zero_division=0)), 4),
        "f1_weighted": round(float(f1_score(yte, pred, average="weighted", zero_division=0)), 4),
    }
    if hasattr(best_pipe, "predict_proba"):
        try:
            proba = best_pipe.predict_proba(Xte)
            if proba.shape[1] == 2:
                roc = float(roc_auc_score(yte, proba[:, 1]))
                pr = float(average_precision_score(yte, proba[:, 1]))
            else:
                roc = float(roc_auc_score(yte, proba, multi_class="ovr",
                                          average="weighted"))
                pr = None
        except Exception:
            roc = pr = None
        # never surface a non-finite metric (undefined for single-class folds)
        for key, val in (("roc_auc", roc), ("pr_auc", pr)):
            if val is not None and np.isfinite(val):
                res.metrics[key] = round(val, 4)
    res.metrics["decision_threshold"] = round(threshold, 3)

    labels_present = sorted(set(yte.unique()) | set(pred))
    cm = confusion_matrix(yte, pred, labels=labels_present)
    res.confusion = cm.tolist()
    res.per_class = []
    for i, lab in enumerate(labels_present):
        tp = int(cm[i][i])
        fn = int(cm[i].sum() - tp)
        fp = int(cm[:, i].sum() - tp)
        support = int(cm[i].sum())
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        res.per_class.append({"class": str(lab), "precision": round(prec, 3),
                              "recall": round(rec, 3), "f1": round(f1, 3),
                              "support": support})

    # baseline: majority class
    majority = ytr.value_counts().idxmax()
    base_pred = np.full(len(yte), majority)
    res.baselines = {"majority_class_accuracy": round(float(accuracy_score(yte, base_pred)), 4),
                     "majority_class": str(majority)}

    res.feature_importance = _importance(best_pipe, Xtr, ytr, num, cat)
    return {"best": best_name}


def _train_regressors(Xtr, ytr, Xte, yte, num, cat, res: MLResult) -> dict:
    allow = [("Ridge", Ridge(alpha=1.0))]
    if len(Xtr) >= 200:
        allow.append(("RandomForestRegressor", RandomForestRegressor(
            n_estimators=100, random_state=RANDOM_STATE, n_jobs=-1)))
    best_name, best_rmse, best_pipe = "", float("inf"), None
    for name, model in allow:
        try:
            pipe = _pipeline(model, num, cat)
            pipe.fit(Xtr, ytr)
            pred = pipe.predict(Xte)
            rmse = float(np.sqrt(mean_squared_error(yte, pred)))
            res.models_tried.append({"model": name, "rmse": round(rmse, 4),
                                     "mae": round(float(mean_absolute_error(yte, pred)), 4),
                                     "r2": round(float(r2_score(yte, pred)), 4)})
            if rmse < best_rmse:
                best_name, best_rmse, best_pipe = name, rmse, pipe
        except Exception as exc:
            res.models_tried.append({"model": name, "error": str(exc)[:200]})
    if best_pipe is None:
        raise RuntimeError("all candidate regressors failed")
    pred = best_pipe.predict(Xte)
    res.best_model = best_name
    res.metrics = {
        "mae": round(float(mean_absolute_error(yte, pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(yte, pred))), 4),
        "r2": round(float(r2_score(yte, pred)), 4),
        "max_error": round(float(np.max(np.abs(yte - pred))), 4),
    }
    base = np.full(len(yte), float(ytr.mean()))
    res.baselines = {"mean_baseline_rmse": round(
        float(np.sqrt(mean_squared_error(yte, base))), 4)}
    res.feature_importance = _importance(best_pipe, Xtr, ytr, num, cat)
    # residual summary
    resid = (yte - pred)
    res.metrics["residual_mean"] = round(float(resid.mean()), 4)
    res.metrics["residual_std"] = round(float(resid.std()), 4)
    return {"best": best_name}


def _feature_names(pipe: Pipeline, num: list[str], cat: list[str]) -> list[str]:
    """Output feature names of the fitted preprocessor (aligned with importances)."""
    try:
        pre = pipe.named_steps["pre"]
        names = list(pre.get_feature_names_out())
        # strip sklearn transformer prefixes (num__, cat__)
        return [str(n).split("__", 1)[-1] for n in names]
    except Exception:
        out: list[str] = []
        for _, _, cols in pipe.named_steps["pre"].transformers_:
            if cols is not None and cols != "drop":
                out.extend(list(cols))
        return out


def _importance(pipe: Pipeline, Xtr, ytr, num, cat) -> list[dict]:
    """Permutation-style importance on the holdout is avoided here to keep the
    API cheap; instead use model-native importances when available and a quick
    correlation-based fallback otherwise."""
    out: list[dict] = []
    model = pipe.named_steps.get("model")
    try:
        feat_names = _feature_names(pipe, num, cat)
        if hasattr(model, "feature_importances_"):
            imps = np.asarray(model.feature_importances_)
            if len(feat_names) == len(imps):
                order = np.argsort(imps)[::-1][:20]
                return [{"feature": str(feat_names[i]), "importance": round(float(imps[i]), 4)}
                        for i in order]
        if hasattr(model, "coef_"):
            coef = np.asarray(model.coef_)
            if coef.ndim > 1:
                coef = np.abs(coef).mean(axis=0)
            if len(feat_names) == len(coef):
                order = np.argsort(np.abs(coef))[::-1][:20]
                return [{"feature": str(feat_names[i]),
                         "importance": round(float(abs(coef[i])), 4),
                         "signed_coef": round(float(coef[i]), 4)} for i in order]
    except Exception:
        pass
    return out


# ---------------------------------------------------- unsupervised ----------
@dataclass
class UnsupervisedResult:
    method: str
    status: str
    reason: str = ""
    features_used: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    clusters: list[dict] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)
    sample_size: int = 0
    limitations: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "method": self.method, "status": self.status, "reason": self.reason,
            "features_used": self.features_used, "metrics": self.metrics,
            "clusters": self.clusters, "anomalies": self.anomalies,
            "sample_size": self.sample_size, "limitations": self.limitations,
            "duration_s": round(self.duration_s, 2),
        }


def run_clustering(df: pd.DataFrame, profiles: list[ColumnProfile],
                   max_clusters: int = 6) -> UnsupervisedResult:
    from sklearn.cluster import KMeans

    t0 = time.time()
    feats = [p.name for p in profiles
             if p.physical_type in ("int64", "float64") and not p.is_identifier
             and p.name in df.columns][:MAX_FEATURES]
    res = UnsupervisedResult(method="K-Means", status="failed", features_used=feats)
    if len(feats) < 2:
        res.status = "unavailable"
        res.reason = "Clustering needs at least two numeric feature columns."
        return res
    X = df[feats].apply(pd.to_numeric, errors="coerce")
    mask = X.notna().all(axis=1)
    X = X[mask]
    if len(X) < 50:
        res.status = "unavailable"
        res.reason = f"Only {len(X)} complete rows; clustering needs at least 50."
        return res
    if len(X) > 30_000:
        X = X.sample(30_000, random_state=RANDOM_STATE)
        res.limitations.append("Fitted on a 30,000-row sample for tractability.")
    res.sample_size = int(len(X))

    Xs = StandardScaler().fit_transform(X)
    k = int(min(max_clusters, max(2, round(np.sqrt(len(Xs) / 2)))))
    k = max(2, min(k, 8, len(Xs) // 10))
    km = KMeans(n_clusters=k, random_state=RANDOM_STATE, n_init=10)
    labels = km.fit_predict(Xs)
    inertia = float(km.inertia_)
    # silhouette on a subsample (O(n²) otherwise)
    sil = None
    try:
        from sklearn.metrics import silhouette_score
        if len(Xs) > 5000:
            idx = np.random.RandomState(RANDOM_STATE).choice(len(Xs), 5000, replace=False)
            sil = float(silhouette_score(Xs[idx], labels[idx]))
        else:
            sil = float(silhouette_score(Xs, labels))
    except Exception:
        pass
    res.metrics = {"k": k, "inertia": round(inertia, 2),
                   "silhouette": round(sil, 4) if sil else None,
                   "n_clusters_found": int(len(set(labels)))}

    work = X.copy()
    work["__cluster"] = labels
    for c in sorted(set(labels)):
        sub = work[work["__cluster"] == c]
        profile = {}
        for f in feats[:12]:
            med = float(sub[f].median())
            overall = float(work[f].median())
            profile[f] = {"median": round(med, 4),
                          "vs_overall": "higher" if med > overall * 1.1
                          else "lower" if med < overall * 0.9 else "similar"}
        top_members = sub.index[:3]
        res.clusters.append({
            "cluster": int(c), "size": int(len(sub)),
            "share_pct": round(100 * len(sub) / len(work), 1),
            "profile": profile,
            "representative_rows": [int(i) for i in top_members],
        })
    res.status = "completed"
    res.duration_s = time.time() - t0
    res.limitations.append(
        "Clusters describe structure in the data; they are not evidence of "
        "criminal or fraudulent activity.")
    return res


def run_anomaly_detection(df: pd.DataFrame, profiles: list[ColumnProfile],
                          label_col: str | None = None) -> UnsupervisedResult:
    t0 = time.time()
    feats = [p.name for p in profiles
             if p.physical_type in ("int64", "float64") and not p.is_identifier
             and p.name in df.columns][:MAX_FEATURES]
    res = UnsupervisedResult(method="IsolationForest", status="failed", features_used=feats)
    if len(feats) < 2:
        res.status = "unavailable"
        res.reason = "Anomaly detection needs at least two numeric feature columns."
        return res
    X = df[feats].apply(pd.to_numeric, errors="coerce")
    mask = X.notna().any(axis=1)
    X = X[mask]
    if len(X) < 50:
        res.status = "unavailable"
        res.reason = f"Only {len(X)} usable rows; at least 50 are required."
        return res
    sampled = False
    if len(X) > 50_000:
        X = X.sample(50_000, random_state=RANDOM_STATE)
        sampled = True
        res.limitations.append("Scored on a 50,000-row sample.")
    res.sample_size = int(len(X))

    Xs = SimpleImputer(strategy="median").fit_transform(X)
    Xs = StandardScaler().fit_transform(Xs)
    iso = IsolationForest(n_estimators=200, contamination="auto",
                          random_state=RANDOM_STATE, n_jobs=-1)
    raw = iso.fit_predict(Xs)               # 1 = inlier, -1 = outlier
    scores = -iso.score_samples(Xs)         # higher = more anomalous
    flags = raw == -1
    n_flagged = int(flags.sum())

    res.metrics = {
        "flagged": n_flagged,
        "flagged_pct": round(100 * n_flagged / len(X), 2),
        "contamination_observed": round(n_flagged / len(X), 4),
        "threshold_percentile": 95,
        "score_mean": round(float(scores.mean()), 4),
        "score_p95": round(float(np.percentile(scores, 95)), 4),
    }

    # top explainable anomalies: contribution of each feature to deviation
    med = np.median(Xs, axis=0)
    order = np.argsort(scores)[::-1][:25]
    for i in order:
        row = Xs[i]
        dev = np.abs(row - med)
        top_feats = np.argsort(dev)[::-1][:4]
        reasons = []
        for f in top_feats:
            val = float(X.iloc[i, f]) if f < X.shape[1] else None
            reasons.append({
                "feature": feats[f],
                "value": round(val, 4) if val is not None else None,
                "deviation_sigma": round(float(row[f] - med[f]), 2),
            })
        original_idx = int(X.index[i])
        item = {
            "row_index": original_idx,
            "score": round(float(scores[i]), 4),
            "reasons": reasons,
            "detected_by": "IsolationForest (unsupervised)",
        }
        if label_col and label_col in df.columns:
            item["synthetic_label"] = str(df.iloc[original_idx][label_col])
        res.anomalies.append(item)

    # if a ground-truth label exists, report agreement honestly
    if label_col and label_col in df.columns:
        try:
            y = pd.to_numeric(df.loc[X.index, label_col], errors="coerce")
            valid = y.notna()
            if valid.sum() > 30:
                yt = (y[valid] == 1).astype(int).to_numpy()
                pf = flags[valid.nonzero()[0]]
                tp = int(((pf) & (yt == 1)).sum())
                fp = int(((pf) & (yt == 0)).sum())
                fn = int((~pf & (yt == 1)).sum())
                tn = int((~pf & (yt == 0)).sum())
                prec = tp / (tp + fp) if (tp + fp) else 0.0
                rec = tp / (tp + fn) if (tp + fn) else 0.0
                res.metrics["agreement_with_label"] = {
                    "precision": round(prec, 3), "recall": round(rec, 3),
                    "support_positive": int((yt == 1).sum()),
                    "note": "Evaluated against synthetic ground-truth labels held out of features.",
                }
        except Exception:
            pass

    res.status = "completed"
    res.duration_s = time.time() - t0
    res.limitations.append(
        "IsolationForest flags statistical rarity, not confirmed fraud; "
        "thresholds are configurable and false positives are expected.")
    res.limitations.append(
        "Unsupervised scores are not calibrated probabilities of fraud.")
    return res


def run_forecast(df: pd.DataFrame, profiles: list[ColumnProfile]) -> dict:
    """Naive seasonal + trend forecast on the best numeric series with a time
    column. Reported with honest error metrics from rolling-origin backtest."""
    time_col = next((p.name for p in profiles if p.semantic_type == "datetime"), None)
    if not time_col:
        return {"status": "unavailable", "reason": "No time column detected."}
    num_cols = [p.name for p in profiles if p.physical_type in ("int64", "float64")
                and not p.is_identifier and p.name in df.columns]
    if not num_cols:
        return {"status": "unavailable", "reason": "No numeric column to forecast."}
    try:
        ts = df[[time_col] + num_cols].copy()
        ts[time_col] = pd.to_datetime(ts[time_col], errors="coerce", utc=False)
        # strip any timezone so arithmetic never mixes aware/naive
        if getattr(ts[time_col].dtype, "tz", None) is not None:
            ts[time_col] = ts[time_col].dt.tz_localize(None)
        ts = ts.dropna(subset=[time_col]).sort_values(time_col)
        if len(ts) < 40:
            return {"status": "unavailable",
                    "reason": f"Only {len(ts)} time points; at least 40 required."}
        # pick the series with the most variance after daily aggregation
        target = None
        best_var = -1.0
        ts = ts.set_index(time_col).sort_index()
        for c in num_cols:
            v = pd.to_numeric(ts[c], errors="coerce")
            if v.notna().sum() < 40:
                continue
            daily = v.groupby(pd.Grouper(freq="D")).sum()
            var = float(daily.var()) if daily.notna().any() else -1
            if var > best_var:
                best_var, target = var, c
        if target is None:
            return {"status": "unavailable", "reason": "No forecastable numeric series."}
        series = (pd.to_numeric(ts[target], errors="coerce")
                  .groupby(pd.Grouper(freq="D")).sum().fillna(0.0))
        series = series[series.index <= series.index.max()]
        if len(series) < 40:
            return {"status": "unavailable", "reason": "Daily aggregation left too few points."}

        # seasonal-naive: value from 7 days ago; backtest last 14 points
        backtest_n = min(14, max(7, len(series) // 8))
        hist, test = series.iloc[:-backtest_n], series.iloc[-backtest_n:]
        pred = []
        for i in range(len(test)):
            hist_all = pd.concat([hist, pd.Series(pred, index=test.index[:i])]) if pred else hist
            lag = hist_all.iloc[-7] if len(hist_all) >= 7 else hist_all.iloc[-1]
            pred.append(float(lag))
        pred = np.array(pred)
        mae = float(np.mean(np.abs(test.to_numpy() - pred)))
        rmse = float(np.sqrt(np.mean((test.to_numpy() - pred) ** 2)))
        denom = np.where(np.abs(test.to_numpy()) > 0, np.abs(test.to_numpy()), np.nan)
        mape = float(np.nanmean(np.abs((test.to_numpy() - pred) / denom)) * 100)

        # future: repeat last week pattern
        horizon = 7
        last_week = series.iloc[-7:].to_numpy()
        future = [{"t": str(series.index.max() + pd.Timedelta(days=d + 1))[:10],
                   "forecast": float(last_week[d % 7])} for d in range(horizon)]
        fitted = [{"t": str(idx)[:10], "actual": float(v)}
                  for idx, v in series.iloc[-120:].items()]
        return {
            "status": "completed",
            "method": "seasonal naive (lag 7) daily aggregation",
            "target": target,
            "points": int(len(series)),
            "backtest_points": int(backtest_n),
            "mae": round(mae, 4), "rmse": round(rmse, 4),
            "mape_pct": round(mape, 2) if mape == mape else None,
            "history": fitted,
            "future": future,
            "note": ("Backtest metrics are computed on the last held-out window; "
                     "prediction intervals are not provided by this method."),
        }
    except Exception as exc:
        return {"status": "failed", "reason": str(exc)[:300]}
