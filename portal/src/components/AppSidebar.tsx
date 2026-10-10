import { MANAGE_GROUPS, manageItems } from "../admin/sections";
import { ChevronIcon } from "../admin/icons";
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

/** What "Back to ..." calls the everyday page Manage was opened from. */
function backLabel(route: Route): string {
  switch (route.view) {
    case "reports":
      return "Back to Reports";
    case "run":
      return "Back to the report";
    case "runs":
      return "Back to My runs";
    case "starred":
      return "Back to Starred";
    case "docs":
      return "Back to Guides";
    default:
      return "Back to Home";
  }
}

/** The Manage sidebar, shown only on Manage pages (see isManageRoute): a way back to the everyday page you came from, then
 * everything this person can manage in groups (Authoring, Scheduling, Data sources, People & access, Operations).
 * Everyday pages -- Home, Reports, My runs, Starred -- live in the top bar instead, so most people never see a
 * sidebar at all. `collapsed` shrinks it to an icon-only rail. */
export default function AppSidebar({
  route,
  backTo,
  navigate,
  auth,
  collapsed,
  onToggleCollapse,
}: {
  route: Route;
  /** The everyday page Manage was opened from; "Back" returns there. */
  backTo: Route;
  navigate: (route: Route) => void;
  auth: AuthInfo;
  collapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const items = manageItems(auth);
  // An #/admin/<section> this person can't open shows the first one they can (AdminShell), so highlight that.
  const active =
    items.find((i) => i.isActive(route)) ?? (route.view === "admin" ? items.find((i) => i.route.view === "admin") : undefined);

  // Labels hide whenever collapsed (collapsing only really matters at desktop width, where the icon-only rail is a
  // real toggle; the phone layout wraps into rows and has its own toggle hidden).
  const navLabel = collapsed ? "hidden" : "truncate";

  return (
    <aside
      className={`flex flex-none flex-col gap-0.5 overflow-y-auto border-border-soft bg-bg-chrome pb-4 transition-[flex-basis] duration-150 ease-out max-md:flex-row max-md:flex-wrap max-md:items-center max-md:overflow-y-visible max-md:border-r-0 max-md:border-b max-md:px-3 max-md:py-2.5 ${
        collapsed ? "basis-[60px] px-2" : "basis-56 px-3.5"
      }`}
      aria-label="Manage"
      data-tour="manage-sidebar"
    >
      <nav className="flex flex-col gap-0.5 max-md:flex-row max-md:flex-wrap">
        <button
          type="button"
          className={navItemClasses({ collapsed, navBack: true })}
          onClick={() => navigate(backTo)}
          title={backLabel(backTo)}
          data-tour="manage-back"
        >
          <span aria-hidden="true">&larr;</span>
          <span className={navLabel}>{backLabel(backTo)}</span>
        </button>
        {MANAGE_GROUPS.map((g) => {
          const inGroup = items.filter((i) => i.group === g.id);
          if (inGroup.length === 0) return null;
          return (
            <div key={g.id} role="group" aria-label={g.label} className="contents">
              <div
                className={`overflow-hidden px-3 pt-4 pb-1.5 font-mono text-[0.66rem] font-semibold tracking-[0.06em] whitespace-nowrap text-text-faint uppercase max-md:w-full max-md:px-2 max-md:pt-1 max-md:pb-0.5 ${collapsed ? "hidden" : ""}`}
              >
                {g.label}
              </div>
              {collapsed && <div aria-hidden="true" className="mx-2 my-1.5 h-px bg-border-soft max-md:hidden" />}
              {inGroup.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={navItemClasses({ collapsed, active: item === active })}
                  onClick={() => navigate(item.route)}
                  title={item.label}
                  aria-current={item === active ? "page" : undefined}
                  data-tour={`manage-${item.key}`}
                >
                  <item.icon />
                  <span className={navLabel}>{item.label}</span>
                </button>
              ))}
            </div>
          );
        })}
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
