import type { ReactNode } from "react";
import { branding } from "../branding";
import BrandMark from "./BrandMark";

/** The split layout shared by every pre-console screen (sign-in, the forced
 * password change): brand panel on the left, whatever the screen needs on
 * the right. */
export default function LoginShell({ children }: { children: ReactNode }) {
  return (
    <div className="login-shell">
      <div className="bg-texture" />
      <div className="bg-grain" />

      <div className="login-brand">
        <div className="login-brand-inner">
          <p className="login-brand-eyebrow">{branding.tagline}</p>
          <div className="wordmark">
            {branding.logoUrl ? (
              <img src={branding.logoUrl} alt="" className="glyph glyph-img" />
            ) : (
              <span className="glyph">
                <BrandMark />
              </span>
            )}
            {branding.name}
          </div>
          <p className="login-brand-desc">{branding.description}</p>
        </div>
      </div>

      <div className="login-form-side">{children}</div>
    </div>
  );
}
