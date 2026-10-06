import { PluginsIcon } from "../icons";

export default function PluginsPage() {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Plugins</h1>
          <p className="page-subtitle">Extend this console without forking it.</p>
        </div>
      </div>

      <div className="empty-state plugins-empty">
        <div className="plugins-empty-icon">
          <PluginsIcon />
        </div>
        <p>No plugins installed yet.</p>
        <p className="muted" style={{ maxWidth: 440, margin: "8px auto 0" }}>
          This is a reserved extension point, not a stub: a future plugin registers its own backend
          router the way <code className="mono">api/app/routers/system.py</code> does today, plus a
          sidebar entry here the way <code className="mono">Users</code>, <code className="mono">Roles</code>,
          and <code className="mono">Monitor</code> already do — installed, configured, and enabled per
          organization from this page once that loader lands.
        </p>
      </div>
    </div>
  );
}
