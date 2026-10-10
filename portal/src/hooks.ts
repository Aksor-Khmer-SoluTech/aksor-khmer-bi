import { useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react";

export type AdminSection =
  | "dashboard"
  | "users"
  | "roles"
  | "clients"
  | "connections"
  | "jdbc-drivers"
  | "secrets"
  | "access-review"
  | "audit"
  | "protected-terms"
  | "organizations"
  | "ldap"
  | "jobs"
  | "api"
  | "monitor"
  | "plugins"
  | "resources";
const ADMIN_SECTIONS: AdminSection[] = [
  "dashboard",
  "users",
  "roles",
  "clients",
  "connections",
  "jdbc-drivers",
  "secrets",
  "access-review",
  "audit",
  "protected-terms",
  "organizations",
  "ldap",
  "jobs",
  "api",
  "monitor",
  "plugins",
  "resources",
];

export type Route =
  // "gallery" is the Templates screen (register + integrate); "reports" is
  // the end-user list of reports the signed-in user was granted -- see
  // ReportsPage.tsx. "detail" (#/reports/<id>) stays a template's own page.
  // #/home -- everyone's own dashboard (HomePage.tsx), where an empty hash lands.
  | { view: "home" }
  | { view: "gallery" }
  // #/templates/new[/<id>] -- the New report wizard (NewReportWizard.tsx); with an id, continuing that draft.
  | { view: "new-report"; id?: string }
  | { view: "reports" }
  // #/runs and #/starred -- a person's own run history and starred reports (top-bar pages, MyRunsPage /
  // StarredPage).
  | { view: "runs" }
  | { view: "starred" }
  // #/reports/<id>/run -- the end-user run page (RunReportPage.tsx).
  | { view: "run"; id: string }
  // `tab` is the tab's URL slug (#/reports/<id>/history); absent means the
  // Overview, which is the default and has no suffix. TemplateDetail owns which
  // slugs exist and falls back to Overview for one it doesn't recognise.
  | { view: "detail"; id: string; tab?: string }
  | { view: "batch" }
  | { view: "schedules" }
  // #/docs/<guide>[/<heading-id>] -- the in-app guides (DocsPage.tsx).
  | { view: "docs"; slug?: string; anchor?: string }
  | { view: "admin"; section: AdminSection }
  // Chrome-less, unauthenticated report viewer meant to be loaded in a
  // third party's <iframe> (see EmbedPage.tsx) -- not reachable via any
  // in-app nav, only ever landed on directly by URL. Query params live
  // inside the hash (`#/embed/<id>?context=...`), same as the rest of
  // this router's state, and are parsed by EmbedPage itself rather than
  // threaded through this generic Route -- no other view needs them.
  | { view: "embed"; id: string };

function parseHash(hash: string): Route {
  // Split off `?...` before route-matching so an embed URL's query
  // string (inside the hash) never leaks into a `[^/]+` capture group.
  const [path] = hash.replace(/^#\/?/, "").split("?");
  if (path === "reports" || path === "reports/") return { view: "reports" };
  if (path === "batch") return { view: "batch" };
  if (path === "schedules") return { view: "schedules" };
  // Resources (folders and images) moved into the Admin console; keep the old link working.
  if (path === "resources") return { view: "admin", section: "resources" };
  if (path === "home") return { view: "home" };
  if (path === "runs") return { view: "runs" };
  if (path === "starred") return { view: "starred" };
  if (path === "templates") return { view: "gallery" };
  const newReportMatch = /^templates\/new(?:\/([^/]+))?\/?$/.exec(path);
  if (newReportMatch) return { view: "new-report", id: newReportMatch[1] && decodeURIComponent(newReportMatch[1]) };
  const docsMatch = /^docs(?:\/([^/]+)(?:\/([^/]+))?)?\/?$/.exec(path);
  if (docsMatch) {
    return {
      view: "docs",
      slug: docsMatch[1] && decodeURIComponent(docsMatch[1]),
      anchor: docsMatch[2] && decodeURIComponent(docsMatch[2]),
    };
  }
  const adminMatch = /^admin\/([^/]+)$/.exec(path);
  if (adminMatch && (ADMIN_SECTIONS as string[]).includes(adminMatch[1])) {
    return { view: "admin", section: adminMatch[1] as AdminSection };
  }
  const runMatch = /^reports\/([^/]+)\/run$/.exec(path);
  if (runMatch) return { view: "run", id: decodeURIComponent(runMatch[1]) };
  // Registered after `/run` above, which is why "run" can never be a tab slug.
  const tabMatch = /^reports\/([^/]+)\/([^/]+)$/.exec(path);
  if (tabMatch) return { view: "detail", id: decodeURIComponent(tabMatch[1]), tab: decodeURIComponent(tabMatch[2]) };
  const reportMatch = /^reports\/([^/]+)$/.exec(path);
  if (reportMatch) return { view: "detail", id: decodeURIComponent(reportMatch[1]) };
  const embedMatch = /^embed\/([^/]+)$/.exec(path);
  if (embedMatch) return { view: "embed", id: decodeURIComponent(embedMatch[1]) };
  return { view: "home" };
}

/** Small hash-based router — the app has a handful of views and doesn't
 * need a routing library, but a real URL per template (#/reports/<id>)
 * makes it linkable/bookmarkable/back-button-able for free. */
export function useHashRoute(): [Route, (route: Route, options?: { replace?: boolean }) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));

  useEffect(() => {
    const onHashChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  /** `replace` swaps the current history entry instead of adding one -- for a
   * change of *view within a page* (a template's tab), which shouldn't make the
   * Back button walk through every tab the person clicked. */
  const navigate = (next: Route, options: { replace?: boolean } = {}) => {
    const hash =
      next.view === "detail"
        ? `#/reports/${encodeURIComponent(next.id)}${next.tab ? `/${encodeURIComponent(next.tab)}` : ""}`
        : next.view === "run"
          ? `#/reports/${encodeURIComponent(next.id)}/run`
          : next.view === "reports"
            ? "#/reports"
            : next.view === "batch"
              ? "#/batch"
              : next.view === "schedules"
                ? "#/schedules"
                : next.view === "home"
                  ? "#/home"
                  : next.view === "runs"
                    ? "#/runs"
                  : next.view === "starred"
                    ? "#/starred"
                  : next.view === "gallery"
                    ? "#/templates"
                  : next.view === "new-report"
                    ? `#/templates/new${next.id ? `/${encodeURIComponent(next.id)}` : ""}`
                    : next.view === "docs"
                    ? `#/docs${next.slug ? `/${encodeURIComponent(next.slug)}` : ""}${next.slug && next.anchor ? `/${encodeURIComponent(next.anchor)}` : ""}`
                    : next.view === "admin"
                      ? `#/admin/${next.section}`
                      : next.view === "embed"
                        ? `#/embed/${encodeURIComponent(next.id)}`
                        : "#/";
    if (options.replace) {
      // replaceState doesn't fire `hashchange`, so update the route by hand.
      window.history.replaceState(null, "", hash);
      setRoute(parseHash(hash));
    } else if (window.location.hash !== hash) window.location.hash = hash;
    else setRoute(next);
  };

  return [route, navigate];
}

/** Shared open/close lifecycle for every `<dialog className="modal">` in
 * the console (ConfirmDialog, RegisterDialog, and every admin *FormDialog)
 * — they all drove `showModal()`/`close()` off an `open` boolean prop with
 * the same six-line effect, copy-pasted per component. `onOpen` runs right
 * before `showModal()` and is where a dialog resets its own form fields;
 * omit it for a dialog with no local state to reset (ConfirmDialog). */
export function useDialogRef(open: boolean, onOpen?: () => void): RefObject<HTMLDialogElement | null> {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      onOpen?.();
      el.showModal();
      // showModal() focuses the first focusable thing, which is now the dialog's × -- start in the first field
      // instead (or on whatever the dialog marked autoFocus), so typing can begin straight away.
      if (document.activeElement?.closest(".modal-close")) {
        const target =
          el.querySelector<HTMLElement>("[autofocus]") ??
          el.querySelector<HTMLElement>("input:not([type=hidden]):not([readonly]):not([disabled]), textarea:not([readonly]):not([disabled]), select:not([disabled])") ??
          el.querySelector<HTMLElement>("button:not(.modal-close):not([disabled])");
        target?.focus();
      }
    }
    if (!open && el.open) el.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onOpen is a
    // fresh closure every render by design (it captures each dialog's
    // latest default values); re-running this effect for that alone would
    // fight the open/close transition it's meant to gate.
  }, [open]);

  return ref;
}

