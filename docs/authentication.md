# Authentication and sessions

How people and programs prove who they are, how a sign-in lasts, and how it ends. This is the standard
**short-lived access token + rotating refresh token** flow, with sessions the server can revoke.

## The short version

| Who | How they authenticate | Lasts |
|---|---|---|
| **A person in the portal** | Signs in at `POST /api/v1/auth/login`. Gets an **access token** (a JWT, 15 minutes) kept in memory, and a **refresh token** in an `HttpOnly` cookie that quietly renews it. | A working day, or weeks with "Keep me signed in"; ends sooner on sign-out, password change or an admin disabling the account |
| **A script that manages Aksor** (create users, register templates…) | Either signs in the same way and uses the access token, or sends HTTP Basic (`curl -u user:password`) | Token: 15 minutes, renewable. Basic: each call stands alone |
| **An embedded report viewer** | An **API client** id and secret (an admin grants it specific reports) | Until the secret is rotated or the client is disabled; see [Embedding](building-a-report.md) |
| **Anyone, to read or render** | Nothing — `GET /reports`, `POST /reports/{id}/render` stay open by design | — |

The break-glass login (`PORTAL_USERNAME` / `PORTAL_PASSWORD`) and LDAP/Active Directory users go through the
same flow; only the password check differs.

**A directory user has no password in this application.** Their credential is whatever the directory (AD / LDAP)
says: no password hash is stored, an administrator can't set, reset or require a change of one (`400 Password is
managed by the user's identity provider`), the user can't change one from Settings (the control isn't shown, and the API
refuses it), and creating such a user with a password is rejected. A sign-in with a blank password is refused before the
directory is contacted, and the user name is escaped wherever it is placed into a bind DN or search filter. Changing
or resetting their password happens in the directory.

## How signing in works

```
Browser                                  API
  │  POST /auth/login {user, password}     │
  │ ─────────────────────────────────────► │  checks the password (and the 2FA code),
  │                                        │  opens a session
  │ ◄───────────────────────────────────── │
  │   body:   { access_token, expires_in, user }
  │   cookie: aksor_refresh=…  (HttpOnly, only sent to /api/v1/auth/*)
  │
  │  GET /anything   Authorization: Bearer <access token>      ← every call, ~15 minutes
  │ ─────────────────────────────────────► │  verifies the signature and expiry, checks the
  │                                        │  session is still live, reads the user's roles now
  │
  │  (shortly before expiry)
  │  POST /auth/refresh   (cookie)         │
  │ ─────────────────────────────────────► │  swaps the refresh token for a NEW one (rotation)
  │ ◄───────────────────────────────────── │  and mints a new access token
  │
  │  POST /auth/logout                     │  revokes the session, clears the cookie
```

| | Access token | Refresh token |
|---|---|---|
| What it is | A signed JWT (HS256) naming the user, organization and session | A long random string, stored by the server only as a SHA-256 |
| Where the browser keeps it | In the page's memory — never `localStorage` or `sessionStorage`; a reload gets a new one from the cookie | In an `HttpOnly` cookie JavaScript can't read, sent only to `/api/v1/auth/*` |
| Lifetime | 15 minutes (`ACCESS_TOKEN_TTL_SECONDS`) | The session's: 12 hours, or 30 days with "keep me signed in" |
| Carries permissions? | **No.** Every request re-reads the user's roles and permissions | — |
| Can be revoked? | Yes — through its session, on the very next request | Yes — it is the session's key |

Because the token names a *session* and permissions are looked up fresh on every request:

- signing out, "sign out other sessions", a password change, or an administrator disabling or locking the
  account ends access **immediately** — not when a token happens to expire;
- changing someone's roles applies to the token they already hold;
- the token never needs to be "re-issued" for a permission change.

## Using the API with a token

```bash
API=http://localhost:8000/api/v1

# 1. Sign in. -c saves the refresh cookie; the answer holds the access token.
curl -s -c jar.txt -X POST $API/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"correct horse battery"}' > login.json
TOKEN=$(jq -r .access_token login.json)

# 2. Call anything with it.
curl -s $API/auth/me -H "Authorization: Bearer $TOKEN"

# 3. Before it expires (15 minutes), get a new one. The cookie jar is read AND rewritten:
#    the refresh token rotates every time.
curl -s -b jar.txt -c jar.txt -X POST $API/auth/refresh -H 'X-Aksor-Client: my-script' \
  | jq -r .access_token

# 4. Sign out.
curl -s -b jar.txt -c jar.txt -X POST $API/auth/logout -H 'X-Aksor-Client: my-script'
```

`login` accepts `"remember": true` (keep the session for 30 days instead of 12 hours) and `"totp_code"`
(see below). The answer never contains the refresh token — only the cookie does.

