import type { ReactElement } from "react";
import { BATCH_RENDER_ENABLED } from "../features";
import type { AdminSection, Route } from "../hooks";
import type { AuthInfo } from "../types";
import {
  AccessReviewIcon,
  ApiIcon,
  BatchIcon,
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
  SchedulesIcon,
  TemplatesIcon,
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
  /** Which heading it sits under in the Manage sidebar. */
  group: ManageGroupId;
}

/** Manage -- everything beyond running reports -- grouped by the job being done, so each person sees only the
 * groups their permissions reach: a job operator just Scheduling, an org admin People & access... A group with
 * nothing visible is left out. */
export type ManageGroupId = "authoring" | "scheduling" | "data" | "people" | "operations";

export const MANAGE_GROUPS: { id: ManageGroupId; label: string }[] = [
  { id: "authoring", label: "Authoring" },
  { id: "scheduling", label: "Scheduling" },
  { id: "data", label: "Data sources" },
  { id: "people", label: "People & access" },
  { id: "operations", label: "Operations" },
];

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
    // Server-wide activity: for the people who run the server, not for everyone who can open a report (every
    // account has report:view, and a Dashboard alone mustn't put a Manage button in front of them).
    visible: (a) => has(a, "audit:view") || has(a, "settings:manage"),
    group: "operations",
  },
  {
    id: "resources",
    label: "Resources",
    icon: ResourcesIcon,
    // The folder tree and uploaded images that templates are organised in and draw from -- for the people who
    // look after them, not for everyone who can open a report.
    visible: (a) => has(a, "folder:manage") || has(a, "report:manage"),
    group: "authoring",
  },
  { id: "users", label: "Users", icon: UsersIcon, visible: (a) => has(a, "user:manage"), group: "people" },
  { id: "roles", label: "Roles", icon: RolesIcon, visible: (a) => has(a, "role:manage"), group: "people" },
  { id: "clients", label: "API Clients", icon: ClientsIcon, visible: (a) => has(a, "client:manage"), group: "people" },
  { id: "connections", label: "Connections", icon: ConnectionsIcon, visible: (a) => has(a, "connection:manage"), group: "data" },
  {
    id: "jdbc-drivers",
    label: "JDBC Drivers",
    icon: DriversIcon,
    // A connection author needs to *see* the drivers to pick one; uploading and deleting them is
    // gated separately, inside the page, by driver:manage (a driver is code the driver service runs).
    visible: (a) => has(a, "driver:manage") || has(a, "connection:manage"),
    group: "data",
  },
  {
    id: "secrets",
    label: "Secrets",
    icon: SecretsIcon,
    // A connection/report author needs to *see* the list to pick one; managing them (create,
    // rotate, revoke) is gated separately, inside the page, by secret:manage.
    visible: (a) => has(a, "secret:manage") || has(a, "connection:manage") || has(a, "report:manage"),
    group: "data",
  },
  {
    id: "access-review",
    label: "Access Review",
    icon: AccessReviewIcon,
    visible: (a) => has(a, "report:manage") || has(a, "folder:manage"),
    group: "people",
  },
  {
    id: "audit",
    label: "Audit Log",
    icon: AuditIcon,
    visible: (a) => has(a, "audit:view"),
    group: "operations",
  },
  {
    id: "protected-terms",
    label: "Protected Terms",
    icon: ProtectedTermsIcon,
    // Report authors need to *see* the sets to pick one; editing them is
    // gated separately, inside the page, by protected_terms:manage.
    visible: (a) => has(a, "protected_terms:manage") || has(a, "report:manage"),
    group: "authoring",
  },
  { id: "organizations", label: "Organizations", icon: OrganizationsIcon, visible: (a) => has(a, "org:manage") || has(a, "user:manage"), group: "people" },
  { id: "ldap", label: "AD / LDAP", icon: LdapIcon, visible: (a) => has(a, "settings:manage"), group: "people" },
  { id: "jobs", label: "Jobs", icon: JobsIcon, visible: (a) => has(a, "job:view"), group: "scheduling" },
  { id: "api", label: "API Explorer", icon: ApiIcon, visible: (a) => has(a, "settings:manage"), group: "operations" },
  { id: "monitor", label: "Monitor", icon: MonitorIcon, visible: (a) => has(a, "settings:manage"), group: "operations" },
  { id: "plugins", label: "Plugins", icon: PluginsIcon, visible: (a) => has(a, "settings:manage"), group: "operations" },
];

/** One entry in the Manage sidebar: an admin section, or one of the other Manage pages (Templates, Batch render,
 * Schedules) that have routes of their own. */
export interface ManageItem {
  key: string;
  label: string;
  icon: () => ReactElement;
  group: ManageGroupId;
  route: Route;
  /** Highlighted when this route is open (Templates also covers a template's own page). */
  isActive: (route: Route) => boolean;
}

export function manageItems(auth: AuthInfo): ManageItem[] {
  const extra: (ManageItem & { visible: boolean })[] = [
    {
      key: "templates", label: "Templates", icon: TemplatesIcon, group: "authoring", route: { view: "gallery" },
      isActive: (r) => r.view === "gallery" || r.view === "detail" || r.view === "new-report", visible: canManageTemplates(auth),
    },
    {
      // A developer's tool -- you hand-write the JSON records a template expects -- so it sits with authoring.
      key: "batch", label: "Batch render", icon: BatchIcon, group: "authoring", route: { view: "batch" },
      isActive: (r) => r.view === "batch", visible: BATCH_RENDER_ENABLED && canManageTemplates(auth),
    },
    {
      // The read-only "what's running" overview; Jobs (below, an admin section) is where schedules are edited.
      key: "schedules", label: "Schedules", icon: SchedulesIcon, group: "scheduling", route: { view: "schedules" },
      isActive: (r) => r.view === "schedules", visible: has(auth, "job:view"),
    },
  ];
  const sections: ManageItem[] = ADMIN_SECTIONS.filter((s) => s.visible(auth)).map((s) => ({
    key: s.id, label: s.label, icon: s.icon, group: s.group, route: { view: "admin", section: s.id },
    isActive: (r) => r.view === "admin" && r.section === s.id,
  }));
  const all = [...extra.filter((e) => e.visible).map(({ visible: _visible, ...item }) => item), ...sections];
  // In group order, keeping each group's own order (the extra pages first: they're what that group is mostly for).
  return MANAGE_GROUPS.flatMap((g) => all.filter((i) => i.group === g.id));
}

/** The Manage button shows only when there is something behind it. */
export const canManage = (auth: AuthInfo) => manageItems(auth).length > 0;

/** Where the Manage button goes: the first page this person can use there. */
export const firstManageRoute = (auth: AuthInfo): Route => manageItems(auth)[0]?.route ?? { view: "home" };

/** The pages that live in Manage (left sidebar); everything else is everyday (top-bar navigation). */
export const isManageRoute = (route: Route) =>
  route.view === "gallery" || route.view === "detail" || route.view === "new-report" || route.view === "batch" || route.view === "schedules" || route.view === "admin";
