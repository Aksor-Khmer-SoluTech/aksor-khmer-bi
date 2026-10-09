import { lazy, Suspense, useEffect, useState } from "react";
import AdminShell from "./admin/AdminShell";
import { canManageTemplates, has } from "./admin/sections";
import { api, onPasswordChangeRequired, onUnauthorized } from "./api";
import AppSidebar from "./components/AppSidebar";
import { BATCH_RENDER_ENABLED } from "./features";
import BatchRender from "./components/BatchRender";
import EmbedPage from "./components/EmbedPage";
import ForcePasswordChange from "./components/ForcePasswordChange";
import Footer from "./components/Footer";
import Gallery from "./components/Gallery";
import Login from "./components/Login";
import ReportsPage from "./components/ReportsPage";
import RunReportPage from "./components/RunReportPage";
import HomePage from "./components/HomePage";
import SchedulesPage from "./components/SchedulesPage";
import TemplateDetail from "./components/TemplateDetail";
import TopBar from "./components/TopBar";
import { useHashRoute, type Route } from "./hooks";
import type { AuthInfo } from "./types";
import { UserSettingsProvider } from "./userSettings";

// Markdown renderer + the guides are only needed on the docs route.
const DocsPage = lazy(() => import("./components/DocsPage"));

function canAccessAdmin(auth: AuthInfo): boolean {
  return auth.isSuperuser || auth.permissions.some((p) => p.endsWith(":manage"));
}

const SIDEBAR_COLLAPSED_KEY = "portal_sidebar_collapsed";

export default function App() {
  const [auth, setAuth] = useState<AuthInfo | null>(null);
  const [checkedSession, setCheckedSession] = useState(false);
  const [route, navigate] = useHashRoute();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1");

  useEffect(() => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  useEffect(() => {
    // The embed view (see EmbedPage.tsx) is unauthenticated by design —
    // its own API calls need no credential, so there's nothing for a
    // session check to accomplish here beyond a wasted round-trip on
    // every embedded page load elsewhere on the web.
    if (route.view === "embed") return;
    onUnauthorized(() => setAuth(null));
    // An admin flagged this account while its owner was signed in: the API
    // starts answering 403 PASSWORD_CHANGE_REQUIRED, so show the change screen.
    onPasswordChangeRequired(() => setAuth((current) => current && { ...current, mustChangePassword: true }));
    api.restoreSession().then((result) => {
      setAuth(result);
      setCheckedSession(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deliberately
    // only the route this mounted with; a later in-app navigation into
    // "embed" isn't a real path (nothing links there), and re-running
    // this for every route change would defeat the point of `[]`.
  }, []);

  // Chrome-less and checked before the session/login gates below — an
  // embedded report must never show this console's own login screen.
  if (route.view === "embed") {
    return <EmbedPage reportId={route.id} />;
  }

  if (!checkedSession) return null;

  if (!auth) {
    return <Login onSignedIn={setAuth} />;
  }

  // Checked before the console renders at all: a flagged account can't use
  // any of it (the API refuses every call), so it gets only this screen.
  if (auth.mustChangePassword) {
    return (
      <ForcePasswordChange
        auth={auth}
        onChanged={() => setAuth({ ...auth, mustChangePassword: false })}
        onAccountReady={setAuth}
      />
    );
  }

  const canAdmin = canAccessAdmin(auth);
  // Home -- the person's own dashboard -- is everyone's landing page, whatever else they can manage.
  // A stale #/admin/..., #/schedules or #/templates link for a since-demoted or never-privileged user
  // renders this instead: no redirect side-effect needed, just don't take that branch below.
  const home: Route = { view: "home" };
  const effectiveRoute: Route =
    route.view === "admin" && !canAdmin
      ? home
      : route.view === "schedules" && !has(auth, "job:view")
        ? home
        : (route.view === "batch" && !BATCH_RENDER_ENABLED) || ((route.view === "gallery" || route.view === "batch") && !canManageTemplates(auth))
            ? home
            : route;

  return (
    <UserSettingsProvider>
      <div className="app-root">
        <div className="bg-texture" />
        <div className="bg-grain" />
        <TopBar auth={auth} canAdmin={canAdmin} inAdmin={effectiveRoute.view === "admin"} navigate={navigate} />

        <div className="app-shell">
          <AppSidebar
            route={effectiveRoute}
            navigate={navigate}
            auth={auth}
            collapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
          />

          <div className="app-main">
            <div className="app-content">
              {effectiveRoute.view === "admin" ? (
                <AdminShell route={effectiveRoute} auth={auth} />
              ) : effectiveRoute.view === "docs" ? (
                <Suspense fallback={null}>
                  <DocsPage route={effectiveRoute} navigate={navigate} />
                </Suspense>
              ) : effectiveRoute.view === "detail" ? (
                // Same reasoning: a vertical tab rail + a pane that fills
                // the rest supplies its own padding, not `.shell`'s.
                <TemplateDetail
                  reportId={effectiveRoute.id}
                  tab={effectiveRoute.tab}
                  onTabChange={(tab) => navigate({ view: "detail", id: effectiveRoute.id, tab }, { replace: true })}
                  onBack={() => navigate({ view: "gallery" })}
                  onDeleted={() => navigate({ view: "gallery" })}
                  auth={auth}
                />
              ) : (
                // The run view keeps its content high on the screen (a report
                // wants every row of a small monitor), so it trims the top pad.
                <div className={`shell${effectiveRoute.view === "run" ? " shell-tight" : ""}`}>
                  {effectiveRoute.view === "gallery" && (
                    <Gallery auth={auth} onOpenReport={(id) => navigate({ view: "detail", id })} />
                  )}
                  {effectiveRoute.view === "home" && (
                    <HomePage
                      auth={auth}
                      canAdmin={canAdmin}
                      navigate={navigate}
                    />
                  )}
                  {effectiveRoute.view === "reports" && (
                    <ReportsPage
                      username={auth.username}
                      onRunReport={(id) => navigate({ view: "run", id })}
                      onManageTemplate={(id) => navigate({ view: "detail", id })}
                    />
                  )}
                  {effectiveRoute.view === "run" && (
                    <RunReportPage reportId={effectiveRoute.id} onBack={() => navigate({ view: "reports" })} />
                  )}
                  {effectiveRoute.view === "batch" && <BatchRender />}
                  {effectiveRoute.view === "schedules" && <SchedulesPage />}
                </div>
              )}
            </div>

            <Footer />
          </div>
        </div>
      </div>
    </UserSettingsProvider>
  );
}