For a short script, **HTTP Basic is simpler** and still works: `curl -u alice:password $API/users/me`. See
[HTTP Basic, for scripts](#http-basic-for-scripts).

## Staying signed in: refresh and rotation

The portal renews the access token by itself, with a fifth of its lifetime left, and again if a call ever
comes back `401`. You don't do anything.

**Each refresh token works once.** Using it swaps it for a new one. This is what makes a stolen cookie
detectable:

- The thief and the owner both hold the same token. Whoever uses it second presents a token that has
  already been replaced.
- That is treated as theft: **the whole session is revoked** and both must sign in again.
- A **10-second grace window** (`REFRESH_GRACE_SECONDS`) forgives the harmless version — two browser tabs
  refreshing at the very same moment with the same cookie. The late request is answered with a fresh access
  token and the cookie is left alone.

The session's total length is fixed when you sign in; refreshing never extends it. When it ends you sign in
again.

## Ending a session

| What happens | Effect |
|---|---|
| You sign out | This session ends; the cookie is cleared; other tabs of the portal sign out too |
| **Settings → Active Sessions** → *Sign out* | That one session ends at once |
| *Sign out N other sessions* (same screen) | Everything except the session you're using |
| You change your password | Every **other** session ends; this one carries on |
| An administrator resets your password, deactivates or locks your account, or clears your 2FA | **Every** session ends |
| An administrator changes your roles | Nothing ends; the new permissions apply on your next request |
| You answer a new-sign-in alert with **Not me** | That session ends (see below) |
| A refresh token is replayed | That session ends (see above) |
| The session's lifetime runs out | You sign in again |

A **locked** account can't sign in at all (it used to be recorded but not enforced). A user removed from an
LDAP directory keeps working until their session ends or an administrator deactivates them here — the
directory is consulted when someone signs in, not on every request.

## New sign-in alerts

When your account signs in on a browser that has never signed in to it before, the bell in the top bar asks you
**Was this you?** It asks on your *other* signed-in browsers only; whoever is on the new one never sees the
question and can't dismiss it.

- **It was me** dismisses the alert.
- **Not me — sign it out** ends that session at once. The portal then offers **Change password**, which keeps
  whoever it was from simply signing in again, and **Review sign-in activity** (Settings → Authentication Log).

A browser is recognised by a random id in a long-lived cookie (`aksor_device`, HttpOnly, sent only to `/api/v1/auth`;
the server keeps just its SHA-256), not by its IP address or browser version. A new network or a browser update is
not a new device, but a private window, another browser profile, or cleared cookies are. An account's very first
sign-in raises no alert. The bell checks again every minute and whenever you return to the tab.

Alerts are on by default; each person can turn them off under **Settings → Notifications**. They appear in the
portal only: Aksor doesn't send email. Answers are recorded in the audit log (`auth.signin_confirmed`,
`auth.signin_disowned`).

## Two-factor authentication

The authenticator-app secret is stored **encrypted** (the same Fernet key as saved credentials — see
`SECRETS_ENCRYPTION_KEY` in [Deployment](deployment.md)). Secrets saved by an older version are encrypted in place
the next time the API starts. If the key is ever lost, those accounts can't pass the code check until an
administrator clears their 2FA (Manage → Users → reset), and the user enrols again.

An account with 2FA is asked for the code at sign-in: `POST /auth/login` answers `401` with
`{"detail": "2FA_REQUIRED"}`, and you send the same request again with `"totp_code": "123456"`.

2FA now guards the **whole account**, not just the form. An account that has it **cannot authenticate with
HTTP Basic** on any other route, because a script can't supply the code — so knowing the password alone gets
nobody anywhere. The only way to a session is through `/auth/login` and its code. A script that needs access
should have its **own service account** (a local user without 2FA holding only the permissions the script
needs), or — to run reports — an API client.

(`GET /auth/verify`, the older password-check endpoint, still asks for the code only when called with
`login=true`, and opens no session.)

## HTTP Basic, for scripts

`Authorization: Basic …` (what `curl -u user:password` sends) is still accepted on every route. The credential
is a header the client attaches by itself, not an ambient cookie, so it carries no cross-site request risk.

Its limits:

- It sends the password on every call, so TLS is mandatory (see [Deployment](deployment.md)).
- It does a password check (bcrypt, or an LDAP bind) per call — fine for scripts, wasteful for a busy client.
  Signing in once and using the token is cheaper.
