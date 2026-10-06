// The editable shape of a report's data configuration -- its filter parameters
// (Parameters tab) and where its data comes from (Data source tab) -- and the
// draft both tabs share.
//
// The two tabs are two views of one configuration, saved together
// (PUT /reports/{id}/data-config replaces both): a data source's URL refers to
// parameters by name ({{ fromDate }}) and the server checks that they exist, so
// renaming a parameter and updating the URL that uses it has to be one save --
// two separate saves would each be refused. The draft lives above the tabs
// (TemplateDetail), so edits survive switching between them, and either tab's
// Save button saves both.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { defaultCredentialValue, type CredentialValue } from "./components/CredentialPicker";
import { NOW_EXPRESSION } from "./dateFormat";
import type {
  ConnectionSummary,
  DataConfig,
  DataSource,
  DataSourceAuth,
  DataSourceType,
  OptionsSource,
  ParameterType,
  ReportParameter,
} from "./types";

// --- request (the part a data source and a REST-backed choice list share) -------------

export interface EditableRequest {
  /** Name of a connection, or "" to write a full URL. */
  connection: string;
  /** A full URL, or -- with a connection -- the path after its base URL. */
  url: string;
  method: "GET" | "POST";
  headersText: string;
  bodyText: string;
  authType: "none" | "bearer" | "basic";
  credential: CredentialValue;
  username: string;
}

export const EMPTY_REQUEST: EditableRequest = {
  connection: "",
  url: "",
  method: "GET",
  headersText: "",
  bodyText: "",
  authType: "none",
  credential: defaultCredentialValue(),
  username: "",
};

interface RequestShape {
  connection: string | null;
  url: string;
  method: "GET" | "POST";
  headers: Record<string, string> | null;
  auth: DataSourceAuth | null;
}

/** "Name: value" lines <-> a header map -- quicker to paste a real set into than a row-per-header editor. */
export function parseHeaders(text: string): Record<string, string> | null {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const colon = line.indexOf(":");
    if (colon > 0) headers[line.slice(0, colon).trim()] = line.slice(colon + 1).trim();
  }
  return Object.keys(headers).length > 0 ? headers : null;
}

export function headersToText(headers: Record<string, string> | null | undefined): string {
  return Object.entries(headers ?? {})
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}

function bodyToText(body: unknown): string {
  return body == null ? "" : typeof body === "string" ? body : JSON.stringify(body, null, 2);
}

function toEditableRequest(s: RequestShape, body: unknown): EditableRequest {
  return {
    connection: s.connection ?? "",
    url: s.url,
    method: s.method,
    headersText: headersToText(s.headers),
    bodyText: bodyToText(body),
    authType: s.auth?.type ?? "none",
    credential: defaultCredentialValue(
      s.auth?.token_env ?? s.auth?.password_env,
      s.auth?.token_secret ?? s.auth?.password_secret
    ),
    username: s.auth?.username ?? "",
  };
}

function toRequestShape(e: EditableRequest): RequestShape {
  // With a connection, authentication is the connection's -- whatever this
  // form last held for a raw URL is not sent.
  let auth: DataSourceAuth | null = null;
  const fromEnv = e.credential.source === "env";
  if (!e.connection && e.authType === "bearer") {
    auth = fromEnv ? { type: "bearer", token_env: e.credential.env.trim() } : { type: "bearer", token_secret: e.credential.secret };
  }
  if (!e.connection && e.authType === "basic") {
    auth = fromEnv
      ? { type: "basic", username: e.username.trim(), password_env: e.credential.env.trim() }
      : { type: "basic", username: e.username.trim(), password_secret: e.credential.secret };
  }
  return {
    connection: e.connection || null,
    url: e.url.trim(),
    method: e.method,
    headers: parseHeaders(e.headersText),
    auth,
  };
}

/** A body typed as JSON is sent as JSON; anything else as plain text (POST only). */
function parseBody(e: EditableRequest): DataSource["body_template"] {
  const text = e.bodyText.trim();
  if (e.method !== "POST" || !text) return null;
  try {
    const parsed = JSON.parse(text);
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : text;
  } catch {
    return text;
  }
}

// --- data source ---------------------------------------------------------------------

/** A database source: which connection (Admin > Connections), and the SELECT to run. */
export interface EditableJdbc {
  connection: string;
  query: string;
  /** What the rows are called in the template; blank = `rows`. */
  rootKey: string;
  /** Hand the database each filter as its declared type, so the query needs no CAST. */
  typedBinding: boolean;
}

// A new source binds by type; a saved one keeps what it had (absent = text, as before this existed).
export const EMPTY_JDBC: EditableJdbc = { connection: "", query: "", rootKey: "", typedBinding: true };

