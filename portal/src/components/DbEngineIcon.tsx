import type { CSSProperties } from "react";
import db2 from "../assets/db/db2.svg";
import mariadb from "../assets/db/mariadb.svg";
import mysql from "../assets/db/mysql.svg";
import oracle from "../assets/db/oracle.svg";
import postgresql from "../assets/db/postgresql.svg";
import sqlserver from "../assets/db/sqlserver.svg";

// Each engine's mark, from src/assets/db, painted in its brand colour on a light
// tile (so it reads the same in the light and dark themes). The marks are the
// vendors' trademarks, shown only to say which database a connection is for.
const ENGINE_MARKS: Record<string, { src: string; color: string }> = {
  oracle: { src: oracle, color: "#F80000" },
  postgresql: { src: postgresql, color: "#336791" },
  mysql: { src: mysql, color: "#00758F" },
  sqlserver: { src: sqlserver, color: "#CC2927" },
  mariadb: { src: mariadb, color: "#003545" },
  db2: { src: db2, color: "#0F62FE" },
};

export default function DbEngineIcon({ engine, size = 32 }: { engine: string; size?: number }) {
  const mark = ENGINE_MARKS[engine];
  const style = {
    width: size,
    height: size,
    "--db-color": mark?.color ?? "var(--text-dim)",
    "--db-mark": mark ? `url("${mark.src}")` : "none",
  } as CSSProperties;
  return <span className="db-icon" style={style} aria-hidden="true" />;
}
