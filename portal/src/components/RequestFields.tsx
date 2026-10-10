import { useRef } from "react";
import { Cable } from "lucide-react";
import CredentialPicker from "./CredentialPicker";
import type { EditableRequest } from "../dataConfig";
import type { ConnectionSummary } from "../types";

const AUTH_LABEL: Record<ConnectionSummary["auth_type"], string> = {
  none: "no authentication",
  bearer: "a bearer token",
  basic: "basic authentication (username + password)",
};

/** The request half of a REST source -- which connection (or full URL), method,
 * path, body, headers and authentication -- shared by a report's data source
 * and a REST-backed choice list, which differ only in what they do with the
 * response. */
export default function RequestFields({
  value,
  onChange,
  connections,
  connectionsAvailable,
  canManageConnections,
  canManageSecrets,
  orgId,
  placeholders,
  bodyHint,
  urlExample,
}: {
  value: EditableRequest;
  onChange: (patch: Partial<EditableRequest>) => void;
  /** null while loading. */
  connections: ConnectionSummary[] | null;
  connectionsAvailable: boolean;
  canManageConnections: boolean;
  /** Gates "+ New credential" in the authentication picker below -- someone without it may still pick an existing one. */
  canManageSecrets: boolean;
  orgId: string;
  /** Filter names that can be dropped into the URL as {{ name }} -- a data source has them, a choice list doesn't. */
  placeholders?: string[];
  bodyHint: string;
  urlExample: string;
}) {
  const urlRef = useRef<HTMLInputElement>(null);
  const selected = connections?.find((c) => c.name === value.connection) ?? null;
  const withConnection = value.connection !== "";

  function pickConnection(name: string) {
    const next = connections?.find((c) => c.name === name) ?? null;
    let url = value.url;
    // Keep what was typed: a full URL that starts with the base URL becomes the
    // path after it; going the other way puts the base URL back in front.
    if (next && url.startsWith(next.base_url)) url = url.slice(next.base_url.length);
    else if (!next && selected && (url === "" || url[0] === "/" || url[0] === "?")) url = selected.base_url + url;
    onChange({ connection: name, url });
  }

  function insertFilter(name: string) {
    const input = urlRef.current;
    const token = `{{ ${name} }}`;
    const start = input?.selectionStart ?? value.url.length;
    const end = input?.selectionEnd ?? value.url.length;
    onChange({ url: value.url.slice(0, start) + token + value.url.slice(end) });
    requestAnimationFrame(() => {
      input?.focus();
      input?.setSelectionRange(start + token.length, start + token.length);
    });
  }

  const manageLink = canManageConnections ? (
    <a href="#/admin/connections" className="req-manage-link">
      Manage connections
    </a>
  ) : null;

  return (
    <>
      <div className="req-connection">
        <label>
          <span>Connection</span>
          <select value={value.connection} onChange={(e) => pickConnection(e.target.value)} disabled={connections === null}>
            <option value="">None — write the full URL</option>
            {connections?.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name} — {c.base_url}
              </option>
            ))}
            {/* A name the list doesn't have (deleted, or the list isn't visible to this person) still has to show. */}
            {withConnection && connections !== null && !selected && (
              <option value={value.connection}>{connectionsAvailable ? `${value.connection} (not found)` : value.connection}</option>
            )}
          </select>
        </label>
        {manageLink}
      </div>
      {connections !== null && connections.length === 0 && connectionsAvailable && (
        <p className="field-hint data-config-hint">
          No connections yet. A connection keeps a base URL, headers and authentication in one place, so reports only add a path — and
          when the API moves, you change it once.{canManageConnections ? " Create one, then come back." : " Ask an administrator to create one."}
        </p>
      )}
      {withConnection && connections !== null && !selected &&
        (connectionsAvailable ? (
          <p className="alert alert-error req-note">
            There's no connection called “{value.connection}” in this organization — pick another, or clear it and write a full URL.
          </p>
        ) : (
          <p className="field-hint data-config-hint">
            You can't list connections, so “{value.connection}” isn't shown here — it's still what this report uses.
          </p>
        ))}

      <div className="data-config-row data-config-url-row">
        <label className="data-config-method">
          <span>Method</span>
          <select value={value.method} onChange={(e) => onChange({ method: e.target.value as "GET" | "POST" })}>
            <option value="GET">GET</option>
            <option value="POST">POST</option>
          </select>
        </label>
        <label className="data-config-url">
          <span>{withConnection ? "Path" : "URL"}</span>
          <span className="req-url">
            {withConnection && selected && (
              <span className="req-url-base" title={selected.base_url}>
                {selected.base_url}
              </span>
            )}
            <input
              ref={urlRef}
              type="text"
              className="mono-input"
              value={value.url}
              placeholder={withConnection ? urlExample.replace(/^https?:\/\/[^/]+/, "") : urlExample}
              onChange={(e) => onChange({ url: e.target.value })}
            />
          </span>
        </label>
      </div>
      {placeholders && placeholders.length > 0 && (
        <div className="req-chips" role="group" aria-label="Insert a filter value">
          <span className="req-chips-label">Insert filter</span>
          {placeholders.map((name) => (
            <button key={name} type="button" className="chip-btn" onClick={() => insertFilter(name)} title={`Insert {{ ${name} }} at the cursor`}>
              {name}
            </button>
          ))}
        </div>
      )}
      <p className="field-hint data-config-hint">
        {withConnection
          ? "Starts with / (or ?) and follows the connection's base URL. "
          : "Write the scheme and host out in full — a value can never choose where the server connects. "}
        {placeholders && placeholders.length > 0 && (
          <>
            Insert a filter value with {"{{ name }}"}; values are URL-encoded for you.
          </>
        )}
      </p>

      {value.method === "POST" && (
        <label>
          <span>{bodyHint}</span>
          <textarea
            className="mono-input"
            rows={4}
            value={value.bodyText}
            placeholder={placeholders?.[0] ? `{ "${placeholders[0]}": "{{ ${placeholders[0]} }}" }` : '{ "active": true }'}
            onChange={(e) => onChange({ bodyText: e.target.value })}
          />
        </label>
      )}

      <label>
        <span>
          {withConnection ? "Extra headers" : "Headers"} — one “Name: value” per line
          {withConnection ? "" : " (use authentication below for secrets)"}
        </span>
        <textarea
          className="mono-input"
          rows={2}
          value={value.headersText}
          placeholder="X-Api-Version: 2"
          onChange={(e) => onChange({ headersText: e.target.value })}
        />
      </label>
      {withConnection && selected && selected.header_names.length > 0 && (
        <p className="field-hint data-config-hint">
          Also sent, from the connection: <span className="mono">{selected.header_names.join(", ")}</span>. A header written here with the same
          name replaces it.
        </p>
      )}

      {withConnection ? (
        <p className="req-auth-note">
          <Cable size={14} aria-hidden="true" />
          <span>
            Authentication comes from the connection{selected ? ` — ${AUTH_LABEL[selected.auth_type]}` : ""}.
            {canManageConnections ? " Change it under Manage → Connections." : ""}
          </span>
        </p>
      ) : (
        <>
          <div className="data-config-row">
            <label>
              <span>Authentication</span>
              <select value={value.authType} onChange={(e) => onChange({ authType: e.target.value as EditableRequest["authType"] })}>
                <option value="none">None</option>
                <option value="bearer">Bearer token</option>
                <option value="basic">Basic (username + password)</option>
              </select>
            </label>
            {value.authType === "basic" && (
              <label>
                <span>Username</span>
                <input type="text" value={value.username} onChange={(e) => onChange({ username: e.target.value })} />
              </label>
            )}
          </div>
          {value.authType !== "none" && (
            <CredentialPicker
              label={value.authType === "bearer" ? "Token" : "Password"}
              value={value.credential}
              onChange={(credential) => onChange({ credential })}
              canManageSecrets={canManageSecrets}
              orgId={orgId}
            />
          )}
        </>
      )}
    </>
  );
}