/** The three kinds of source share one editable shape; only `type`'s own part is
 * sent. Switching type clears the other parts (see DataConfigDraft.setSourceType). */
export interface EditableSource {
  type: DataSourceType;
  request: EditableRequest;
  jdbc: EditableJdbc;
  /** Sample data, as the JSON text being edited. */
  staticText: string;
}

export const EMPTY_SOURCE: EditableSource = { type: "rest", request: EMPTY_REQUEST, jdbc: EMPTY_JDBC, staticText: "" };

export function toEditableSource(s: DataSource): EditableSource {
  const type = s.type ?? "rest";
  return {
    type,
    request: type === "rest" ? toEditableRequest(s, s.body_template) : EMPTY_REQUEST,
    jdbc: type === "jdbc" ? { connection: s.connection ?? "", query: s.query ?? "", rootKey: s.root_key ?? "", typedBinding: s.typed_binding === true } : EMPTY_JDBC,
    staticText: type === "static" && s.static_data ? JSON.stringify(s.static_data, null, 2) : "",
  };
}

/** The sample data text as an object, or why it isn't one. Blank is "nothing yet", not an error. */
export function parseStaticData(text: string): { value: Record<string, unknown> | null; error: string | null } {
  if (!text.trim()) return { value: null, error: null };
  try {
    const parsed = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { value: null, error: "Sample data must be a JSON object, like { \"rows\": [ … ] }" };
    }
    return { value: parsed as Record<string, unknown>, error: null };
  } catch (err) {
    return { value: null, error: `Not valid JSON — ${err instanceof Error ? err.message : "check the syntax"}` };
  }
}

const NO_REQUEST = { url: "", method: "GET" as const, headers: null, body_template: null, auth: null };

export function toDataSource(e: EditableSource): DataSource {
  if (e.type === "jdbc") {
    return {
      type: "jdbc",
      connection: e.jdbc.connection || null,
      ...NO_REQUEST,
      query: e.jdbc.query.trim(),
      root_key: e.jdbc.rootKey.trim() || null,
      typed_binding: e.jdbc.typedBinding,
    };
  }
  if (e.type === "static") {
    return { type: "static", connection: null, ...NO_REQUEST, static_data: parseStaticData(e.staticText).value };
  }
  return { type: "rest", ...toRequestShape(e.request), body_template: parseBody(e.request) };
}

/** Whether the chosen type holds anything worth warning about before it's thrown away. */
export function sourceConfigured(e: EditableSource): boolean {
  if (e.type === "jdbc") return Boolean(e.jdbc.connection || e.jdbc.query.trim());
  if (e.type === "static") return e.staticText.trim() !== "";
  const r = e.request;
  return Boolean(r.connection || r.url.trim() || r.headersText.trim() || r.bodyText.trim() || r.authType !== "none");
}

// --- parameters ----------------------------------------------------------------------

export type DefaultMode = "none" | "fixed" | "now";

/** A `date`, `datetime` or `time` parameter can default to the moment it's run. */
export const supportsNow = (type: ParameterType) => type === "date" || type === "datetime" || type === "time";

export interface EditableParameter {
  key: number;
  name: string;
  label: string;
  kind: "choices" | "text";
  /** Only for kind === "choices": typed here, or fetched from a REST API. */
  choicesFrom: "list" | "api";
  optionsText: string;
  /** Only for kind === "text" -- which input the run page renders. */
  textType: ParameterType;
  /** Only for kind === "text" -- a choice list is required regardless (see
   * ReportParameter's own docstring on the API side). */
  required: boolean;
  /** Only for kind === "text": what the field starts with. `fixed` uses
   * `defaultValue` (ISO for a date/time); `now` is `now()`. */
  defaultMode: DefaultMode;
  defaultValue: string;
  /** Only for choicesFrom === "api". */
  request: EditableRequest;
  itemsPath: string;
  valuePath: string;
  labelPath: string;
}

let nextKey = 1;

export function newParameter(): EditableParameter {
  return {
    key: nextKey++,
    name: "",
    label: "",
    kind: "text",
    choicesFrom: "list",
    optionsText: "",
    textType: "text",
    required: true,
    defaultMode: "none",
    defaultValue: "",
    request: EMPTY_REQUEST,
    itemsPath: "",
    valuePath: "",
    labelPath: "",
  };
}