- Accounts with 2FA can't use it (above).
- It can be turned off entirely with `AUTH_ALLOW_BASIC=false`. Then every client must use `/auth/login`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET` | *(generated)* | The key access tokens are signed with — 32+ characters. Unset: a random key is generated into `data/secrets/jwt.key` on first use (mode 0600, mounted by `docker-compose.yml`). **Set it explicitly when you run more than one `api` replica**, so they all accept each other's tokens. Changing or losing it signs everyone out and nothing else |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | Access-token lifetime (60–3600). Shorter = a stolen token is useful for less time, more refreshes |
| `REFRESH_TOKEN_SESSION_HOURS` | `12` | Session length without "keep me signed in" (1–72) |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | Session length with it (1–180) |
| `REFRESH_GRACE_SECONDS` | `10` | How long a just-replaced refresh token is forgiven for two tabs racing (0–60) |
| `LOGIN_ATTEMPTS_PER_MINUTE` | `10` | Sign-in attempts per minute for one client address and user name (and 5× that per address) before `429` |
| `AUTH_ALLOW_BASIC` | `true` | Accept HTTP Basic on API calls. `false` forces `/auth/login` |
| `AUTH_COOKIE_SECURE` | `auto` | `auto`: the cookie is `Secure` when the request came over HTTPS (or a proxy said so with `X-Forwarded-Proto`). `true` / `false` to force |
| `AUTH_COOKIE_SAMESITE` | `lax` | `lax`, `strict`, or `none` (needs HTTPS; see below) |
| `CORS_ALLOWED_ORIGINS` | — | The portal's origin(s). Also the list the refresh and logout routes accept an `Origin` from |
| `PORTAL_USERNAME` / `PORTAL_PASSWORD` | — | The built-in admin: a one-time password for the first sign-in, which becomes your administrator account (see [Deployment](deployment.md)); afterwards an emergency key under a different user name |

## Deploying it

**The portal and the API must be on the same *site*.** The refresh cookie is `SameSite=Lax`, so the browser
only sends it when the page and the API share a registrable domain. Ports and subdomains don't matter:

| Portal | API | Works? |
|---|---|---|
| `http://localhost:8080` | `http://localhost:8000` | Yes |
| `https://reports.example.com` | `https://api.example.com` | Yes (same site, `example.com`) |
| `https://reports.example.com` | `https://reports.example.com/api` (one reverse proxy) | Yes, and the simplest |
| `https://portal.a.com` | `https://api.b.com` | Only with `AUTH_COOKIE_SAMESITE=none` and HTTPS — or put both behind one domain |
| `http://localhost:8080` | `http://127.0.0.1:8000` | **No** — `localhost` and `127.0.0.1` are different sites. Use `localhost` for both |

**TLS.** Cookies and tokens need HTTPS on anything beyond a trusted network. When a proxy terminates TLS,
make it send `X-Forwarded-Proto: https` so the cookie is marked `Secure` (or set `AUTH_COOKIE_SECURE=true`).

**The cookie's path.** It is scoped to `/api/v1/auth`, so a reverse proxy must serve the API at that same path (don't rewrite `/api/v1` away or move it under a prefix).

**CORS.** `CORS_ALLOWED_ORIGINS` must list the portal's exact origin — it is what lets the browser send the
cookie to `/auth/*` at all (the API answers `Access-Control-Allow-Credentials: true`, which browsers refuse
with a `*` origin).

**Several API replicas.** Share `JWT_SECRET` (a token minted by one must verify on another) and one database
(sessions live there). Nothing else is sticky.

**Local development** (`npm run dev` on `localhost:5173`, API on `localhost:8000`): add
`http://localhost:5173` to `CORS_ALLOWED_ORIGINS`.

**Backups.** Sessions are in the database (`auth_sessions`); the signing key is in `data/secrets/jwt.key`
unless you set `JWT_SECRET`. Losing either only signs people out.

## What protects what

| Threat | Defence |
|---|---|
| A script injected into the page (XSS) reads the credential | The access token is only in memory and lives minutes; the refresh token is in an `HttpOnly` cookie JavaScript can't read. (XSS can still *act* as the user while the page is open, so keep untrusted HTML out of the console — React escapes what it renders) |
| Another site makes the browser call refresh/logout (CSRF) | Those two routes need a custom header (forces a CORS preflight), an allowed `Origin`, and the cookie is `SameSite=Lax`. Every other route needs the `Authorization` header, which a foreign page can't attach |
| A refresh cookie is stolen | Rotation: using it second revokes the session. Only its hash is stored. It is scoped to `/api/v1/auth` |
| A leaked database | Refresh tokens are stored as SHA-256 hashes and passwords as bcrypt, so neither can be replayed or read. Authenticator-app (2FA) secrets and saved credentials are **encrypted** with `SECRETS_ENCRYPTION_KEY` (or `data/secrets/master.key`), which is not in the database — a copy of the database alone yields none of them. Back the key up with the database; lose it and users must re-enrol 2FA (an administrator clears it under Manage → Users) |
| A forged or altered token | HS256 only — the header's `alg` is never trusted (`none` and key-confusion tricks are refused); the signature, issuer, type and expiry are all checked |
| Someone keeps access after being removed | Every request re-checks the session and the user (active, unlocked, current roles) |
| Password guessing | `/auth/login` (and `/auth/verify`) are throttled to `LOGIN_ATTEMPTS_PER_MINUTE` (10) per client address and user name, and 5× that per address; over it, `429` with `Retry-After`. Failed sign-ins are logged (Authentication Log; the security feed). The counters are per API process, and HTTP Basic on *other* routes is not throttled — so on an internet-facing API also set `AUTH_ALLOW_BASIC=false` and rate-limit `/auth/login` at the proxy |

