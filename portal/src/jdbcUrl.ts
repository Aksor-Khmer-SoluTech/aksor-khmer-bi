// The standard JDBC URL for a database connection's fields, and the fields back
// out of a pasted URL -- the portal's live "URL <-> fields" link. The server
// (api/app/jdbc.py) has the authoritative copy of both and re-checks whatever
// is saved; keep the two in step.
import type { SslMode } from "./types";

export interface JdbcFields {
  engine: string;
  host: string;
  port: number;
  database: string;
  serviceType: "service_name" | "sid";
  sslMode: SslMode;
}

const hostForUrl = (host: string) => (host.includes(":") && !host.startsWith("[") ? `[${host}]` : host);

export function buildJdbcUrl(f: JdbcFields): string {
  const host = hostForUrl(f.host.trim());
  const db = encodeURIComponent(f.database.trim());
  switch (f.engine) {
    case "postgresql":
      return `jdbc:postgresql://${host}:${f.port}/${db}?sslmode=${f.sslMode}`;
    case "mysql": {
      const mode = { disable: "DISABLED", require: "REQUIRED", "verify-ca": "VERIFY_CA", "verify-full": "VERIFY_IDENTITY" }[f.sslMode];
      return `jdbc:mysql://${host}:${f.port}/${db}?sslMode=${mode}`;
    }
    case "mariadb": {
      const mode = { disable: "disable", require: "trust", "verify-ca": "verify-ca", "verify-full": "verify-full" }[f.sslMode];
      return `jdbc:mariadb://${host}:${f.port}/${db}?sslMode=${mode}`;
    }
    case "sqlserver": {
      const encrypt = f.sslMode !== "disable";
      const trust = f.sslMode === "disable" || f.sslMode === "require";
      return `jdbc:sqlserver://${host}:${f.port}${db ? `;databaseName=${db}` : ""};encrypt=${encrypt};trustServerCertificate=${trust}`;
    }
    case "db2":
      return `jdbc:db2://${host}:${f.port}/${db}${f.sslMode !== "disable" ? ":sslConnection=true;" : ""}`;
    case "oracle": {
      const sid = f.serviceType === "sid";
      if (f.sslMode === "disable") {
        return sid ? `jdbc:oracle:thin:@${host}:${f.port}:${f.database.trim()}` : `jdbc:oracle:thin:@//${host}:${f.port}/${f.database.trim()}`;
      }
      return `jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=tcps)(HOST=${f.host.trim()})(PORT=${f.port}))(CONNECT_DATA=(${sid ? "SID" : "SERVICE_NAME"}=${f.database.trim()})))`;
    }
    default:
      return "";
  }
}

export interface ParsedJdbcUrl {
  engine: string;
  host: string;
  port: number;
  database: string;
  serviceType: "service_name" | "sid" | null;
}

const DEFAULT_PORTS: Record<string, number> = { oracle: 1521, postgresql: 5432, mysql: 3306, sqlserver: 1433, mariadb: 3306, db2: 50000 };

function splitAuthority(authority: string, engine: string): { host: string; port: number } | null {
  if (authority.includes("@")) return null;
  let host: string;
  let portText: string;
  if (authority.startsWith("[")) {
    const end = authority.indexOf("]");
    host = authority.slice(1, end);
    portText = authority.slice(end + 1).replace(/^:/, "");
  } else {
    [host, portText = ""] = authority.split(":", 2);
  }
  if (!host) return null;
  const port = portText ? Number(portText) : DEFAULT_PORTS[engine];
  return Number.isInteger(port) ? { host, port } : null;
}

/** null when the text isn't (yet) a JDBC URL this portal understands -- it's called on every keystroke. */
export function parseJdbcUrl(raw: string): ParsedJdbcUrl | null {
  const url = raw.trim();
  if (!/^jdbc:/i.test(url)) return null;
  const body = url.slice(5);
  const lower = body.toLowerCase();

  if (lower.startsWith("oracle:thin:@")) {
    const target = body.slice("oracle:thin:@".length);
    if (target.startsWith("(")) {
      const found: Record<string, string> = {};
      for (const m of target.matchAll(/\((HOST|PORT|SERVICE_NAME|SID)\s*=\s*([^()\s]+)\)/gi)) found[m[1].toUpperCase()] = m[2];
      if (!found.HOST) return null;
      return {
        engine: "oracle",
        host: found.HOST,
        port: /^\d+$/.test(found.PORT ?? "") ? Number(found.PORT) : 1521,
        database: found.SERVICE_NAME ?? found.SID ?? "",
        serviceType: found.SID && !found.SERVICE_NAME ? "sid" : "service_name",
      };
    }
    if (target.startsWith("//")) {
      const [authority, ...rest] = target.slice(2).split("/");
      const hp = splitAuthority(authority, "oracle");
      return hp && { engine: "oracle", ...hp, database: rest.join("/").split("?")[0], serviceType: "service_name" };
    }
    const m = /^([^:/]+):(\d+)([:/])(.+)$/.exec(target);
    return m && { engine: "oracle", host: m[1], port: Number(m[2]), database: m[4], serviceType: m[3] === ":" ? "sid" : "service_name" };
  }

  for (const engine of ["postgresql", "mysql", "mariadb", "sqlserver", "db2"]) {
    if (!lower.startsWith(`${engine}://`)) continue;
    const rest = body.slice(engine.length + 3);
    if (engine === "sqlserver") {
      const [authority, ...props] = rest.split(";");
      const hp = splitAuthority(authority, engine);
      let database = "";
      for (const pair of props) {
        const [k, v = ""] = pair.split("=");
        if (["databasename", "database"].includes(k.trim().toLowerCase())) database = v.trim();
      }
      return hp && { engine, ...hp, database, serviceType: null };
    }
    const slash = rest.indexOf("/");
    const authority = slash === -1 ? rest : rest.slice(0, slash);
    const hp = splitAuthority(authority, engine);
    let database = slash === -1 ? "" : rest.slice(slash + 1).split("?")[0];
    if (engine === "db2") database = database.split(":")[0];
    try {
      database = decodeURIComponent(database);
    } catch {
      /* keep it as typed */
    }
    return hp && { engine, ...hp, database, serviceType: null };
  }
  return null;
}
