import { useState } from "react";
import { ADMIN_SECTIONS } from "../admin/sections";
import { AdminIcon, DocsIcon, InfoIcon } from "../admin/icons";
import { branding } from "../branding";
import type { Route } from "../hooks";
import type { AuthInfo } from "../types";
import AboutDialog from "./AboutDialog";
import AccountMenu from "./AccountMenu";
import BrandMark from "./BrandMark";
import NotificationsMenu from "./NotificationsMenu";

/** Slim, always-visible top bar — brand on the left, the things that stay
 * constant no matter which area of the sidebar you're in (a shortcut into
 * Admin, notifications, About, and the signed-in account menu — a single
 * Settings entry covering Profile/Notifications/Preferences/Access/
 * Active Sessions, plus Sign out) on the right. Mirrors GitLab's split:
 * top bar is global chrome, the sidebar below it is contextual. */
export default function TopBar({
  auth,
  canAdmin,
  inAdmin,
  navigate,
}: {
  auth: AuthInfo;
  canAdmin: boolean;
  inAdmin: boolean;
  navigate: (route: Route) => void;
}) {
  const firstAdminSection = ADMIN_SECTIONS.find((s) => s.visible(auth))?.id ?? "users";
  const [aboutOpen, setAboutOpen] = useState(false);

  return (
    <header className="flex flex-none items-center justify-between gap-4 bg-bg-chrome px-5 py-3 max-md:gap-2 max-md:px-4 max-md:py-2.5">
      <button
        type="button"
        tabIndex={-1}
        className="flex cursor-pointer items-center gap-3 text-left font-display text-[1.1rem] font-semibold tracking-[-0.01em] text-inherit max-md:gap-2 max-md:text-[1.02rem]"
        onClick={() => navigate({ view: "reports" })}
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
            accent colour so it ties to the logo tile. Phones drop the
            product name, divider and tagline to save the width. */}
        <span className="flex min-w-[200px] items-center gap-3.5 max-md:min-w-0">
          <span className="flex flex-col gap-0.5">
            <span className="whitespace-nowrap">{branding.name}</span>
            {branding.tagline && (
              <span className="max-md:hidden whitespace-nowrap font-mono text-[0.6rem] font-medium tracking-[0.06em] text-text-faint uppercase">
                {branding.tagline}
              </span>
            )}
          </span>
          {branding.productName && (
            <>
              <span aria-hidden="true" className="my-0.5 w-px flex-none self-stretch bg-border-strong max-md:hidden" />
              <span className="whitespace-nowrap text-[1.08rem] leading-none font-medium tracking-[-0.005em] text-accent-strong max-md:hidden">
                {branding.productName}
              </span>
            </>
          )}
        </span>
      </button>

      <div className="flex items-center gap-3.5 max-md:gap-2">
        {canAdmin && !inAdmin && (
          <button
            type="button"
            className="group inline-flex cursor-pointer items-center gap-1.5 rounded-sm border border-border-strong bg-bg-raised py-[5px] pr-4 pl-3.5 text-[0.78rem] font-medium text-text shadow-card transition-[border-color,background-color,color,box-shadow,transform] duration-200 ease-out hover:-translate-y-px hover:border-accent-border hover:bg-accent-soft hover:text-accent-strong hover:shadow-accent active:translate-y-0"
            onClick={() => navigate({ view: "admin", section: firstAdminSection })}
          >
            {/* The wrench itself turns on hover, like it's being used —
                a small, on-theme touch rather than a generic color swap. */}
            <span className="inline-flex transition-transform duration-300 ease-out group-hover:-rotate-[22deg]">
              <AdminIcon />
            </span>
            <span className="max-md:hidden">Admin</span>
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
