# Sign-in email: 6-digit code

Sign-in is passwordless: the app asks Supabase Auth to email a one-time
credential, the user types it, and Supabase decides whether it is live before
this app mints its own session cookie.

Supabase has two shapes for that email, and the shape is **template-driven**,
not an API flag (`POST /auth/v1/otp` is the same call either way):

| Template contains        | Email delivers        | UI path                    |
| ------------------------ | --------------------- | -------------------------- |
| `{{ .Token }}`           | a 6-digit code        | type it on the code step   |
| `{{ .ConfirmationURL }}` | a magic link          | open it, or paste it back  |

This project wants the **code**, because a code does not depend on the browser
being able to reach the redirect target (wrong port, mail scanner opening the
link, reading mail on a phone, corporate mail rewriting URLs).

The backend already supports both: `POST /api/auth/otp/verify` redeems a code
through `POST /auth/v1/verify`, and `POST /api/auth/supabase/redeem` redeems a
link token. Only the email body has to change.

## Dashboard (30 seconds)

Auth → Email Templates → **Magic Link** → replace the body with:

```html
<h2>Your sign-in code</h2>
<p>Enter this code to sign in to Aegis:</p>
<p style="font-size:28px;font-weight:600;letter-spacing:6px">{{ .Token }}</p>
<p>It expires in an hour and works once. If you did not request it, ignore this email.</p>
```

Subject: `Your sign-in code` (`mailer_subjects_magic_link`).

Leave `{{ .ConfirmationURL }}` **out** of the body: with both variables present
Supabase still sends a link, and the code stops being the obvious path. The
paste-a-link box on the sign-in page stays available for any email already in
an inbox.

## Same change via the Management API

Needs an account access token from <https://supabase.com/dashboard/account/tokens>
(not the project's anon or service-role key):

```bash
PROJECT_REF=your-project-ref
curl -X PATCH "https://api.supabase.com/v1/projects/$PROJECT_REF/config/auth" \
  -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mailer_subjects_magic_link": "Your sign-in code",
    "mailer_templates_magic_link_content": "<h2>Your sign-in code</h2><p>Enter this code to sign in to Aegis:</p><p style=\"font-size:28px;font-weight:600;letter-spacing:6px\">{{ .Token }}</p><p>It expires in an hour and works once.</p>"
  }'
```

Read the current value back with `GET` on the same URL and look at the
`mailer_templates_magic_link_content` key.

## Still true after the switch

- **The built-in mailer is a test sender**: 2 messages per hour and only to
  team-member addresses on hosted projects. Anything beyond a demo needs
  custom SMTP (Auth → SMTP Settings), otherwise sign-in fails with
  `email rate limit exceeded` — the API surfaces that as `429`.
- `SUPABASE_REDIRECT_TO` stops mattering for codes; it only affects the link
  form of the email.
- Code length comes from `OTP_LENGTH` (default 6) and the UI reads
  `otp_length` from `GET /api/auth/provider`.

## `429 email rate limit exceeded`

That error is not this app's cooldown — it is Supabase refusing to send because
the project's **built-in** mailer has spent its hourly quota (2 messages/hour on
hosted projects, only to team-member addresses). No query parameter or template
change lifts it, and waiting a few seconds never helps. The API now reports it
with `Retry-After: 3600` and a message that says so.

Three ways out, cheapest first:

1. **Wait** for the hourly window. Old links in the inbox still work.
2. **Use your own sender** — no dashboard change, no Supabase quota. Set the
   SMTP block and switch the provider:

   ```dotenv
   OTP_PROVIDER=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=you@gmail.com
   SMTP_PASSWORD=app-password-16-chars   # Google account → App passwords
   SMTP_FROM=you@gmail.com
   ```

   With `smtp` the app generates the code itself, stores only its hash, emails
   it, and verifies it locally with expiry / attempt limits / single use. Gmail's
   daily quota is thousands, so it does not come back in five minutes. Note the
   code lifetime then follows `OTP_TTL_SECONDS` (600), not
   `SUPABASE_OTP_TTL_SECONDS`.
3. **Add custom SMTP in Supabase** (Authentication → SMTP Settings) and raise
   Auth → Rate Limits → "Emails sent". Codes keep coming from Supabase, with a
   real quota.

For local work with no mail at all, `OTP_PROVIDER=dev_console` returns the code
in the `/api/auth/otp/request` response; the sign-in page shows it in a
"development mode" box and can fill it with one click.

Provider selection summary (`config.otp_provider()`):

| `OTP_PROVIDER` | Uses              | Falls back to detection when unusable |
| -------------- | ----------------- | ------------------------------------- |
| empty          | auto              | Supabase → SMTP → dev console         |
| `supabase`     | GoTrue            | yes, when URL/key are missing         |
| `smtp`         | our SMTP sender   | yes, when `SMTP_HOST`/`SMTP_FROM` are missing |
| `dev_console`  | response + log    | never — always available               |

A **failed** send no longer starts the 30s per-email cooldown: the request was
never delivered, so retrying is allowed immediately (and the provider still
rate-limits as it sees fit).
