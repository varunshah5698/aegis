"""Central application configuration.

All brand strings, limits and provider settings live here so the product
identity can be changed in one place (spec #3).
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
PROJECT_DIR = BASE_DIR.parent                              # repo root

# Load backend/.env (server-side only) before anything reads the environment.
# Real secrets never leave the backend: they are not VITE_-prefixed, not
# returned in API responses and never logged.
try:  # python-dotenv ships with the environment; fall back silently if absent
    from dotenv import load_dotenv as _load_dotenv

    _load_dotenv(BASE_DIR / ".env")
except Exception:  # pragma: no cover - optional dependency
    pass


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_int(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


# ---------------------------------------------------------------- brand ----
BRAND = {
    "name": env("BRAND_NAME", "Aegis"),
    "descriptor": env("BRAND_DESCRIPTOR", "AI Financial Intelligence"),
    "tagline": env("BRAND_TAGLINE", "Upload Your Data. Discover What Matters."),
    "auth_provider": env("BRAND_AUTH_PROVIDER", "Freebuff"),
}

# --------------------------------------------------------------- limits ----
MAX_UPLOAD_BYTES = env_int("MAX_UPLOAD_BYTES", 200 * 1024 * 1024)   # 200 MB
MAX_ROWS = env_int("MAX_ROWS", 500_000)
MAX_COLUMNS = env_int("MAX_COLUMNS", 1_000)
PREVIEW_ROWS = 25
SAMPLE_ROWS_FOR_EXPENSIVE = 50_000

# ------------------------------------------------------------- storage -----
DATA_DIR = Path(env("DATA_DIR", str(PROJECT_DIR / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
ARTIFACT_DIR = DATA_DIR / "artifacts"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = env("SQLITE_PATH", str(DATA_DIR / "finsentry.db"))

for _d in (UPLOAD_DIR, ARTIFACT_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DATABASE_URL = env("DATABASE_URL", f"sqlite:///{DB_PATH}")

# --------------------------------------------------------------- server ----
CORS_ORIGINS = [o.strip() for o in env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
SECRET_KEY = env("SECRET_KEY", "dev-insecure-secret-change-me")
SESSION_TTL_HOURS = env_int("SESSION_TTL_HOURS", 24 * 14)
WORKERS = env_int("ANALYSIS_WORKERS", 2)
# A stage that outlives this budget is abandoned and its run marked failed, so a
# hung pipeline can never leave the workspace spinning forever.
STAGE_TIMEOUT_SECONDS = env_int("STAGE_TIMEOUT_SECONDS", 900)

# ------------------------------------------------- external providers ------
# Never claim a provider is live unless it is actually configured (spec #18).
OPENAI_API_KEY = env("OPENAI_API_KEY", "")
LLM_MODEL = env("LLM_MODEL", "gpt-4o-mini")
EXCHANGE_RATE_API_KEY = env("EXCHANGE_RATE_API_KEY", "")
EXCHANGE_RATE_PROVIDER = env("EXCHANGE_RATE_PROVIDER", "")

# ------------------------------------------------- AI provider (Groq) ------
# All model traffic is server-side. The browser only ever sees our own API.
AI_ENABLED = env("AI_ENABLED", "true").lower() not in ("0", "false", "no")
AI_PROVIDER = env("AI_PROVIDER", "groq").strip().lower()
GROQ_API_KEY = env("GROQ_API_KEY", "")
GROQ_BASE_URL = env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
# Empty means "pick the best available chat model from the provider's live list".
AI_MODEL = env("AI_MODEL", "").strip()
AI_TIMEOUT_SECONDS = env_int("AI_TIMEOUT_SECONDS", 45)
AI_MAX_OUTPUT_TOKENS = env_int("AI_MAX_OUTPUT_TOKENS", 900)
AI_MAX_INPUT_CHARS = env_int("AI_MAX_INPUT_CHARS", 6000)
AI_RATE_LIMIT_PER_MINUTE = env_int("AI_RATE_LIMIT_PER_MINUTE", 20)
AI_MAX_RETRIES = env_int("AI_MAX_RETRIES", 2)


def _ai_key() -> str:
    """The active provider credential, resolved without ever printing it."""
    if AI_PROVIDER == "groq":
        return GROQ_API_KEY
    if AI_PROVIDER == "openai":
        return OPENAI_API_KEY
    return ""


def ai_configured() -> bool:
    return bool(AI_ENABLED and _ai_key())


def ai_base_url() -> str:
    if AI_PROVIDER == "openai":
        return env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return GROQ_BASE_URL


def llm_configured() -> bool:
    """True when any provider can phrase/summarise computed results."""
    return ai_configured() or bool(OPENAI_API_KEY)


def fx_provider_configured() -> bool:
    return bool(EXCHANGE_RATE_API_KEY and EXCHANGE_RATE_PROVIDER)


# Strength used for PBKDF2 password hashing (spec #21: secure hashing).
PBKDF2_ITERATIONS = env_int("PBKDF2_ITERATIONS", 390_000)

# ------------------------------------------- passwordless OTP (Freebuff) ---
# Email one-time passcodes are the primary sign-in. When no SMTP sender is
# configured the code is logged server-side and returned in the request
# response instead (keyless dev mode) — never in production with SMTP set.
OTP_LENGTH = env_int("OTP_LENGTH", 6)
OTP_TTL_SECONDS = env_int("OTP_TTL_SECONDS", 600)
OTP_MAX_ATTEMPTS = env_int("OTP_MAX_ATTEMPTS", 5)
OTP_REQUEST_COOLDOWN_SECONDS = env_int("OTP_REQUEST_COOLDOWN_SECONDS", 30)
OTP_MAX_ACTIVE_PER_EMAIL = env_int("OTP_MAX_ACTIVE_PER_EMAIL", 3)

# Explicit delivery choice: "supabase", "smtp" or "dev_console". Empty means
# auto-detect (Supabase wins when configured). This is the escape hatch when a
# provider is unusable — e.g. Supabase's built-in mailer is capped at a couple
# of messages per hour, and `OTP_PROVIDER=dev_console` keeps local sign-in
# working without an email, while `OTP_PROVIDER=smtp` sends our own code from
# the configured sender and never touches Supabase's mail quota.
OTP_PROVIDER_PREFERENCE = env("OTP_PROVIDER", "").strip().lower()

SMTP_HOST = env("SMTP_HOST", "")
SMTP_PORT = env_int("SMTP_PORT", 587)
SMTP_USER = env("SMTP_USER", "")
SMTP_PASSWORD = env("SMTP_PASSWORD", "")
SMTP_FROM = env("SMTP_FROM", "")
SMTP_USE_TLS = env("SMTP_USE_TLS", "true").lower() not in ("0", "false", "no")


def email_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


# ------------------------------------------- Supabase Auth (real email OTP) --
# Supabase Auth (GoTrue) delivers and verifies the passcode; this app only
# exchanges a verified token for its own session cookie. The publishable key is
# browser-safe, but it is still read server-side only — the browser never talks
# to Supabase here, so the key is never bundled or shipped to a client.
def _supabase_project_url() -> str:
    """Project base URL, tolerating a pasted REST endpoint (``…/rest/v1``)."""
    raw = env("SUPABASE_URL") or env("VITE_SUPABASE_URL")
    return raw.split("/rest/v1")[0].rstrip("/")


SUPABASE_URL = _supabase_project_url()
SUPABASE_KEY = (env("SUPABASE_PUBLISHABLE_KEY") or env("SUPABASE_ANON_KEY")
                or env("VITE_SUPABASE_PUBLISHABLE_KEY")).strip()
SUPABASE_TIMEOUT_SECONDS = env_int("SUPABASE_TIMEOUT_SECONDS", 20)
# Must match the project's Auth → Email OTP Expiry so the UI countdown is true.
SUPABASE_OTP_TTL_SECONDS = env_int("SUPABASE_OTP_TTL_SECONDS", 3600)
# Where the emailed sign-in link lands. Supabase only honours a redirect whose
# scheme+host match the project's Site URL (the port is ignored for loopback),
# so this must share the host with Site URL or the link falls back to it — and
# if Site URL points at a port nothing serves, the browser shows
# ERR_CONNECTION_REFUSED. This is the page that finishes the sign-in.
SUPABASE_REDIRECT_TO = env("SUPABASE_REDIRECT_TO", "http://localhost:5173/auth/callback")


def supabase_auth_configured() -> bool:
    return bool(SUPABASE_URL.startswith("http") and SUPABASE_KEY)


def otp_provider() -> str:
    """Which component actually delivers passcodes right now.

    ``OTP_PROVIDER`` overrides the auto-detection, but only to a provider that
    can actually work: asking for ``smtp`` without a sender (or ``supabase``
    without a URL/key) falls back to detection instead of failing sign-in.
    """
    pref = OTP_PROVIDER_PREFERENCE
    if pref == "dev_console":
        return "dev_console"              # always available, deliberately
    if pref == "supabase" and supabase_auth_configured():
        return "supabase"
    if pref == "smtp" and email_configured():
        return "smtp"
    if supabase_auth_configured():
        return "supabase"
    return "smtp" if email_configured() else "dev_console"


def otp_ttl_seconds() -> int:
    """Lifetime of a delivered passcode, from whichever provider owns it."""
    return SUPABASE_OTP_TTL_SECONDS if otp_provider() == "supabase" else OTP_TTL_SECONDS


# ------------------------------------------------- workspace billing ------
# Admin area access: comma-separated emails that may view the admin console.
# Empty in dev, so /api/admin/* returns 403 for everyone until configured.
ADMIN_EMAILS = {e.strip().lower() for e in env("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin_email(email: str) -> bool:
    return email.strip().lower() in ADMIN_EMAILS


# Checkout plans (USD). Demo checkout records the order as paid immediately;
# wire a real provider webhook here before accepting live payments.
PLANS = {
    "starter": {"name": "Starter", "amount_cents": 0},
    "professional": {"name": "Professional", "amount_cents": 2900},
    "business": {"name": "Business", "amount_cents": 9900},
}
