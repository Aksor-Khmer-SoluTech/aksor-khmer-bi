import { apiBaseUrl } from "../../api";

export default function ApiExplorerPage() {
  const docsUrl = `${apiBaseUrl()}/docs`;

  return (
    <div className="api-explorer">
      <div className="page-header">
        <div>
          <h1 className="page-title">API Explorer</h1>
          <p className="page-subtitle">
            The backend's own interactive OpenAPI docs, embedded — use the <strong>Authorize</strong> button inside
            (sign in with <code>/auth/login</code> there, then paste the access token into <em>HTTPBearer</em>; separate from this session) to unlock <strong>Try it out</strong>. See also{" "}
            <a href={`${apiBaseUrl()}/redoc`} target="_blank" rel="noreferrer">
              ReDoc
            </a>
            .
          </p>
        </div>
        <a className="btn btn-sm" href={docsUrl} target="_blank" rel="noreferrer">
          Open in new tab ↗
        </a>
      </div>
      <div className="api-explorer-frame">
        <iframe src={docsUrl} title="OpenAPI / Swagger UI" />
      </div>
    </div>
  );
}
