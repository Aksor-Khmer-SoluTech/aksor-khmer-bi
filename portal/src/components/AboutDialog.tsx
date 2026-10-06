import { MailIcon, PhoneIcon, SupportIcon, TelegramIcon } from "../admin/icons";
import { branding } from "../branding";
import { useDialogRef } from "../hooks";
import { support } from "../support";
import BrandMark from "./BrandMark";

import ModalClose from "./ModalClose";
function stripScheme(url: string): string {
  return url.replace(/^https?:\/\//, "");
}

function telHref(phone: string): string {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

function telegramHref(username: string): string {
  return `https://t.me/${username.replace(/^@/, "")}`;
}

/** Info icon in TopBar opens this — the brand/product lockup, a short
 * purpose blurb, the license/source Footer.tsx already carries, and a
 * support/donate block (KHQR + direct contact), read together in one
 * place instead of scattered across the chrome. */
export default function AboutDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useDialogRef(open);

  return (
    <dialog ref={ref} className="modal max-w-[560px]" onCancel={onClose}>
      <ModalClose />
      <div className="flex items-center gap-3.5">
        {branding.logoUrl ? (
          <img src={branding.logoUrl} alt="" className="h-11 w-11 flex-none rounded-xl bg-bg-panel object-cover" />
        ) : (
          <span className="grid h-11 w-11 flex-none place-items-center rounded-xl bg-gradient-to-br from-accent to-accent-strong text-accent-ink shadow-accent">
            <BrandMark />
          </span>
        )}
        <div>
          {branding.productName && (
            <p className="m-0 mb-0.5 font-mono text-[0.68rem] font-semibold tracking-[0.07em] text-text-faint uppercase">
              {branding.productName}
            </p>
          )}
          <h2 className="m-0 font-display text-[1.4rem] font-semibold tracking-[-0.01em]">{branding.name}</h2>
        </div>
      </div>

      {branding.tagline && <p className="mt-3 text-[0.9rem] text-text-dim">{branding.tagline}</p>}

      <p className="mt-3 text-[0.86rem] leading-relaxed text-text-dim">
        {branding.name} is an open, self-hostable platform for producing Khmer-language documents at scale — design
        report templates once, then render them on demand, in bulk, or on a schedule. Templates, images, and
        generated reports live in a shared, permissioned folder tree, with role-based access controlling who can
        view, edit, or run what. Built for teams who need Khmer typography handled properly, not bolted on
        afterward.
      </p>

      <dl className="mt-4 flex flex-col gap-2 border-t border-border-soft pt-3.5 text-[0.85rem]">
        <div className="flex items-baseline justify-between gap-3">
          <dt className="font-medium text-text-faint">Version</dt>
          <dd className="m-0 truncate font-mono text-text">v{__APP_VERSION__}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <dt className="font-medium text-text-faint">License</dt>
          <dd className="m-0 truncate">
            <a className="text-accent hover:underline" href={`${branding.repoUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">
              {branding.licenseName}
            </a>
          </dd>
        </div>
        <div className="flex items-baseline justify-between gap-3">
          <dt className="font-medium text-text-faint">Source</dt>
          <dd className="m-0 truncate">
            <a className="text-accent hover:underline" href={branding.repoUrl} target="_blank" rel="noreferrer">
              {stripScheme(branding.repoUrl)}
            </a>
          </dd>
        </div>
      </dl>

      <div className="mt-4 rounded-lg border border-border-soft bg-bg-panel p-4">
        <div className="flex items-center gap-1.5 text-text">
          <SupportIcon />
          <h3 className="m-0 font-display text-[0.95rem] font-semibold">Support this project</h3>
        </div>
        <p className="mt-1.5 text-[0.82rem] leading-relaxed text-text-dim">
          {branding.name} is free and open-source. If it saves your team time, a donation helps keep it
          maintained — scan the KHQR code with any Cambodian banking app, or reach out directly.
        </p>

        <div className="mt-3 flex flex-wrap items-start gap-4">
          <KhqrCode src={support.donateQrUrl} />

          <div className="flex min-w-[160px] flex-1 flex-col gap-2">
            <a
              href={`mailto:${support.email}`}
              className="flex items-center gap-2 rounded-md border border-border-soft bg-bg-raised px-3 py-2 text-[0.82rem] text-text transition-colors duration-150 hover:border-accent-border hover:bg-accent-soft"
            >
              <MailIcon />
              <span className="truncate">{support.email}</span>
            </a>
            <a
              href={telHref(support.phone)}
              className="flex items-center gap-2 rounded-md border border-border-soft bg-bg-raised px-3 py-2 text-[0.82rem] text-text transition-colors duration-150 hover:border-accent-border hover:bg-accent-soft"
            >
              <PhoneIcon />
              <span className="truncate">{support.phone}</span>
            </a>
            <a
              href={telegramHref(support.telegram)}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 rounded-md border border-border-soft bg-bg-raised px-3 py-2 text-[0.82rem] text-text transition-colors duration-150 hover:border-accent-border hover:bg-accent-soft"
            >
              <TelegramIcon />
              <span className="truncate">{support.telegram}</span>
            </a>
          </div>
        </div>
      </div>

      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      </div>
    </dialog>
  );
}

/** KHQR donation code — the project's real, bundled image (see
 * support.ts), never a generated one. */
function KhqrCode({ src }: { src: string }) {
  return (
    <div className="flex flex-none flex-col items-center gap-1.5">
      <img
        src={src}
        alt="KHQR donation code"
        className="h-[132px] w-[132px] rounded-lg border border-border-soft bg-white object-contain p-2"
      />
      <span className="font-mono text-[0.62rem] tracking-[0.06em] text-text-faint uppercase">KHQR</span>
    </div>
  );
}
