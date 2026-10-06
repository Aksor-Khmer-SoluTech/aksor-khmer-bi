import { useEffect, useState, type FormEvent } from "react";
import { ExternalLink, ShieldAlert } from "lucide-react";
import { api, ApiError } from "../../api";
import DbEnginePicker from "../../components/DbEnginePicker";
import FileDropzone from "../../components/FileDropzone";
import { onDialogCancel, useDialogRef } from "../../hooks";
import type { JdbcDriver, JdbcEngine, Organization } from "../../types";

import ModalClose from "../../components/ModalClose";
const NAME_MAX = 80;

/** Upload a vendor JDBC driver (.jar). Mounted fresh per open, like the other admin dialogs. */
export default function DriverUploadDialog({
  open,
  onClose,
  engines,
  organizations,
  defaultOrgId,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  engines: JdbcEngine[];
  organizations: Organization[];
  defaultOrgId: string;
  onUploaded: (driver: JdbcDriver) => void;
}) {
  // Start on an engine that has no built-in driver: that's what most uploads are for.
  const [engine, setEngine] = useState<JdbcEngine>(engines.find((e) => !e.built_in) ?? engines[0]);
  const [name, setName] = useState("");
  const [driverClass, setDriverClass] = useState(engine.driver_class);
  const [classEdited, setClassEdited] = useState(false);
  const [orgId, setOrgId] = useState(defaultOrgId);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ref = useDialogRef(open);

  useEffect(() => {
    if (!classEdited) setDriverClass(engine.driver_class);
  }, [engine, classEdited]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return setError("Choose the driver's .jar file");
    setPending(true);
    setError(null);
    try {
      onUploaded(await api.jdbc.drivers.upload({ name: name.trim(), engine: engine.id, driverClass: driverClass.trim(), orgId, file }));
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't upload the driver");
    } finally {
      setPending(false);
    }
  }

  return (
    <dialog ref={ref} className="modal conn-dialog conn-dialog-wide jdbc-dialog" onCancel={onDialogCancel(onClose)}>
      <ModalClose />
      <h2 className="panel-title">Upload a JDBC driver</h2>
      <p className="panel-subtitle">
        The vendor's driver file for a database this server has no built-in driver for. Connections then choose it by name.
      </p>
      <form onSubmit={handleSubmit}>
        <section className="jdbc-section">
          <h3 className="jdbc-heading">Engine</h3>
          <DbEnginePicker
            engines={engines}
            value={engine.id}
            onChange={setEngine}
          />
          <a className="jdbc-vendor-link" href={engine.driver_url} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={13} aria-hidden="true" /> Download the {engine.label} driver from the vendor
          </a>
        </section>

        <section className="jdbc-section">
          <div className="jdbc-grid">
            <label>
              <span className="field-label-row">
                <span>Name</span>
                <span className={`char-counter${name.length >= NAME_MAX ? " char-counter-limit" : ""}`}>
                  {name.length}/{NAME_MAX}
                </span>
              </span>
              <input
                type="text"
                required
                maxLength={NAME_MAX}
                placeholder={`${engine.label} — ojdbc11 23.4`}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              <span>Driver class</span>
              <input
                type="text"
                className="mono-input"
                required
                spellCheck={false}
                value={driverClass}
                onChange={(e) => {
                  setClassEdited(true);
                  setDriverClass(e.target.value);
                }}
              />
            </label>
            <div className="field-block jdbc-span-2">
              <span className="field-label">Driver file (.jar)</span>
              <FileDropzone
                file={file}
                onFile={(f) => {
                  setError(null);
                  setFile(f);
                }}
                onClear={() => setFile(null)}
                onReject={setError}
                accept=".jar,application/java-archive"
                exts={["jar"]}
                idleTitle="Drag & drop the driver .jar here"
                compact
              />
              <p className="field-hint jdbc-file-hint">
                The upload is checked: it must be a .jar that contains the driver class above. Its SHA-256 is recorded and re-checked
                before every use.
              </p>
            </div>
            {organizations.length > 1 && (
              <label>
                <span>Organization</span>
                <select value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  {organizations.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </section>

        <aside className="jdbc-code-warning">
          <ShieldAlert size={18} aria-hidden="true" />
          <div>
            <strong>A driver is code, and loading it runs it.</strong>
            <p>
              Upload only a file you downloaded from the vendor yourself. It runs in the isolated driver service — with no access to this
              platform's database or keys — but whoever can upload one is trusted like someone who can deploy code. Every upload is audited
              with its hash.
            </p>
          </div>
        </aside>

        {error && <p className="alert alert-error">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {pending && <span className="spinner" />}
            Upload driver
          </button>
        </div>
      </form>
    </dialog>
  );
}
