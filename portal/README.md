# Control Plane — report templates & admin portal

A React + Vite single-page console for managing this project's report
templates instead of hand-rolling `curl` calls against
[`../api`](../api)'s `/api/v1/reports` endpoints: a template gallery,
per-template rendering ("Preview"), auto-generated integration snippets
(curl/JavaScript/Python) with the real `report_id` filled in, best-effort
parameter detection, and batch (many-contexts-at-once) rendering.

Signed-in users who hold at least one `*:manage` permission also get an
**Admin** mode (a mode switch appears in the header): users, dynamic
per-organization roles and permission grants, organizations, an embedded
Swagger/OpenAPI explorer, live host resource monitoring (CPU/RAM/disk/
threads), and a reserved Plugins page. See `src/admin/` for that half of
the app — it's a client of the same `api` service's `/api/v1/{users,
roles,organizations,grants,permissions,system}` endpoints, following the
exact same fetch-client pattern as the template gallery (`src/api.ts`).

It has no server-side logic of its own — it's a browser-side client of
the `api` service's public HTTP API, nothing more. That's why it's a
separate, independently deployable/scalable instance from `api`: the
built app is static files served by nginx (see [`Dockerfile`](Dockerfile),
a multi-stage build — Node only exists in the build stage, the runtime
image is `nginx:alpine` + a few hundred KB of static assets, versus the
~1.7GB `api` image needs for LibreOffice/Tesseract/ICU).

## Develop

```bash
npm install
npm run dev       # http://localhost:5173, hot-reloading
```

Point it at your `api` instance — see Configuration below. If `api` runs
on a different origin than the portal's dev server, add that origin
(`http://localhost:5173`) to `api`'s `CORS_ALLOWED_ORIGINS`.

## Build

```bash
npm run build      # type-checks, then bundles to dist/
npm run preview    # serve the built dist/ locally
```

## Configuration

[`public/config.js`](public/config.js) is loaded before the app bundle
and deliberately kept out of it, so the API base URL can be changed on a
deployed instance (edit the file, or bind-mount over it) without a
rebuild:

```js
window.PORTAL_API_BASE_URL = "http://localhost:8000";
```

Leave it `""` for same-origin deployments (e.g. both services served
from behind the same reverse-proxy host) — API calls then resolve
relative to the portal's own origin instead of a separate one.

### Date and time display

How the portal *shows and asks for* dates and times — the run page's filters and
the Parameters tab's default-value editor — is chosen here too, once per
deployment. Values are still stored and sent to the API in ISO form
(`2026-09-30`, `08:30`, `2026-09-30T08:30`); only what a person sees and types
changes (see [`src/dateFormat.ts`](src/dateFormat.ts)):

```js
window.PORTAL_DATE_FORMAT = "DD/MM/YYYY";              // default
window.PORTAL_TIME_FORMAT = "HH:mm";                   // default; "hh:mm A" for 12-hour
window.PORTAL_DATETIME_FORMAT = "DD/MM/YYYY HH:mm";    // default: the date format, a space, the time format
```

Tokens: `YYYY` `YY` `MM` `DD` `HH` (00–23) `hh` (01–12, needs `A`) `mm` `ss` `A` (AM/PM);
everything else is copied as is. A format that can't be used (a date format
missing its month, say) is logged to the console and the default is used.
Typing is forgiving — any punctuation separates the parts, and a pasted ISO
date works.

### Branding

The same `config.js` mechanism white-labels the portal's chrome (see
[`src/branding.ts`](src/branding.ts)) — every field is optional and
defaults to a neutral identity, not this project's own, so a fork that
leaves this block out gets a generic console rather than someone else's
product name:

```js
window.PORTAL_BRAND_NAME = "Acme Ops Console";      // default: "Control Plane"
window.PORTAL_PRODUCT_NAME = "Fulfillment";         // default: unset (nothing extra renders)
window.PORTAL_LOGO_URL = null;                      // default: a built-in abstract mark
window.PORTAL_BRAND_MARK = null;                    // default: unset; set a 2-5 letter acronym (e.g. "AKBI") to draw it as the logo monogram instead of the abstract mark
window.PORTAL_TAGLINE = "internal tools";           // short, shown under the wordmark (top bar + sign-in screen)
window.PORTAL_DESCRIPTION = "Sign in to continue."; // shown on the sign-in screen
window.PORTAL_REPO_URL = "https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi";
window.PORTAL_LICENSE_NAME = "MIT";
```

