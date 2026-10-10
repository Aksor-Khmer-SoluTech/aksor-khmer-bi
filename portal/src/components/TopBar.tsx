import { FileText, History, House, Star, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { canManage, firstManageRoute, isManageRoute } from "../admin/sections";
import { AdminIcon, DocsIcon, InfoIcon } from "../admin/icons";
import { branding } from "../branding";
import type { Route } from "../hooks";
import type { AuthInfo } from "../types";
import AboutDialog from "./AboutDialog";
import AccountMenu from "./AccountMenu";
import BrandMark from "./BrandMark";
import NotificationsMenu from "./NotificationsMenu";

/** The everyday pages -- what most people come for. Everything else is behind Manage. */
const EVERYDAY: { label: string; icon: LucideIcon; route: Route; isActive: (route: Route) => boolean }[] = [
  { label: "Home", icon: House, route: { view: "home" }, isActive: (r) => r.view === "home" },
  { label: "Reports", icon: FileText, route: { view: "reports" }, isActive: (r) => r.view === "reports" || r.view === "run" },
  { label: "My runs", icon: History, route: { view: "runs" }, isActive: (r) => r.view === "runs" },
  { label: "Starred", icon: Star, route: { view: "starred" }, isActive: (r) => r.view === "starred" },
];

/** The top bar, and for most people the only navigation there is: brand, then the everyday pages (Home, Reports,
 * My runs, Starred); on the right the Manage button -- only for someone with something to manage (templates,
 * schedules, users, connections... see manageItems) -- then notifications, docs, About and the account menu.
 * Manage pages add the grouped left sidebar (AppSidebar); there the everyday links give way to that sidebar's
 * "Back to ..." (the page Manage was opened from). */
export default function TopBar({
  auth,
  route,
  navigate,
}: {
  auth: AuthInfo;
  route: Route;
  navigate: (route: Route) => void;
}) {
  const [aboutOpen, setAboutOpen] = useState(false);
  const inManage = isManageRoute(route);

  return (
    <header className="flex flex-none flex-wrap items-center justify-between gap-x-4 gap-y-2 bg-bg-chrome px-5 py-3 max-md:gap-x-2 max-md:px-4 max-md:py-2.5">
      <button
        type="button"
        tabIndex={-1}
        className="flex min-w-0 cursor-pointer items-center gap-3 text-left max-md:flex-1 max-md:basis-0 font-display text-[1.1rem] font-semibold tracking-[-0.01em] text-inherit max-md:gap-2 max-md:text-[1.02rem]"
        onClick={() => navigate({ view: "home" })}
      >
        {branding.logoUrl ? (
          <img
            src={branding.logoUrl}
            alt=""
            className="h-10 w-10 flex-none rounded-[10px] bg-bg-panel object-cover max-md:h-7 max-md:w-7"
          />
        ) : (
          <span className="grid h-10 w-10 flex-none place-items-center rounded-[10px] bg-gradient-to-br from-accent to-accent-strong text-accent-ink shadow-accent max-md:h-7 max-md:w-7">
            <BrandMark />
          </span>
        )}
        {/* Two columns: the org brand stacked over its tagline ("Aksor Khmer"
            / "Business Intelligence"), then the product name ("Control
            Plane") in its own column to the right, vertically centred
            against that whole stack -- so it sits midway between the two
            lines rather than riding the first one. The hairline divider
            stretches the full height of the stack to mark the hand-off.
            The org brand stays the primary (bold, dark) heading; the
            product name is the same display face one weight lighter, in the
            accent colour so it ties to the logo tile. It shows only in Manage --
            the console side of the app; everyday pages are just the brand and
            their links. Phones drop it, the divider and the tagline. */}
        <span className="flex min-w-0 items-center gap-3.5">
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate">{branding.name}</span>
            {branding.tagline && (
              <span className="max-md:hidden whitespace-nowrap font-mono text-[0.6rem] font-medium tracking-[0.06em] text-text-faint uppercase">
                {branding.tagline}
              </span>
            )}
          </span>
          {branding.productName && inManage && (
            <>
              <span aria-hidden="true" className="my-0.5 w-px flex-none self-stretch bg-border-strong max-md:hidden" />
              <span className="whitespace-nowrap text-[1.08rem] leading-none font-medium tracking-[-0.005em] text-accent-strong max-md:hidden">
                {branding.productName}
              </span>
            </>
          )}
        </span>
      </button>

      {!inManage && (
        <nav aria-label="Main" className="flex min-w-0 flex-1 items-center gap-1 max-md:order-last max-md:basis-full max-md:justify-between">
          {EVERYDAY.map(({ label, icon: Icon, route: to, isActive }) => {
            const active = isActive(route);
            return (
              <button
                key={label}
                type="button"
                className={`inline-flex cursor-pointer items-center gap-1.5 rounded-sm border-none px-3 py-[7px] text-[0.86rem] font-medium whitespace-nowrap transition-[background-color,color] duration-150 ease-out max-md:px-2 ${
                  active
                    ? "bg-bg-chrome-active text-accent-strong"
                    : "bg-transparent text-text-dim hover:bg-bg-chrome-hover hover:text-text"
                }`}
                onClick={() => navigate(to)}
                aria-current={active ? "page" : undefined}
                title={label}
                data-tour={`nav-${label.toLowerCase().replace(/ /g, "-")}`}
              >
                <Icon size={16} aria-hidden="true" />
                <span className="md:max-lg:hidden">{label}</span>
              </button>
            );
          })}
        </nav>
      )}

      <div className="ml-auto flex items-center gap-3.5 max-md:gap-2">
        {canManage(auth) && (
          <button
            type="button"
            className={`group inline-flex cursor-pointer items-center gap-1.5 rounded-sm border py-[5px] pr-4 pl-3.5 text-[0.78rem] font-medium shadow-card transition-[border-color,background-color,color,box-shadow,transform] duration-200 ease-out hover:-translate-y-px hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong hover:shadow-accent active:translate-y-0 max-md:px-2.5 ${
              inManage ? "border-accent-border bg-accent-soft text-accent-strong" : "border-border-strong bg-bg-raised text-text"
            }`}
            onClick={() => navigate(firstManageRoute(auth))}
            aria-current={inManage ? "page" : undefined}
            data-tour="manage"
            title="Manage templates, schedules, data sources, people and the server"
          >
            {/* The wrench itself turns on hover, like it's being used —
                a small, on-theme touch rather than a generic color swap. */}
            <span className="inline-flex transition-transform duration-300 ease-out group-hover:-rotate-[22deg]">
              <AdminIcon />
            </span>
            <span className="max-md:hidden">Manage</span>
          </button>
        )}

        {/* Notifications / Documentation / About sit in one tight cluster —
            grouped by proximity (gap-1 inside, the wider gap-3.5 around)
            rather than a divider rule. */}
        <div className="flex items-center gap-1">
          <NotificationsMenu />

          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-sm border border-transparent bg-transparent p-[7px] text-text-dim transition-[border-color,background-color,transform] duration-150 ease-out hover:bg-bg-chrome-hover hover:text-text active:translate-y-px"
            onClick={() => navigate({ view: "docs" })}
            title="Documentation"
            data-tour="docs"
          >
            <DocsIcon />
          </button>

          <button
            type="button"
            className="inline-flex cursor-pointer items-center gap-1.5 rounded-sm border border-transparent bg-transparent p-[7px] text-text-dim transition-[border-color,background-color,transform] duration-150 ease-out hover:bg-bg-chrome-hover hover:text-text active:translate-y-px"
            onClick={() => setAboutOpen(true)}
            title="About"
          >
            <InfoIcon />
          </button>
        </div>

        <AccountMenu auth={auth} />
      </div>

      <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} />
    </header>
  );
}
