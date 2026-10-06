import type { Route } from "../hooks";
import type { AuthInfo } from "../types";
import AccessReviewPage from "./access-review/AccessReviewPage";
import ApiExplorerPage from "./api-explorer/ApiExplorerPage";
import AuditLogPage from "./audit/AuditLogPage";
import DashboardPage from "./dashboard/DashboardPage";
import JobsPage from "./jobs/JobsPage";
import LdapConfigsPage from "./ldap/LdapConfigsPage";
import MonitorPage from "./monitor/MonitorPage";
import OrganizationsPage from "./organizations/OrganizationsPage";
import PluginsPage from "./plugins/PluginsPage";
import ProtectedTermsPage from "./protected-terms/ProtectedTermsPage";
import ClientsPage from "./clients/ClientsPage";
import ConnectionsPage from "./connections/ConnectionsPage";
import DriversPage from "./jdbc/DriversPage";
import ResourcesPage from "../components/ResourcesPage";
import RolesPage from "./roles/RolesPage";
import SecretsPage from "./secrets/SecretsPage";
import { ADMIN_SECTIONS } from "./sections";
import UsersPage from "./users/UsersPage";

/** The section nav itself now lives in AppSidebar (one app-wide rail
 * instead of a separate admin-only one) — this just picks which page to
 * render for the active section. */
export default function AdminShell({
  route,
  auth,
}: {
  route: Extract<Route, { view: "admin" }>;
  auth: AuthInfo;
}) {
  const sections = ADMIN_SECTIONS.filter((s) => s.visible(auth));
  // A deep-link into a section this user can't reach (permissions changed,
  // or a stale link) falls back to the first one they can.
  const active = sections.find((s) => s.id === route.section) ?? sections[0];

  return (
    <div className="admin-content">
      {active?.id === "dashboard" && <DashboardPage auth={auth} />}
      {active?.id === "resources" && <ResourcesPage auth={auth} />}
      {active?.id === "users" && <UsersPage auth={auth} />}
      {active?.id === "roles" && <RolesPage auth={auth} />}
      {active?.id === "clients" && <ClientsPage auth={auth} />}
      {active?.id === "connections" && <ConnectionsPage auth={auth} />}
      {active?.id === "jdbc-drivers" && <DriversPage auth={auth} />}
      {active?.id === "secrets" && <SecretsPage auth={auth} />}
      {active?.id === "access-review" && <AccessReviewPage auth={auth} />}
      {active?.id === "audit" && <AuditLogPage auth={auth} />}
      {active?.id === "protected-terms" && <ProtectedTermsPage auth={auth} />}
      {active?.id === "organizations" && <OrganizationsPage auth={auth} />}
      {active?.id === "ldap" && <LdapConfigsPage auth={auth} />}
      {active?.id === "jobs" && <JobsPage auth={auth} />}
      {active?.id === "api" && <ApiExplorerPage />}
      {active?.id === "monitor" && <MonitorPage />}
      {active?.id === "plugins" && <PluginsPage />}
    </div>
  );
}