/** Wraps a `<dialog>`'s `onCancel` (native, fired on Escape) so it isn't
 * also triggered by a same-named "cancel" event bubbling up from a
 * `<input type="file">` descendant when its OS picker is dismissed
 * without choosing a file (Chromium, ~113+ -- see the File and Directory
 * Entries API). Without this guard, canceling that picker closes the
 * whole dialog too, silently discarding whatever the user had already
 * typed into it (RegisterDialog's template upload, UserSettingsModal's
 * avatar upload). A genuine Escape-key cancel always has the dialog
 * itself as `e.target`; a bubbled one has the input instead. */
export function onDialogCancel(onClose: () => void) {
  return (e: SyntheticEvent<HTMLDialogElement>) => {
    if (e.target === e.currentTarget) onClose();
  };
}

/** Copy-to-clipboard with a brief "copied" acknowledgement state, shared
 * by every copy button in the console (id chips, code snippets). */
/** execCommand fallback for contexts where navigator.clipboard is missing (http, older browsers). */
function legacyCopy(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;top:-1000px;opacity:0";
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

export function useCopy(): [boolean, (text: string) => void] {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  // Leaving (or re-copying) must not let an earlier timeout clear a newer "copied" early, or set state after unmount.
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = (text: string) => {
    const done = () => {
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1500);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => legacyCopy(text) && done());
    } else if (legacyCopy(text)) {
      // Plain-http deployments have no async clipboard API.
      done();
    }
  };

  return [copied, copy];
}
