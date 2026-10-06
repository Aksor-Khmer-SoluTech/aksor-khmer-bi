// Runtime configuration — loaded before the app bundle, so this can be
// edited (or bind-mounted/replaced) on a deployed instance without a
// rebuild. See ../README.md.
window.PORTAL_API_BASE_URL = "http://localhost:8000";

// Branding — the portal ships with a neutral "Control Plane" identity by
// default (see ../src/branding.ts); a fork that leaves this block out gets
// that generic console untouched. This repo is the Aksor Khmer platform's
// own deployment, so it opts in: "Aksor Khmer BI" is the brand, "Control
// Plane" is PORTAL_PRODUCT_NAME (this console's own module name, shown
// next to the brand in the top bar and in the About panel), and
// PORTAL_TAGLINE spells out what "BI" stands for underneath both (also
// the eyebrow line above the wordmark on the sign-in screen).
window.PORTAL_BRAND_NAME = "Aksor Khmer";
// The logo square's monogram (Aksor Khmer BI -> AKBI); unset keeps the
// neutral built-in dial. Ignored if PORTAL_LOGO_URL is set.
window.PORTAL_BRAND_MARK = "AKBI";
window.PORTAL_PRODUCT_NAME = "Control Plane";
window.PORTAL_TAGLINE = "Business Intelligence";
window.PORTAL_DESCRIPTION = "Khmer documents. Under control.";

// Standard display formats for dates and times in the portal -- how a date,
// time or date-time reads on the run page and in the parameter editor. Values
// are still stored and sent to the API in ISO form (2026-09-30, 08:30); this
// only changes how they are shown and typed. Tokens: YYYY YY MM DD HH hh mm ss
// A (AM/PM); anything else is copied as is. Leave any of them out for the
// default: DD/MM/YYYY, HH:mm, and the two together.
window.PORTAL_DATE_FORMAT = "DD/MM/YYYY";
window.PORTAL_TIME_FORMAT = "HH:mm";
// window.PORTAL_DATETIME_FORMAT = "DD/MM/YYYY HH:mm";