Not covered: a compromised browser or machine, and an attacker who can already run code on the server (they
can read the signing key and the encryption key).

## The `/auth` routes

| Method and path | Needs | Does |
|---|---|---|
| `POST /api/v1/auth/login` | — | Password (+ 2FA code) → access token, refresh cookie |
| `POST /api/v1/auth/refresh` | the cookie, `X-Aksor-Client` header | Rotates the cookie, new access token |
| `POST /api/v1/auth/logout` | `X-Aksor-Client` header | Revokes the session, clears the cookie |
| `GET /api/v1/auth/me` | a token (or Basic) | Who you are and your permissions |
| `GET /api/v1/auth/sessions` | a token (or Basic) | Your live sessions, the current one marked |
| `DELETE /api/v1/auth/sessions/{id}` | a token | Sign one of your sessions out |
| `POST /api/v1/auth/sessions/revoke-others` | a token | Sign out all but this one |
| `GET /api/v1/auth/verify` | Basic | Check a username and password (for scripts); no session |
| `GET /api/v1/users/me/notifications` | a token | Your unanswered new-sign-in alerts (never the one about this session) |
| `POST /api/v1/users/me/notifications/{id}/ack` | a token | "It was me" |
| `POST /api/v1/users/me/notifications/{id}/sign-out` | a token | "Not me": signs that session out |

Swagger (`/docs`): **Authorize** offers both schemes. Sign in with `/auth/login` there, then paste the
`access_token` into *HTTPBearer*.

## Upgrading from the Basic-only portal

- Everyone signs in once more after the upgrade (the portal no longer keeps a password in the browser).
- Run the migration (`alembic upgrade head`, automatic in Docker): it adds the `auth_sessions` table. (An existing database created by an earlier revision needs the one-off repair under *Migrations were squashed* in [Deployment](deployment.md).)
- Scripts using `curl -u user:password` **keep working**, with one exception: accounts that have 2FA can no
  longer use Basic (see above). Give those scripts a service account.
- Set `CORS_ALLOWED_ORIGINS` to the portal's exact origin if it wasn't (it is now also what lets the cookie
  through), and make sure the portal and the API are the same site.
- Locked accounts are now actually refused at sign-in.

## Troubleshooting

| You see | Cause and fix |
|---|---|
| The portal signs you out on every reload | The refresh cookie isn't reaching the API: the portal and API are different sites (`localhost` vs `127.0.0.1`, or two unrelated domains), `CORS_ALLOWED_ORIGINS` doesn't match the portal's origin exactly, or the cookie is `Secure` while you use plain `http` (set `AUTH_COOKIE_SECURE=false` for a non-HTTPS test) |
| `401 Your session has expired -- sign in again` | The access token expired and the refresh failed — the session ended or was revoked. Sign in |
| `401 … its sign-in cookie was used twice` | A refresh token was replayed (or two clients shared one cookie jar) — the session was revoked on purpose. Sign in again |
| `400 Missing the X-Aksor-Client header` | A hand-written refresh or logout call. Add the header (any value) |
| `403 This origin isn't allowed` | The call's `Origin` isn't in `CORS_ALLOWED_ORIGINS` |
| `401 … two-factor authentication` on a script | The account has 2FA, so it can't use Basic. Use a service account, or `/auth/login` with a code |
| `401 Username/password authentication is turned off` | `AUTH_ALLOW_BASIC=false`: sign in with `/auth/login` and use the token |
| Everyone was signed out after a deploy | `JWT_SECRET` changed (or the key file wasn't kept). Expected once; keep it stable |
| `401 This account is locked` | An administrator locked it: Manage → Users |
| `429 Too many sign-in attempts` | More than `LOGIN_ATTEMPTS_PER_MINUTE` tries from one address for one user name; wait the `Retry-After` seconds |
