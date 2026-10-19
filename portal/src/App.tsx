import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { canManageTemplates, has, isManageRoute, manageItems } from "./admin/sections";
import { api, onPasswordChangeRequired, onUnauthorized } from "./api";
import AppSidebar from "./components/AppSidebar";
import { BATCH_RENDER_ENABLED } from "./features";
import ForcePasswordChange from "./components/ForcePasswordChange";
import Footer from "./components/Footer";
import { TourHost } from "./components/GuidedTour";
import Login from "./components/Login";
import HomePage from "./components/HomePage";
import TopBar, { EVERYDAY } from "./components/TopBar";
import { branding } from "./branding";
import { useHashRoute, type Route } from "./hooks";
import type { AuthInfo } from "./types";
import { UserSettingsProvider } from "./userSettings";

// Each page is its own chunk, loaded when its route is first opened: the first paint needs only the sign-in screen
// or Home, not the editors, charts and admin pages behind the other routes. The markdown renderer and the guides
// (DocsPage) are the largest of them.
const AdminShell = lazy(() => import("./admin/AdminShell"));
const AnalyzePage = lazy(() => import("./components/AnalyzePage"));
const BatchRender = lazy(() => import("./components/BatchRender"));
const DashboardsPage = lazy(() => import("./components/DashboardsPage"));
const DocsPage = lazy(() => import("./components/DocsPage"));
const EmbedPage = lazy(() => import("./components/EmbedPage"));
const Gallery = lazy(() => import("./components/Gallery"));
const MyRunsPage = lazy(() => import("./components/MyRunsPage"));
const NewReportWizard = lazy(() => import("./components/NewReportWizard"));
const ReportsPage = lazy(() => import("./components/ReportsPage"));
const RunReportPage = lazy(() => import("./components/RunReportPage"));
const SchedulesPage = lazy(() => import("./components/SchedulesPage"));
const StarredPage = lazy(() => import("./components/StarredPage"));
const TemplateDetail = lazy(() => import("./components/TemplateDetail"));

const SIDEBAR_COLLAPSED_KEY = "portal_sidebar_collapsed";

export default function App() {
  const [auth, setAuth] = useState<AuthInfo | null>(null);
  const [checkedSession, setCheckedSession] = useState(false);
  const [route, navigate] = useHashRoute();
  // The everyday page you were last on, so leaving Manage takes you back there (Home if you came straight in).
  const lastEveryday = useRef<Route>({ view: "home" });
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
    return (
      <Suspense fallback={null}>
        <EmbedPage reportId={route.id} />
      </Suspense>
    );
  }

  if (!checkedSession) return null;

  if (!auth) {
    return (
      <>
        <DocumentTitle />
        <Login onSignedIn={setAuth} />
      </>
    );
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

  const canOpenAdmin = manageItems(auth).some((i) => i.route.view === "admin");
  // Home -- the person's own dashboard -- is everyone's landing page, whatever else they can manage.
  // A stale #/admin/..., #/schedules or #/templates link for a since-demoted or never-privileged user
  // renders this instead: no redirect side-effect needed, just don't take that branch below.
  const home: Route = { view: "home" };
  const effectiveRoute: Route =
    route.view === "admin" && !canOpenAdmin
      ? home
      : route.view === "schedules" && !has(auth, "job:view")
        ? home
        : (route.view === "batch" && !BATCH_RENDER_ENABLED) || ((route.view === "gallery" || route.view === "batch" || route.view === "new-report") && !canManageTemplates(auth))
            ? home
            : route;

  if (!isManageRoute(effectiveRoute)) lastEveryday.current = effectiveRoute;

  return (
    <UserSettingsProvider>
      {effectiveRoute.view !== "docs" && <DocumentTitle route={effectiveRoute} />}
      <div className="app-root">
        <div className="bg-texture" />
        <div className="bg-grain" />
        <TopBar auth={auth} route={effectiveRoute} navigate={navigate} />
        <TourHost route={effectiveRoute} />

        <div className="app-shell">
          {/* Only Manage pages have a sidebar; the everyday pages are all in the top bar. */}
          {isManageRoute(effectiveRoute) && (
            <AppSidebar
              route={effectiveRoute}
              backTo={lastEveryday.current}
              navigate={navigate}
              auth={auth}
              collapsed={sidebarCollapsed}
              onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
            />
          )}

          <div className="app-main">
            <div className="app-content">
              <Suspense fallback={null}>
                {effectiveRoute.view === "admin" ? (
                  <AdminShell route={effectiveRoute} auth={auth} />
                ) : effectiveRoute.view === "docs" ? (
                  <DocsPage route={effectiveRoute} navigate={navigate} />
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
                      <Gallery auth={auth} onOpenReport={(id) => navigate({ view: "detail", id })} onNewReport={() => navigate({ view: "new-report" })} />
                    )}
                    {effectiveRoute.view === "new-report" && (
                      <NewReportWizard auth={auth} reportId={effectiveRoute.id} navigate={navigate} />
                    )}
                    {effectiveRoute.view === "home" && (
                      <HomePage auth={auth} navigate={navigate} />
                    )}
                    {effectiveRoute.view === "runs" && <MyRunsPage navigate={navigate} />}
                    {effectiveRoute.view === "starred" && <StarredPage username={auth.username} navigate={navigate} />}
                    {effectiveRoute.view === "analyze" && <AnalyzePage auth={auth} viewId={effectiveRoute.id} navigate={navigate} />}
                    {effectiveRoute.view === "dashboards" && <DashboardsPage auth={auth} dashboardId={effectiveRoute.id} navigate={navigate} />}
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
              </Suspense>
            </div>

            <Footer />
          </div>
        </div>
      </div>
    </UserSettingsProvider>
  );
}

/** The browser tab's title: the brand, then where you are -- the everyday page by its top-bar name ("Aksor Khmer ·
 * Home", "· Reports" -- a report's run page included --, "· My runs", "· Starred"), or the console's own name in
 * Manage ("Aksor Khmer · Control Plane"). Signed out, the brand alone. The Docs page sets its own ("… ·
 * Documentation"). index.html sets the brand alone before the app loads, so nothing flashes. */
function DocumentTitle({ route }: { route?: Route }) {
  const page = !route
    ? null
    : isManageRoute(route)
      ? branding.productName
      : (EVERYDAY.find((item) => item.isActive(route))?.label ?? null);
  useEffect(() => {
    document.title = page ? `${branding.name} · ${page}` : branding.name;
  }, [page]);
  return null;
}