export function toEditableParameter(p: ReportParameter): EditableParameter {
  const source = p.options_source;
  return {
    key: nextKey++,
    name: p.name,
    label: p.label ?? "",
    kind: p.options === null && source === null ? "text" : "choices",
    choicesFrom: source ? "api" : "list",
    optionsText: (p.options ?? []).map((o) => (o.label ? `${o.value} | ${o.label}` : o.value)).join("\n"),
    textType: p.type,
    required: p.required,
    defaultMode: p.default_value === NOW_EXPRESSION ? "now" : p.default_value ? "fixed" : "none",
    defaultValue: p.default_value && p.default_value !== NOW_EXPRESSION ? p.default_value : "",
    request: source ? toEditableRequest(source, source.body) : EMPTY_REQUEST,
    itemsPath: source?.items_path ?? "",
    valuePath: source?.value_field ?? "",
    labelPath: source?.label_field ?? "",
  };
}

function parseOptions(text: string): { value: string; label: string | null }[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const bar = line.indexOf("|");
      return bar === -1
        ? { value: line, label: null }
        : { value: line.slice(0, bar).trim(), label: line.slice(bar + 1).trim() || null };
    });
}

export function toOptionsSource(e: EditableParameter): OptionsSource {
  const body = parseBody(e.request);
  return {
    ...toRequestShape(e.request),
    body: body !== null && typeof body === "object" ? body : null,
    items_path: e.itemsPath.trim() || null,
    value_field: e.valuePath.trim(),
    label_field: e.labelPath.trim() || null,
  };
}

function toDefault(e: EditableParameter): string | null {
  if (e.kind !== "text") return null;
  if (e.defaultMode === "now" && supportsNow(e.textType)) return NOW_EXPRESSION;
  if (e.defaultMode === "fixed") return e.defaultValue.trim() || null;
  return null;
}

export function toParameter(e: EditableParameter): ReportParameter {
  const fixed = e.kind === "choices" && e.choicesFrom === "list";
  const options = fixed ? parseOptions(e.optionsText) : [];
  return {
    name: e.name.trim(),
    label: e.label.trim() || null,
    type: e.kind === "text" ? e.textType : "text",
    // A choice list can't be optional (see ReportParameter's docstring on the
    // API side) -- forced true regardless of what this row's checkbox last
    // showed, so switching kind back to "choices" can't carry over a stale
    // "optional" from when it was free text.
    required: e.kind === "text" ? e.required : true,
    default_value: toDefault(e),
    options: options.length > 0 ? options : null,
    options_source: e.kind === "choices" && e.choicesFrom === "api" ? toOptionsSource(e) : null,
  };
}

const nameOf = (p: EditableParameter) => `“${p.label.trim() || p.name.trim() || "New parameter"}”`;

/** Problems the server would only half-report (or quietly "fix" into something
 * else), caught before saving. null = nothing to say. */
export function validateDraft(parameters: EditableParameter[]): string | null {
  for (const p of parameters) {
    if (p.kind !== "choices") continue;
    if (p.choicesFrom === "list" && parseOptions(p.optionsText).length === 0) {
      return `${nameOf(p)} is a choice list with no choices — add some, fetch them from a REST API, or make it free text.`;
    }
    if (p.choicesFrom === "api" && p.request.method === "POST" && p.request.bodyText.trim()) {
      let ok = false;
      try {
        const parsed = JSON.parse(p.request.bodyText);
        ok = parsed !== null && typeof parsed === "object" && !Array.isArray(parsed);
      } catch {
        /* falls through */
      }
      if (!ok) return `The request body for ${nameOf(p)} must be a JSON object.`;
    }
  }
  return null;
}

// --- the shared draft ------------------------------------------------------------------

type Status = "idle" | "loading" | "ready" | "error";

export interface DataConfigDraft {
  status: Status;
  loadError: string | null;
  parameters: EditableParameter[];
  addParameter: () => void;
  updateParameter: (key: number, patch: Partial<EditableParameter>) => void;
  removeParameter: (key: number) => void;
  useSource: boolean;
  setUseSource: (on: boolean) => void;
  source: EditableSource;
  /** Edits to the REST part / the database part / the sample data of the source. */
  updateRequest: (patch: Partial<EditableRequest>) => void;
  updateJdbc: (patch: Partial<EditableJdbc>) => void;
  setStaticText: (text: string) => void;
  /** Change the kind of source. What the previous kind held is cleared from the form -- the
   * tab asks first when there was something (see DataSourceTab). */
  setSourceType: (type: DataSourceType) => void;
  /** Why the sample data can't be saved, if it can't. */
  staticError: string | null;
  /** A source is saved on the server for this report (as opposed to only being typed into the form). */
  savedSource: boolean;
  /** Unsaved changes on the Parameters tab / the Data source tab. */
  parametersDirty: boolean;
  sourceDirty: boolean;
  save: () => Promise<void>;
  saving: boolean;
  saveError: string | null;
  /** True from a successful save until the next edit. */
  saved: boolean;
  /** null while loading; [] when there are none -- or the list isn't available to this person. */
  connections: ConnectionSummary[] | null;
  connectionsAvailable: boolean;
}

