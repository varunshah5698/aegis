"""Universal schema inference and semantic column mapping (spec #5).

Works on any CSV: inspects names, values, cardinality, patterns and
distributions to infer physical + semantic types, identifier roles, target
roles and sensitivity — without assuming financial column names.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

# ------------------------------------------------------------- semantics ----
NUMERIC = "numeric"
INTEGER = "integer"
FLOAT = "float"
CATEGORY = "categorical"
TEXT = "text"
DATETIME = "datetime"
BOOLEAN = "boolean"
IDENTIFIER = "identifier"
CURRENCY_AMOUNT = "currency_amount"
CURRENCY_CODE = "currency_code"
PERCENT = "percentage"
GEOGRAPHIC = "geographic"
ID_LIKE = "id_like"

DATE_PATTERNS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%d %b %Y",
]

ID_TOKENS = re.compile(
    r"(_id$|^id$|id_|uuid|guid|reference|ref$|account|customer|client|user|transaction|"
    r"order|invoice|session|device|merchant|institution|branch|iban|swift|card|token)",
    re.I,
)
GEO_TOKENS = re.compile(
    r"(country|region|state|province|city|postal|zip|postcode|county|location|lat|latitude|"
    r"lon|longitude|address|territory|zone|district)",
    re.I,
)
CURRENCY_TOKENS = re.compile(r"(currency|ccy|curr$|fx_|exchange_rate|rate_to)", re.I)
AMOUNT_TOKENS = re.compile(
    r"(amount|amt|price|value|balance|total|fee|cost|revenue|salary|payment|sum|volume|worth)",
    re.I,
)
PERCENT_TOKENS = re.compile(r"(percent|percentage|pct|_rate$|ratio|bps|proportion)", re.I)
DATE_TOKENS = re.compile(
    r"(date|time|_at$|timestamp|day|month|year|period|created|settled|processed|updated)", re.I
)
TEXT_TOKENS = re.compile(r"(description|comment|note|name|title|message|reason|memo|summary|label)", re.I)
TARGET_TOKENS = re.compile(
    r"(label|target|churn|fraud|anomaly|default|outcome|class|(^y$|_y$)|ground_truth|is_fraud|"
    r"synthetic_anomaly|binary)",
    re.I,
)
BOOL_TOKENS = re.compile(r"(^is_|_flag$|^has_|^was_|^can_|^should_|active|enabled|disabled)", re.I)
SENSITIVE_TOKENS = re.compile(
    r"(ssn|social_security|passport|pan_|card_number|cardno|cvv|password|secret|token|"
    r"api_key|iban|account_number|phone|mobile|email|dob|birth)",
    re.I,
)

TRUE_TOKENS = {"true", "t", "yes", "y", "1", "1.0", "active", "enabled"}
FALSE_TOKENS = {"false", "f", "no", "n", "0", "0.0", "inactive", "disabled"}


@dataclass
class ColumnProfile:
    name: str
    normalized: str
    physical_type: str
    semantic_type: str
    likely_meaning: str = ""
    null_pct: float = 0.0
    unique_count: int = 0
    uniqueness_ratio: float = 0.0
    sample_values: list = field(default_factory=list)
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_mean: float | None = None
    typical_value: str = ""
    distribution: str = ""
    date_min: str | None = None
    date_max: str | None = None
    is_identifier: bool = False
    is_target: bool = False
    is_sensitive: bool = False
    semantic_confidence: float = 0.0
    reason: str = ""
    categories: list = field(default_factory=list)
    user_override: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------- helpers ----
def _is_numeric_str(s: str) -> bool:
    s = s.strip().replace(",", "")
    if not s:
        return False
    if s.startswith(("$", "₹", "€", "£")):
        s = s[1:]
    if s.endswith("%"):
        try:
            float(s[:-1])
            return True
        except ValueError:
            return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _parse_num(v: str) -> float | None:
    v = v.strip().replace(",", "")
    if not v:
        return None
    if v.startswith(("$", "₹", "€", "£")):
        v = v[1:]
    neg = v.startswith("(") and v.endswith(")")
    if neg:
        v = v[1:-1]
    if v.endswith("%"):
        v = v[:-1]
    try:
        x = float(v)
        return -x if neg else x
    except ValueError:
        return None


def _parse_date(v: str) -> datetime | None:
    v = v.strip()
    if not v:
        return None
    # ISO-ish fast path
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    return None


def _name_signal(name: str, pattern: re.Pattern) -> bool:
    return bool(pattern.search(name))


def _classify_physical(series: pd.Series, sample: list[str]) -> str:
    non_null = [v for v in sample if v != ""]
    if not non_null:
        return "empty"
    numeric_hits = sum(1 for v in non_null if _is_numeric_str(v))
    ratio = numeric_hits / len(non_null)

    if ratio >= 0.95:
        vals = [_parse_num(v) for v in non_null]
        nums = [v for v in vals if v is not None]
        if nums and all(float(v).is_integer() for v in nums):
            return "int64"
        return "float64"

    bool_hits = sum(1 for v in non_null if v.strip().lower() in TRUE_TOKENS | FALSE_TOKENS)
    if ratio < 0.5 and bool_hits / len(non_null) >= 0.98:
        return "bool"

    date_hits = sum(1 for v in non_null[:500] if _parse_date(v) is not None)
    if date_hits / min(len(non_null), 500) >= 0.9:
        return "datetime"

    return "object"


def _distribution(nums: np.ndarray) -> str:
    if nums.size == 0:
        return "unknown"
    med = float(np.median(nums))
    mean = float(np.mean(nums))
    if med == 0:
        return "constant" if mean == 0 else "skewed"
    coeff = mean / med if med else 0.0
    if coeff > 1.6:
        return "right-skewed"
    if coeff < 0.6:
        return "left-skewed"
    return "approximately-symmetric"


# ------------------------------------------------------- column profiler ----
def profile_column(name: str, series: pd.Series) -> ColumnProfile:
    filled = series.fillna("").astype(str)
    total = len(filled)
    non_empty = filled[filled.str.strip() != ""]
    null_pct = round(100.0 * (total - len(non_empty)) / total, 3) if total else 100.0
    sample = non_empty.head(2000).tolist()

    physical = _classify_physical(series, sample)
    unique_vals = non_empty.unique().tolist()
    unique_count = len(unique_vals)
    uniqueness = round(unique_count / len(non_empty), 4) if len(non_empty) else 0.0

    prof = ColumnProfile(
        name=name,
        normalized=re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower(),
        physical_type=physical,
        semantic_type=TEXT,
        null_pct=null_pct,
        unique_count=unique_count,
        uniqueness_ratio=uniqueness,
        sample_values=unique_vals[:5],
    )

    low = name.lower()
    reasons: list[str] = []

    # ---- numeric path
    if physical in ("int64", "float64"):
        nums = np.array([x for x in (_parse_num(v) for v in sample) if x is not None], dtype=float)
        if nums.size:
            prof.numeric_min = float(np.min(nums))
            prof.numeric_max = float(np.max(nums))
            prof.numeric_mean = float(np.mean(nums))
            prof.distribution = _distribution(nums)
            prof.typical_value = str(round(float(np.median(nums)), 4))

        # identifier-shaped digits (postal codes, account numbers, phone…)
        digitish = all(v.strip().replace("-", "").isdigit() for v in sample[:50])
        id_name = bool(ID_TOKENS.search(name))
        if uniqueness > 0.95 and id_name:
            prof.semantic_type = IDENTIFIER
            prof.is_identifier = True
            reasons.append("name contains an identifier token and values are ~unique")
        elif digitish and _name_signal(name, ID_LIKE_PIN) :
            prof.semantic_type = GEOGRAPHIC
            reasons.append("digit-only values with a postal/geo-like name")
        elif id_name and uniqueness > 0.5:
            prof.semantic_type = IDENTIFIER
            prof.is_identifier = True
            reasons.append("identifier-like name with low repetition")
        elif _name_signal(name, PERCENT_TOKENS):
            prof.semantic_type = PERCENT
            reasons.append("name suggests a percentage or ratio")
        elif _name_signal(name, AMOUNT_TOKENS) or (nums.size and float(np.min(nums)) < 0):
            prof.semantic_type = CURRENCY_AMOUNT
            reasons.append("name suggests a monetary amount" if _name_signal(name, AMOUNT_TOKENS)
                           else "negative values suggest signed amounts")
        else:
            prof.semantic_type = FLOAT if physical == "float64" else INTEGER
            reasons.append("values parse as numbers")

        if uniqueness == 1.0 and unique_count > 1000:
            prof.semantic_type = IDENTIFIER
            prof.is_identifier = True
            reasons.append("every value is unique")
    else:
        # ---- categorical / text / datetime / bool
        top = Counter(non_empty.tolist()).most_common(12)
        prof.categories = [{"value": k, "count": v} for k, v in top]
        prof.typical_value = top[0][0] if top else ""

        if physical == "bool":
            prof.semantic_type = BOOLEAN
            reasons.append("values are boolean-like")
        elif physical == "datetime":
            prof.semantic_type = DATETIME
            parsed = [d for d in (_parse_date(v) for v in sample[:2000]) if d]
            if parsed:
                prof.date_min = min(parsed).isoformat(sep=" ")
                prof.date_max = max(parsed).isoformat(sep=" ")
            reasons.append("values parse as dates/timestamps")
        else:
            avg_len = float(np.mean([len(v) for v in sample])) if sample else 0
            if unique_count <= 30 and uniqueness < 0.5:
                prof.semantic_type = CATEGORY
                reasons.append(f"low cardinality ({unique_count} distinct values)")
            elif avg_len > 60 or uniqueness > 0.8:
                prof.semantic_type = TEXT
                reasons.append("free text with many distinct values")
            else:
                prof.semantic_type = CATEGORY
                reasons.append(f"{unique_count} distinct values")

    # ---- name-based semantic overrides (carry more weight than heuristics)
    if _name_signal(name, CURRENCY_TOKENS):
        if prof.physical_type == "object" and unique_count <= 20:
            prof.semantic_type = CURRENCY_CODE
            reasons.append("name suggests a currency code")
        else:
            prof.semantic_type = CURRENCY_AMOUNT
            reasons.append("name mentions currency or FX")
    elif _name_signal(name, GEO_TOKENS):
        prof.semantic_type = GEOGRAPHIC
        reasons.append("name suggests geography")
    elif _name_signal(name, TARGET_TOKENS) and prof.physical_type in ("object", "int64", "bool", "float64"):
        prof.semantic_type = "target"
        prof.is_target = True
        reasons.append("name suggests a label/target column")

    if _name_signal(name, DATE_TOKENS) and prof.physical_type == "datetime" and prof.semantic_type == TEXT:
        prof.semantic_type = DATETIME

    if prof.physical_type == "object" and _name_signal(name, TEXT_TOKENS):
        prof.semantic_type = TEXT
        reasons.append("name suggests free text")

    # sensitivity classification (spec #5.1)
    if SENSITIVE_TOKENS.search(name):
        prof.is_sensitive = True
        reasons.append("name suggests sensitive/personal data")

    # confidence: stronger when name signal + value pattern agree
    conf = 0.55
    if _name_signal(name, ANY_NAME_SIGNAL):
        conf += 0.25
    if prof.is_identifier or prof.is_target:
        conf += 0.1
    if prof.null_pct > 60:
        conf -= 0.15
    prof.semantic_confidence = round(min(max(conf, 0.2), 0.98), 2)
    prof.reason = "; ".join(reasons) if reasons else "insufficient signal"
    prof.likely_meaning = _meaning_guess(name, prof.semantic_type)
    return prof


ID_LIKE_PIN = re.compile(r"(postal|zip|postcode|pin_?code)", re.I)

# single combined name-signal pattern (compiled patterns can't be unioned with |)
ANY_NAME_SIGNAL = re.compile(
    "(?:"
    + "|".join(
        f"(?:{p.pattern})"
        for p in (ID_TOKENS, GEO_TOKENS, CURRENCY_TOKENS, DATE_TOKENS, TARGET_TOKENS)
    )
    + ")",
    re.I,
)


def _meaning_guess(name: str, semantic: str) -> str:
    pretty = name.replace("_", " ").strip().lower()
    if semantic == IDENTIFIER:
        return f"Unique identifier: {pretty}"
    if semantic == DATETIME:
        return f"Event timestamp: {pretty}"
    if semantic == CURRENCY_AMOUNT:
        return f"Monetary amount: {pretty}"
    if semantic == CURRENCY_CODE:
        return f"Currency code: {pretty}"
    if semantic == GEOGRAPHIC:
        return f"Geographic attribute: {pretty}"
    if semantic == "target":
        return f"Label/target used for evaluation: {pretty}"
    if semantic == BOOLEAN:
        return f"Boolean flag: {pretty}"
    if semantic == CATEGORY:
        return f"Categorical feature: {pretty}"
    if semantic == PERCENT:
        return f"Percentage/ratio: {pretty}"
    return f"Descriptive field: {pretty}"


# ---------------------------------------------- semantic alias mapping ------
ALIASES: dict[str, list[tuple[str, float]]] = {
    # financial transaction semantics (spec #5.2)
    "transaction_id": [(r"^(transaction_id|txn_id|tx_id|trans_id|payment_id|utr|reference_id)$", 0.95)],
    "source_account": [(r"source_account|sender_account|from_account|payer|debtor|origin_account", 0.9)],
    "destination_account": [(r"destination_account|receiver_account|beneficiary|to_account|payee|creditor", 0.9)],
    "sender": [(r"sender|payer_name|from_name|originator", 0.85)],
    "receiver": [(r"receiver|payee_name|beneficiary_name|recipient|to_name", 0.85)],
    "source_customer": [(r"source_customer|sender_customer|customer_id_from", 0.85)],
    "destination_customer": [(r"destination_customer|receiver_customer|customer_id_to", 0.85)],
    "amount_source": [(r"^source_amount$|amount_source|original_amount|txn_amount|transaction_amount|debit_amount", 0.9)],
    "amount_destination": [(r"^destination_amount$|amount_destination|credited_amount|received_amount", 0.9)],
    "currency_source": [(r"^source_currency$|currency_code_from|base_currency|txn_currency", 0.9)],
    "currency_destination": [(r"^destination_currency$|currency_code_to|quote_currency", 0.9)],
    "fx_rate": [(r"fx_rate|exchange_rate|conversion_rate|rate_to", 0.9)],
    "fee_amount": [(r"fee_amount|charges|commission", 0.85)],
    "transaction_time": [(r"initiated_at|transaction_time|txn_time|transaction_date|posted_at|value_date|timestamp", 0.9)],
    "settlement_time": [(r"settled_at|settlement_date|settlement_time", 0.9)],
    "status": [(r"transaction_status|payment_status|status$|state$", 0.85)],
    "category": [(r"transaction_category|category$|type$|transaction_type|merchant_category|mcc$", 0.8)],
    "country": [(r"country|nationality", 0.85)],
    "institution": [(r"institution|bank_id|bank$|issuer|provider", 0.8)],
    "payment_rail": [(r"payment_rail|rail$|scheme|network$|channel|method|payment_method", 0.8)],
    "risk_label": [(r"fraud_label|anomaly_label|is_fraud|risk|flagged|label$", 0.9)],
    "device": [(r"device_id|device$|browser|user_agent", 0.8)],
    "email": [(r"e?mail", 0.95)],
    "phone": [(r"phone|mobile|contact_number", 0.9)],
    "customer_id": [(r"customer_id|client_id|user_id|member_id|party_id", 0.9)],
    "merchant_id": [(r"merchant_id|shop_id|store_id", 0.9)],
    "description": [(r"description|narration|details|remarks|memo", 0.85)],
}


def semantic_alias_match(name: str) -> tuple[str, float] | None:
    low = name.strip().lower()
    best: tuple[str, float] | None = None
    for canonical, patterns in ALIASES.items():
        for pat, score in patterns:
            if re.search(pat, low) and (best is None or score > best[1]):
                best = (canonical, score)
    return best


# ------------------------------------------------------------ dataset -------
@dataclass
class DatasetInference:
    columns: list[ColumnProfile]
    semantic_map: dict[str, str]           # column -> canonical semantic role
    capabilities: dict[str, dict]          # module -> {state, reason}
    detected: dict
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "columns": [c.as_dict() for c in self.columns],
            "semantic_map": self.semantic_map,
            "capabilities": self.capabilities,
            "detected": self.detected,
            "warnings": self.warnings,
        }


def infer_schema(df: pd.DataFrame) -> DatasetInference:
    columns = [profile_column(str(c), df[c]) for c in df.columns]
    warnings: list[str] = []

    semantic_map: dict[str, str] = {}
    for col in columns:
        alias = semantic_alias_match(col.name)
        if alias:
            canonical, score = alias
            if score >= col.semantic_confidence:
                col.semantic_confidence = max(col.semantic_confidence, score)
                col.reason = (col.reason + f"; alias match → {canonical}").strip("; ")
                if canonical in ("transaction_id", "customer_id", "merchant_id", "email", "phone"):
                    col.is_identifier = canonical in ("transaction_id", "customer_id", "merchant_id")
                    if canonical in ("email", "phone"):
                        col.is_sensitive = True
            semantic_map[col.name] = canonical
        elif col.semantic_type == "target":
            semantic_map[col.name] = "target"

    # second pass: ISO-style date columns that name-heuristics missed
    for col in columns:
        if col.physical_type == "datetime" and col.name not in semantic_map:
            semantic_map[col.name] = "datetime"

    capabilities = _assess_capabilities(df, semantic_map, columns)
    detected = {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "numeric_columns": sum(1 for c in columns if c.physical_type in ("int64", "float64")),
        "categorical_columns": sum(1 for c in columns if c.semantic_type == CATEGORY),
        "datetime_columns": sum(1 for c in columns if c.semantic_type == DATETIME),
        "identifier_columns": sum(1 for c in columns if c.is_identifier),
        "target_columns": sum(1 for c in columns if c.is_target),
        "missing_pct": round(float(df.isna().mean().mean() * 100), 2),
    }
    if detected["target_columns"] == 0:
        warnings.append(
            "No target/label column was detected, so supervised learning is unavailable. "
            "Unsupervised methods (clustering, anomaly detection) will be used instead."
        )
    return DatasetInference(columns=columns, semantic_map=semantic_map,
                             capabilities=capabilities, detected=detected, warnings=warnings)


def _cap(state: str, reason: str, **extra) -> dict:
    return {"state": state, "reason": reason, **extra}


def _has_role(semantic_map: dict[str, str], role: str) -> str | None:
    for col, canon in semantic_map.items():
        if canon == role:
            return col
    return None


def _assess_capabilities(df: pd.DataFrame, semantic_map: dict[str, str],
                         columns: list[ColumnProfile]) -> dict[str, dict]:
    """Capability states per spec #5.4."""
    caps: dict[str, dict] = {}
    n = len(df)
    numeric_cols = [c.name for c in columns if c.physical_type in ("int64", "float64") and not c.is_identifier]
    cat_cols = [c.name for c in columns if c.semantic_type in (CATEGORY, BOOLEAN)]
    time_col = _has_role(semantic_map, "transaction_time") or _has_role(semantic_map, "datetime")
    time_col = time_col or next((c.name for c in columns if c.semantic_type == DATETIME), None)
    target_col = _has_role(semantic_map, "target") or next((c.name for c in columns if c.is_target), None)

    caps["eda"] = _cap("available", "Descriptive statistics run on every dataset.") if n else \
        _cap("unavailable", "No data rows.")
    caps["relationships"] = (
        _cap("available", f"{len(numeric_cols)} numeric column(s) available for correlation analysis.")
        if len(numeric_cols) >= 2
        else _cap("unavailable", "At least two numeric columns are required for correlation analysis.")
    )
    caps["timeseries"] = (
        _cap("available", f"Temporal column '{time_col}' found.", column=time_col)
        if time_col else _cap("unavailable", "No date/timestamp column was detected.")
    )

    # ML eligibility (spec #9.1)
    if target_col:
        y = df[target_col]
        nunique = int(y.nunique(dropna=True))
        if nunique < 2:
            caps["ml_classification"] = _cap(
                "unavailable", f"Target '{target_col}' contains a single class.")
            caps["ml_regression"] = _cap(
                "unavailable", f"Target '{target_col}' contains a single class.")
        elif nunique <= 20 and len(numeric_cols) + len(cat_cols) >= 1:
            caps["ml_classification"] = _cap(
                "available", f"Target '{target_col}' has {nunique} classes.", target=target_col)
        else:
            if any(df[c].dtype.kind in "fi" for c in numeric_cols[:1] if c in df):
                caps["ml_regression"] = _cap(
                    "available", f"'{target_col}' looks continuous; regression will be attempted.",
                    target=target_col)
            else:
                caps["ml_regression"] = _cap(
                    "unavailable", f"'{target_col}' is not numeric; regression is not applicable.",
                    target=target_col)
            caps["ml_classification"] = _cap(
                "needs_configuration",
                f"Target '{target_col}' has {nunique} distinct values; confirm it is a label.",
                target=target_col)
    else:
        caps["ml_classification"] = _cap(
            "unavailable", "No label/target column detected — supervised learning is not possible.")
        caps["ml_regression"] = _cap(
            "unavailable", "No target column detected — supervised learning is not possible.")

    caps["ml_clustering"] = (
        _cap("available", f"{len(numeric_cols)} numeric feature(s) for clustering.")
        if len(numeric_cols) >= 2
        else _cap("unavailable", "Clustering needs at least two numeric feature columns.")
    )
    caps["ml_anomaly"] = (
        _cap("available", "Unsupervised anomaly detection on numeric features.")
        if len(numeric_cols) >= 2
        else _cap("unavailable", "Anomaly detection needs at least two numeric feature columns.")
    )
    caps["forecasting"] = (
        _cap("available", f"Time column '{time_col}' with {n} rows supports naive/trend forecasting.")
        if time_col and n >= 30 else
        _cap("unavailable", "Forecasting needs a time column and at least 30 rows.")
    )

    # financial module (spec #10)
    src = _has_role(semantic_map, "source_account")
    dst = _has_role(semantic_map, "destination_account")
    amt = _has_role(semantic_map, "amount_source") or _has_role(semantic_map, "amount_destination")
    if src and dst:
        caps["transaction_summary"] = _cap(
            "available", f"Source ('{src}') and destination ('{dst}') account columns detected.")
        caps["transfer_network"] = _cap(
            "available", f"Directed edges from '{src}' to '{dst}'.", source=src, destination=dst)
    else:
        missing = [r for r, c in (("source account", src), ("destination account", dst)) if not c]
        caps["transaction_summary"] = (
            _cap("available", "Amount column detected; totals can be computed.") if amt else
            _cap("unavailable", f"Missing: {', '.join(missing)} and no amount column. "
                                "Map columns manually to enable this."))
        caps["transfer_network"] = _cap(
            "unavailable",
            f"Cannot infer {' and '.join(missing)} columns. Map them manually to enable network analysis.")
    if amt:
        caps.setdefault("transaction_summary", _cap("available", "Amount column detected."))
        caps["currency"] = _cap("available", "Amount column(s) present for currency analytics.")
    else:
        caps["currency"] = _cap("unavailable", "No monetary amount column was detected.")

    cur_src = _has_role(semantic_map, "currency_source")
    cur_dst = _has_role(semantic_map, "currency_destination")
    fx = _has_role(semantic_map, "fx_rate")
    if cur_src or cur_dst:
        caps["fx"] = _cap(
            "available with limitations" if not fx else "available",
            "Historical rates embedded in transaction rows only — no live feed is configured."
            if not fx else "FX rate column detected; historical analysis is possible.",
            currencies=[c for c in (cur_src, cur_dst) if c])
    else:
        caps["fx"] = _cap("unavailable", "No currency code columns detected.")

    recon = any(re.search(r"reconcil|expected_settlement|observed_settlement", c.name, re.I)
                for c in columns)
    caps["reconciliation"] = (
        _cap("available", "Reconciliation columns detected.") if recon else
        _cap("unavailable",
             "No reconciliation fields (expected/observed settlement) — this analysis requires "
             "additional columns rather than manufactured results."))

    status_col = _has_role(semantic_map, "status")
    caps["payments"] = (
        _cap("available", f"Status column '{status_col}' supports success/failure analytics.")
        if status_col else _cap("unavailable", "No payment status column detected."))

    caps["assistant"] = _cap(
        "available" if n else "unavailable",
        "Rule-based analytical assistant over persisted results (no external LLM configured).")
    return caps
