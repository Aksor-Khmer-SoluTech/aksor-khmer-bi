import { lazy, Suspense } from "react";
import type { Route } from "../hooks";
import type { AuthInfo } from "../types";
import { ADMIN_SECTIONS } from "./sections";

// One chunk per section, fetched when it is first opened.
const AccessReviewPage = lazy(() => import("./access-review/AccessReviewPage"));
const ApiExplorerPage = lazy(() => import("./api-explorer/ApiExplorerPage"));
const AuditLogPage = lazy(() => import("./audit/AuditLogPage"));
const ClientsPage = lazy(() => import("./clients/ClientsPage"));
const ConnectionsPage = lazy(() => import("./connections/ConnectionsPage"));
const DashboardPage = lazy(() => import("./dashboard/DashboardPage"));
const DatasetsPage = lazy(() => import("./datasets/DatasetsPage"));
const DriversPage = lazy(() => import("./jdbc/DriversPage"));
const JobsPage = lazy(() => import("./jobs/JobsPage"));
const LdapConfigsPage = lazy(() => import("./ldap/LdapConfigsPage"));
const MonitorPage = lazy(() => import("./monitor/MonitorPage"));
const OrganizationsPage = lazy(() => import("./organizations/OrganizationsPage"));
const PluginsPage = lazy(() => import("./plugins/PluginsPage"));
const ProtectedTermsPage = lazy(() => import("./protected-terms/ProtectedTermsPage"));
const ResourcesPage = lazy(() => import("../components/ResourcesPage"));
const RolesPage = lazy(() => import("./roles/RolesPage"));
const SecretsPage = lazy(() => import("./secrets/SecretsPage"));
const UsersPage = lazy(() => import("./users/UsersPage"));

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
      <Suspense fallback={null}>
        {active?.id === "dashboard" && <DashboardPage auth={auth} />}
        {active?.id === "resources" && <ResourcesPage auth={auth} />}
        {active?.id === "users" && <UsersPage auth={auth} />}
        {active?.id === "roles" && <RolesPage auth={auth} />}
        {active?.id === "clients" && <ClientsPage auth={auth} />}
        {active?.id === "connections" && <ConnectionsPage auth={auth} />}
        {active?.id === "datasets" && <DatasetsPage auth={auth} />}
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
      </Suspense>
    </div>
  );
}
