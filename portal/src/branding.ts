// Runtime white-label config — same pre-bundle window-global mechanism
// public/config.js already uses for PORTAL_API_BASE_URL (see api.ts), so a
// deployed instance can be rebranded by editing/bind-mounting config.js,
// no rebuild required. Every field defaults to a neutral "Control Plane"
// identity rather than any one deployment's own name — see
// portal/README.md's Branding section — so a fork that changes nothing
// gets a generic console, not someone else's product name.
declare global {
  interface Window {
    PORTAL_BRAND_NAME?: string;
    PORTAL_PRODUCT_NAME?: string;
    PORTAL_LOGO_URL?: string;
    PORTAL_BRAND_MARK?: string;
    PORTAL_TAGLINE?: string;
    PORTAL_DESCRIPTION?: string;
    PORTAL_REPO_URL?: string;
    PORTAL_LICENSE_NAME?: string;
  }
}

export const branding = {
  name: window.PORTAL_BRAND_NAME || "Control Plane",
  // Secondary label for the deployment's own module/product name, shown
  // under the brand in the sidebar and the About panel — separate from
  // `name` because a white-label org's brand and the console's own name
  // for itself aren't always the same word. Unset (not a second generic
  // string) is the fork-safe default: nothing extra renders until a
  // deployment opts in.
  productName: window.PORTAL_PRODUCT_NAME || null,
  logoUrl: window.PORTAL_LOGO_URL || null,
  // A short acronym (2-5 letters, e.g. "AKBI") drawn as a monogram in
  // the logo square when no `logoUrl` is set -- see BrandMark.tsx. Unset
  // keeps the neutral built-in dial, same fork-safe default as the other
  // fields: nothing brand-specific renders until a deployment opts in.
  mark: window.PORTAL_BRAND_MARK?.trim() || null,
  tagline: window.PORTAL_TAGLINE || "admin console",
  description: window.PORTAL_DESCRIPTION || "Sign in to continue.",
  // Contact + donation details (the About dialog's "support this project"
  // section) are deliberately NOT configurable here -- see support.ts.
  repoUrl: window.PORTAL_REPO_URL || "https://github.com/Aksor-Khmer-SoluTech/aksor-khmer-bi",
  licenseName: window.PORTAL_LICENSE_NAME || "MIT",
};
