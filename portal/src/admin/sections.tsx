import type { ReactElement } from "react";
import type { AdminSection } from "../hooks";
import type { AuthInfo } from "../types";
import {
  AccessReviewIcon,
  ApiIcon,
  AuditIcon,
  ClientsIcon,
  ConnectionsIcon,
  DashboardIcon,
  DriversIcon,
  SecretsIcon,
  JobsIcon,
  LdapIcon,
  MonitorIcon,
  OrganizationsIcon,
  PluginsIcon,
  ResourcesIcon,
  ProtectedTermsIcon,
  RolesIcon,
  UsersIcon,
} from "./icons";

/** Shared between AdminShell (renders the active section's page) and
 * AppSidebar (renders the section list as nav items) — the two used to
 * duplicate this list before the sidebar was unified into one app-wide
 * rail instead of a separate admin-only one. */
export interface SectionDef {
  id: AdminSection;
  label: string;
  icon: () => ReactElement;
  visible: (auth: AuthInfo) => boolean;
}

export const has = (auth: AuthInfo, code: string) => auth.isSuperuser || auth.permissions.includes(code);

/** Who gets the Templates screen (register + integrate) in the sidebar and
 * lands on it by default. Everyone else lands on Reports -- the list of
 * reports they were granted -- and never sees template management. (A
 * user managing just one report via a report-specific grant reaches that
 * template from its "Manage" link on the Reports page instead.) */
export const canManageTemplates = (auth: AuthInfo) => has(auth, "report:manage");

export const ADMIN_SECTIONS: SectionDef[] = [
  // First on purpose -- AdminShell lands on sections[0] when no deep
  // link says otherwise, so this is Admin's landing page (there wasn't
  // one before). Visible if the caller holds any one of the three
  // panels' own gates (each panel then independently hides itself if
  // its own permission is missing -- see DashboardPage.tsx).
  {
    id: "dashboard",
    label: "Dashboard",
    icon: DashboardIcon,
    visible: (a) => has(a, "report:view") || has(a, "job:view") || has(a, "audit:view"),
  },
  {
    id: "resources",
    label: "Resources",
    icon: ResourcesIcon,
    // The folder tree and uploaded images that templates are organised in and draw from -- for the people who
    // look after them, not for everyone who can open a report.
    visible: (a) => has(a, "folder:manage") || has(a, "report:manage"),
  },
  { id: "users", label: "Users", icon: UsersIcon, visible: (a) => has(a, "user:manage") },
  { id: "roles", label: "Roles", icon: RolesIcon, visible: (a) => has(a, "role:manage") },
  { id: "clients", label: "API Clients", icon: ClientsIcon, visible: (a) => has(a, "client:manage") },
  { id: "connections", label: "Connections", icon: ConnectionsIcon, visible: (a) => has(a, "connection:manage") },
  {
    id: "jdbc-drivers",
    label: "JDBC Drivers",
    icon: DriversIcon,
    // A connection author needs to *see* the drivers to pick one; uploading and deleting them is
    // gated separately, inside the page, by driver:manage (a driver is code the driver service runs).
    visible: (a) => has(a, "driver:manage") || has(a, "connection:manage"),
  },
  {
    id: "secrets",
    label: "Secrets",
    icon: SecretsIcon,
    // A connection/report author needs to *see* the list to pick one; managing them (create,
    // rotate, revoke) is gated separately, inside the page, by secret:manage.
    visible: (a) => has(a, "secret:manage") || has(a, "connection:manage") || has(a, "report:manage"),
  },
  {
    id: "access-review",
    label: "Access Review",
    icon: AccessReviewIcon,
    visible: (a) => has(a, "report:manage") || has(a, "folder:manage"),
  },
  {
    id: "audit",
    label: "Audit Log",
    icon: AuditIcon,
    visible: (a) => has(a, "audit:view"),
  },
  {
    id: "protected-terms",
    label: "Protected Terms",
    icon: ProtectedTermsIcon,
    // Report authors need to *see* the sets to pick one; editing them is
    // gated separately, inside the page, by protected_terms:manage.
    visible: (a) => has(a, "protected_terms:manage") || has(a, "report:manage"),
  },
  { id: "organizations", label: "Organizations", icon: OrganizationsIcon, visible: () => true },
  { id: "ldap", label: "AD / LDAP", icon: LdapIcon, visible: (a) => has(a, "settings:manage") },
  { id: "jobs", label: "Jobs", icon: JobsIcon, visible: (a) => has(a, "job:view") },
  { id: "api", label: "API Explorer", icon: ApiIcon, visible: (a) => has(a, "settings:manage") },
  { id: "monitor", label: "Monitor", icon: MonitorIcon, visible: (a) => has(a, "settings:manage") },
  { id: "plugins", label: "Plugins", icon: PluginsIcon, visible: () => true },
];
