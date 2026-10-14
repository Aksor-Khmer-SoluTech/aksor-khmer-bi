import { CircleAlert, FileWarning, PlugZap, RotateCw, Rows3, ShieldAlert, Timer, type LucideIcon } from "lucide-react";
import { ApiError } from "../api";

/** Why running a data source failed -- sample data, a REST API or a database -- shown where its data would have
 * appeared, not in a banner the person has scrolled away from. The heading says which kind of failure it is, the
 * server's own message says what exactly, and the hint says where to look. */

export type SourceKind = "static" | "rest" | "jdbc" | "dataset" | string;

export interface RunFailure {
  /** HTTP status from the API; 0 when the API itself couldn't be reached; -1 for a problem found before sending. */
  status: number;
  message: string;
}

export function toRunFailure(err: unknown, fallback: string): RunFailure {
  if (err instanceof ApiError) return { status: err.status, message: err.message };
  return { status: 0, message: fallback };
}

function describe(kind: SourceKind, status: number, message: string): { icon: LucideIcon; title: string; hint: string } {
  if (status === -1) {
    return { icon: FileWarning, title: "The sample data isn't valid JSON", hint: "Fix it where the message points, or press Insert example to start from a working one." };
  }
  if (status === 0) {
    return { icon: PlugZap, title: "Couldn't reach the server", hint: "Check your network, then try again. If it keeps happening, the API may be down." };
  }
  if (status === 401 || status === 403) {
    return { icon: ShieldAlert, title: "You aren't allowed to run this", hint: "Ask someone who manages it for access, or sign in again." };
  }
  if (status === 400 || status === 422) {
    return {
      icon: CircleAlert,
      title: kind === "jdbc" ? "The query can't run as written" : kind === "rest" ? "The request isn't set up right" : "The source isn't set up right",
      hint:
        kind === "jdbc"
          ? "A query must be one SELECT (or WITH … SELECT); write filters as :name. Fix it above and run again."
          : kind === "rest"
            ? "Check the path and the filters it uses ({{ name }}), and that the connection is chosen."
            : "Fix the setting the message names, then run again.",
    };
  }
  // 502 and anything else: the source itself answered badly or not at all. The server's message says which way.
  const db = kind === "jdbc";
  const http = /HTTP (\d{3})/.exec(message);
  if (/couldn't connect|couldn't reach/i.test(message)) {
    return db
      ? { icon: PlugZap, title: "Couldn't connect to the database", hint: "Check its host, port and login under Manage → Connections — Test connection there says what's wrong." }
      : { icon: PlugZap, title: "Couldn't reach the API", hint: "Check the URL (or the connection's base URL) for a typo, and that this server can reach that address." };
  }
  if (/took too long|time limit|timed out/i.test(message)) {
    return { icon: Timer, title: "It took too long", hint: db ? "Narrow it with a filter, or ask whoever owns the database about an index." : "Narrow the request with a filter, or try again when the API is less busy." };
  }
  if (/more than [\d,]+ rows|too large/i.test(message)) {
    return { icon: Rows3, title: "That's too much data", hint: "Narrow it with a filter (a date range, a branch) so it returns fewer rows." };
  }
  if (http) {
    const code = Number(http[1]);
    return {
      icon: CircleAlert,
      title: `The API answered with an error (HTTP ${code})`,
      hint:
        code === 401 || code === 403
          ? "Its credential was refused: check the Secret the connection uses."
          : code === 404
            ? "Nothing at that address: check the path and the filter values in it."
            : code >= 500
              ? "The API itself failed. Try again later, or ask whoever runs it."
              : "Check the path, its filter values and the request body.",
    };
  }
  if (/valid JSON|JSON object/i.test(message)) {
    return { icon: FileWarning, title: "The API's answer isn't usable JSON", hint: "A data source must answer with a JSON object ({ … }). Check the path points at the data, not a web page." };
  }
  if (/rejected the query/i.test(message)) {
    return { icon: CircleAlert, title: "The database rejected the query", hint: "Run it in your database's own tool with the same values to see why — a misspelt column or table is the usual cause." };
  }
  if (/no longer (exists|allows)/i.test(message)) {
    return { icon: CircleAlert, title: "Something it uses is gone", hint: "A connection, dataset, filter or procedure it names was removed. Choose another, or ask whoever manages it." };
  }
  if (kind === "jdbc") {
    return {
      icon: PlugZap,
      title: "The database didn't answer the query",
      hint: "Check the connection under Manage → Connections (Test connection), and run the query in your database's own tool with the same values.",
    };
  }
  if (kind === "rest") {
    return {
      icon: PlugZap,
      title: "The API call failed",
      hint: "Check the connection's base URL and credential, and try the same request with the same values in a REST client.",
    };
  }
  return { icon: PlugZap, title: "The data source failed", hint: "Check its settings and try again." };
}

export default function SourceRunError({ failure, kind, onRetry, retrying = false }: { failure: RunFailure; kind: SourceKind; onRetry?: () => void; retrying?: boolean }) {
  const { icon: Icon, title, hint } = describe(kind, failure.status, failure.message);
  return (
    <div role="alert" className="source-run-error">
      <span className="source-run-error-icon" aria-hidden="true">
        <Icon size={20} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="source-run-error-title">{title}</p>
        <p className="source-run-error-message">{failure.message}</p>
        <p className="source-run-error-hint">{hint}</p>
      </div>
      {onRetry && (
        <button type="button" className="btn btn-sm shrink-0" onClick={onRetry} disabled={retrying}>
          {retrying ? <span className="spinner" /> : <RotateCw size={13} aria-hidden="true" />} Try again
        </button>
      )}
    </div>
  );
}