/** Load a report's data config once one of the two tabs is opened, and hold
 * the edits. `enabled` says a tab that needs it is showing. */
export function useDataConfigDraft(reportId: string, enabled: boolean): DataConfigDraft {
  const [status, setStatus] = useState<Status>("idle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [parameters, setParameters] = useState<EditableParameter[]>([]);
  const [useSource, setUseSourceState] = useState(false);
  const [source, setSource] = useState<EditableSource>(EMPTY_SOURCE);
  const [baseline, setBaseline] = useState({ parameters: "[]", source: "null" });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [connections, setConnections] = useState<ConnectionSummary[] | null>(null);
  const [connectionsAvailable, setConnectionsAvailable] = useState(true);
  const loadedFor = useRef<string | null>(null);
  const request = useRef(0);

  const serialize = (config: DataConfig) => ({
    parameters: JSON.stringify(config.parameters.map((p) => toParameter(toEditableParameter(p)))),
    source: JSON.stringify(config.data_source ? toDataSource(toEditableSource(config.data_source)) : null),
  });

  function apply(config: DataConfig) {
    setParameters(config.parameters.map(toEditableParameter));
    setUseSourceState(config.data_source !== null);
    setSource(config.data_source ? toEditableSource(config.data_source) : EMPTY_SOURCE);
    setBaseline(serialize(config));
  }

  useEffect(() => {
    if (!enabled || loadedFor.current === reportId) return;
    loadedFor.current = reportId;
    const mine = ++request.current;
    setStatus("loading");
    setLoadError(null);
    setSaved(false);
    setSaveError(null);
    api
      .getDataConfig(reportId)
      .then((config) => {
        if (mine !== request.current) return;
        apply(config);
        setStatus("ready");
      })
      .catch((err) => {
        if (mine !== request.current) return;
        loadedFor.current = null; // let the next visit to a tab try again
        setLoadError(err instanceof ApiError ? err.message : "Couldn't load this report's data settings");
        setStatus("error");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- apply only sets state
  }, [reportId, enabled]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setConnections(null);
    api.connections
      .list()
      .then((list) => {
        if (cancelled) return;
        setConnections(list);
        setConnectionsAvailable(true);
      })
      .catch(() => {
        // Not everyone who edits a report may list connections; they can still write full URLs.
        if (cancelled) return;
        setConnections([]);
        setConnectionsAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, reportId]);

  const touch = useCallback(() => setSaved(false), []);

  const draftParameters = useMemo(() => JSON.stringify(parameters.map(toParameter)), [parameters]);
  const draftSource = useMemo(() => JSON.stringify(useSource ? toDataSource(source) : null), [useSource, source]);

  const staticError = useSource && source.type === "static" ? parseStaticData(source.staticText).error : null;

  const save = useCallback(async () => {
    const problem = validateDraft(parameters) ?? (useSource && source.type === "static" ? parseStaticData(source.staticText).error : null);
    if (problem) {
      setSaveError(problem);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const config = await api.putDataConfig(reportId, {
        parameters: parameters.map(toParameter),
        data_source: useSource ? toDataSource(source) : null,
      });
      apply(config);
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- apply only sets state
  }, [reportId, parameters, useSource, source]);

  return {
    status,
    loadError,
    parameters,
    addParameter: () => {
      touch();
      setParameters((prev) => [...prev, newParameter()]);
    },
    updateParameter: (key, patch) => {
      touch();
      setParameters((prev) => prev.map((p) => (p.key === key ? { ...p, ...patch } : p)));
    },
    removeParameter: (key) => {
      touch();
      setParameters((prev) => prev.filter((p) => p.key !== key));
    },
    useSource,
    setUseSource: (on) => {
      touch();
      setUseSourceState(on);
    },
    source,
    updateRequest: (patch) => {
      touch();
      setSource((prev) => ({ ...prev, request: { ...prev.request, ...patch } }));
    },
    updateJdbc: (patch) => {
      touch();
      setSource((prev) => ({ ...prev, jdbc: { ...prev.jdbc, ...patch } }));
    },
    setStaticText: (text) => {
      touch();
      setSource((prev) => ({ ...prev, staticText: text }));
    },
    setSourceType: (type) => {
      touch();
      // A fresh source of the new type: the old one's settings are gone from the form.
      setSource({ ...EMPTY_SOURCE, type });
    },
    staticError,
    savedSource: baseline.source !== "null",
    parametersDirty: status === "ready" && draftParameters !== baseline.parameters,
    sourceDirty: status === "ready" && draftSource !== baseline.source,
    save,
    saving,
    saveError,
    saved,
    connections,
    connectionsAvailable,
  };
}
