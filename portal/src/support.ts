// Contact + donation details for the About dialog's "support this project"
// section. Build-time only, on purpose: unlike everything in branding.ts
// (read from window.PORTAL_* / public/config.js, which a deployer can edit
// or bind-mount after the build), these are compiled into the bundle, so
// rebranding an installed portal never touches who it credits or where
// donations go -- same reasoning as the footer's fixed attribution (see
// README's Branding section). To change them, edit this file and rebuild.
import khqrUrl from "./assets/aba-khqr.jpg";

export const support = {
  email: "aksorkhmerbi@gmail.com",
  phone: "+855 10 335 644",
  // With its leading "@", as people usually write it -- AboutDialog strips
  // it when building the t.me link.
  telegram: "@siengsotheara",
  // The real exported ABA KHQR image (src/assets/aba-khqr.jpg), never a
  // generated one: a fabricated QR would either fail to scan or, worse,
  // look scannable while paying no one.
  donateQrUrl: khqrUrl,
} as const;
