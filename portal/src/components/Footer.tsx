import { ExternalLinkIcon } from "../admin/icons";
import { branding } from "../branding";

/** The project credited in the footer. A constant on purpose, not read from
 * branding.ts/config.js like the rest of the chrome: Aksor Khmer BI is a
 * community project, so a deployment may rebrand its own header but not
 * this credit line. */
const PROJECT_NAME = "Aksor Khmer BI";

/** Always rendered, in both Templates and Admin mode — keeps open-source
 * attribution (license, contribute, contact) visible regardless of how a
 * fork rebrands the header via branding.ts/config.js. */
export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="app-footer">
      <span className="app-footer-legal">
        <span className="app-footer-name">{PROJECT_NAME}</span>
        <span className="app-footer-sep" aria-hidden="true">
          &middot;
        </span>
        <span>&copy; {year}</span>
        <span className="app-footer-sep" aria-hidden="true">
          &middot;
        </span>
        <a href={`${branding.repoUrl}/blob/main/LICENSE`} target="_blank" rel="noreferrer">
          {branding.licenseName} Licensed
        </a>
        <span className="app-footer-sep" aria-hidden="true">
          &middot;
        </span>
        <a href={branding.repoUrl} target="_blank" rel="noreferrer">
          Contribute
          <ExternalLinkIcon />
        </a>
      </span>
      <span className="app-footer-version">v{__APP_VERSION__}</span>
    </footer>
  );
}
