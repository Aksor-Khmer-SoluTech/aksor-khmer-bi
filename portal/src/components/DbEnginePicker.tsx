import type { JdbcEngine } from "../types";
import DbEngineIcon from "./DbEngineIcon";

/** The engine choice as a row of cards, each with its mark -- a radio group, so it works from the keyboard. */
export default function DbEnginePicker({
  engines,
  value,
  onChange,
  disabled = false,
}: {
  engines: JdbcEngine[];
  value: string;
  onChange: (engine: JdbcEngine) => void;
  disabled?: boolean;
}) {
  return (
    <div className="db-engines" role="radiogroup" aria-label="Database engine">
      {engines.map((engine) => (
        <label key={engine.id} className={`db-engine${value === engine.id ? " selected" : ""}${disabled ? " disabled" : ""}`}>
          <input
            type="radio"
            name="db-engine"
            value={engine.id}
            checked={value === engine.id}
            disabled={disabled}
            onChange={() => onChange(engine)}
          />
          <DbEngineIcon engine={engine.id} size={34} />
          <span className="db-engine-name">{engine.label}</span>
          <span className="db-engine-tag">{engine.built_in ? "built in" : "needs driver"}</span>
        </label>
      ))}
    </div>
  );
}