`PORTAL_PRODUCT_NAME` is a secondary label for the deployment's own
module/product name, separate from `PORTAL_BRAND_NAME` — useful when an
org's brand and what they call this particular console aren't the same
word. It's shown next to the brand in the top bar's wordmark (after a
thin divider) and in the About panel (the info icon in the top bar);
leave it unset and neither renders.

This repo's own [`config.js`](public/config.js) sets all three:
`PORTAL_BRAND_NAME = "Aksor Khmer BI"` (the platform),
`PORTAL_PRODUCT_NAME = "Control Plane"` (this console, specifically), and
`PORTAL_TAGLINE = "Business Intelligence"` (spelling out what "BI"
stands for, shown under the wordmark) — `PORTAL_LOGO_URL` stays unset,
and `PORTAL_BRAND_MARK = "AKBI"` draws the acronym as the logo monogram
(stacked "AK" / "BI" once it's 4+ letters, so it stays legible in the
small mobile logo square) in place of the built-in abstract mark.

The footer (always visible, across every view) always credits
"Aksor Khmer BI", the license, the build version, and a "Contribute" link
back to `PORTAL_REPO_URL` regardless of how the header is rebranded — the
point is a rebrandable *product* on top of attributed, still-discoverable
*open-source* origins, not license laundering.

That name is a constant in [`src/components/Footer.tsx`](src/components/Footer.tsx),
deliberately *not* a `config.js` option: Aksor Khmer BI is a community
project, so a deployment can rebrand its own header but not the project
credit.

The same goes for the About dialog's "Support this project" block (email,
phone, Telegram, and the KHQR donation code): those live in
[`src/support.ts`](src/support.ts) (the QR image is
[`src/assets/aba-khqr.jpg`](src/assets/aba-khqr.jpg)) and are compiled into
the build, so an installed portal can't be pointed at different contact or
donation details through `config.js` or by swapping a file in `public/`. To
change them, edit that file and rebuild.

## Run (Docker)

```bash
docker compose -p aksor-app up -d --build portal   # the portal alone; ./deployment.sh up for everything
# open http://localhost:8080
```

## Auth

The console signs in at `api`'s `POST /api/v1/auth/login` and then carries a short-lived
**access token** (a JWT, 15 minutes) as `Authorization: Bearer …` on every call. The token lives
**only in memory** — never `localStorage` or `sessionStorage` — so a reload, or another tab, gets a
fresh one from the **refresh token**, an `HttpOnly` cookie the browser keeps and JavaScript can't read
(sent only to `/api/v1/auth/*`). [`src/api.ts`](src/api.ts) renews the token shortly before it expires
(and once, transparently, if a call ever answers `401`), takes turns across tabs with a Web Lock so two
tabs don't present the same cookie, and signs every tab out when one signs out. "Keep me signed in"
keeps the session for weeks instead of a working day; Settings → Active Sessions lists the places the
account is signed in and signs any of them out at once.

The portal and the API must be on the **same site** (the cookie is `SameSite=Lax`; `localhost` and
`127.0.0.1` count as different sites) and `api`'s `CORS_ALLOWED_ORIGINS` must name the portal's exact
origin. The full design, configuration and security model are in
[`../docs/authentication.md`](../docs/authentication.md); the server side is
[`../api/app/auth.py`](../api/app/auth.py), [`../api/app/auth_tokens.py`](../api/app/auth_tokens.py) and
[`../api/app/routers/auth.py`](../api/app/routers/auth.py). The console's own screens sit behind this
sign-in, but the underlying API stays open for reading (`GET /reports`, `GET /reports/{id}/schema`) and
rendering (`POST /reports/{id}/render[/batch]`) — only registering, editing, replacing, and deleting
templates require it.

Admin mode itself is gated client-side on the caller's effective
permissions (the sign-in answer's `org_id`/`is_superuser`/`permissions`)
purely to decide what to *show*; every admin action is still independently
authorized server-side by the endpoint it calls — which also re-reads the
user's roles on every request — so a hidden nav item was never the actual
security boundary.

## Stack notes

Plain global CSS (no Tailwind/CSS-in-JS), no router (the app is a
handful of views — gallery, template detail, batch render, and the
admin sections — switched on a lightweight `hashchange` listener in
[`src/hooks.ts`](src/hooks.ts) so both a template and an admin section
are linkable, e.g. `#/reports/<id>` or `#/admin/users`), and
[`prism-react-renderer`](https://github.com/FormidableLabs/prism-react-renderer)
for the syntax-highlighted integration snippets — the only real
dependency beyond React itself. The JSON context editor is a plain
`<textarea>` with client-side `JSON.parse` validation rather than a full
code-editor component, to keep the dependency surface small.
