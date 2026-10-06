import { ADMIN_SECTIONS, canManageTemplates, has } from "../admin/sections";
import { BATCH_RENDER_ENABLED } from "../features";
import { BatchIcon, DashboardIcon, ChevronIcon, ReportsIcon, SchedulesIcon, TemplatesIcon } from "../admin/icons";
import type { Route } from "../hooks";
import type { AuthInfo } from "../types";

/** One fully-resolved class string per nav-item state, rather than
 * concatenating a "base" string with "override" fragments for the same
 * property (e.g. `bg-transparent` + `bg-accent-soft` both present at
 * once when active) -- which utility wins then depends on Tailwind's
 * internal generation order, not on source position in the class
 * attribute, so two classes for one property is a real correctness bug,
 * not just untidy. Every branch below sets each property exactly once. */
function navItemClasses({
  active = false,
  collapsed = false,
  navBack = false,
}: {
  active?: boolean;
  collapsed?: boolean;
  navBack?: boolean;
}): string {
  const padding = collapsed ? "justify-center px-0" : "px-3";
  const verticalPadding = navBack ? "pt-1.5 pb-[9px]" : "py-[9px]";
  const size = navBack ? "text-[0.8rem]" : "text-[0.86rem]";
  const color = active
    ? "bg-bg-chrome-active text-accent-strong hover:bg-bg-chrome-active hover:text-accent-strong"
    : navBack
      ? "bg-transparent text-text-faint hover:bg-transparent hover:text-text-dim"
      : "bg-transparent text-text-dim hover:bg-bg-chrome-hover hover:text-text";
  return `flex w-full cursor-pointer appearance-none items-center gap-2.5 rounded-sm border-none text-left font-medium ${padding} ${verticalPadding} ${size} ${color}`;
}

/** The contextual left rail below TopBar. Its contents swap with where you
 * are: outside Admin it shows the top-level destinations (Templates and
 * Batch render if you hold report:manage, Reports for everyone, Schedules if
 * and you hold job:view) — the Admin entry
 * point lives only in TopBar; inside Admin
 * it swaps to a back-link and the admin section list (users/roles/.../
 * plugins) — the same pattern GitLab uses for a project/group's sidebar
 * nested under the global top bar. `collapsed` shrinks it to an
 * icon-only rail. */
export default function AppSidebar({
  route,
  navigate,
  auth,
  collapsed,
  onToggleCollapse,
}: {
  route: Route;
  navigate: (route: Route) => void;
  auth: AuthInfo;
  collapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const inAdmin = route.view === "admin";
  const manageTemplates = canManageTemplates(auth);
  const sections = ADMIN_SECTIONS.filter((s) => s.visible(auth));
  const activeSectionId = inAdmin ? (sections.find((s) => s.id === route.section) ?? sections[0])?.id : null;

  // Unconditional, not just `max-md:hidden` -- the original CSS hides
  // labels whenever collapsed regardless of viewport (collapsing only
  // really makes sense at desktop width, where the icon-only rail is a
  // real toggle; mobile's own row-wrapped layout doesn't re-show them).
  // Reproduced as-is rather than "fixed" here -- a pure styling
  // migration isn't the place to change behavior even if this looks
  // like a pre-existing quirk.
  const navLabel = collapsed ? "hidden" : "truncate";

  return (
    <aside
      className={`flex flex-col gap-0.5 overflow-y-auto border-border-soft bg-bg-chrome pb-4 transition-[flex-basis] duration-150 ease-out max-md:flex-row max-md:flex-wrap max-md:items-center max-md:overflow-y-visible max-md:border-r-0 max-md:border-b max-md:px-3 max-md:py-2.5 ${
        collapsed ? "basis-[60px] px-2" : "basis-56 px-3.5"
      }`}
    >
      <nav className="flex flex-col gap-0.5 max-md:flex-row max-md:flex-wrap">
        {inAdmin ? (
          <>
            <button
              type="button"
              className={navItemClasses({ collapsed, navBack: true })}
              onClick={() => navigate({ view: "reports" })}
              title="Reports"
            >
              <span aria-hidden="true">&larr;</span>
              <span className={navLabel}>Reports</span>
            </button>
            <div
              className={`overflow-hidden px-3 pt-4 pb-1.5 font-mono text-[0.66rem] font-semibold tracking-[0.06em] whitespace-nowrap text-text-faint uppercase max-md:w-full max-md:px-2 max-md:pt-1 max-md:pb-0.5 ${collapsed ? "hidden" : ""}`}
            >
              Admin console
            </div>
            {sections.map((s) => (
              <button
                key={s.id}
                type="button"
                className={navItemClasses({ collapsed, active: s.id === activeSectionId })}
                onClick={() => navigate({ view: "admin", section: s.id })}
                title={s.label}
              >
                <s.icon />
                <span className={navLabel}>{s.label}</span>
              </button>
            ))}
          </>
        ) : (
          <>
            <button
              type="button"
              className={navItemClasses({ collapsed, active: route.view === "home" })}
              onClick={() => navigate({ view: "home" })}
              title="Home"
            >
              <DashboardIcon />
              <span className={navLabel}>Home</span>
            </button>
            <button
              type="button"
              className={navItemClasses({ collapsed, active: route.view === "reports" || route.view === "run" })}
              onClick={() => navigate({ view: "reports" })}
              title="Reports"
            >
              <ReportsIcon />
              <span className={navLabel}>Reports</span>
            </button>
            {manageTemplates && (
              <button
                type="button"
                className={navItemClasses({ collapsed, active: route.view === "gallery" || route.view === "detail" })}
                onClick={() => navigate({ view: "gallery" })}
                title="Templates"
              >
                <TemplatesIcon />
                <span className={navLabel}>Templates</span>
              </button>
            )}
            {/* A developer's tool -- you hand-write the JSON records a template
                expects -- so it's for people who manage templates, like the
                Templates item above, not for everyone who can open a report. */}
            {BATCH_RENDER_ENABLED && manageTemplates && (
              <button
                type="button"
                className={navItemClasses({ collapsed, active: route.view === "batch" })}
                onClick={() => navigate({ view: "batch" })}
                title="Batch render"
              >
                <BatchIcon />
                <span className={navLabel}>Batch render</span>
              </button>
            )}
            {has(auth, "job:view") && (
              <button
                type="button"
                className={navItemClasses({ collapsed, active: route.view === "schedules" })}
                onClick={() => navigate({ view: "schedules" })}
                title="Schedules"
              >
                <SchedulesIcon />
                <span className={navLabel}>Schedules</span>
              </button>
            )}
          </>
        )}
      </nav>

      <div className="mt-auto pt-2 max-md:hidden">
        <button
          type="button"
          className={navItemClasses({ collapsed })}
          onClick={onToggleCollapse}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <span className={`inline-flex transition-transform duration-150 ease-out ${collapsed ? "rotate-180" : ""}`}>
            <ChevronIcon />
          </span>
          <span className={navLabel}>{collapsed ? "Expand sidebar" : "Collapse sidebar"}</span>
        </button>
      </div>
    </aside>
  );
}
