import CopyButton from "../../components/CopyButton";
import { useDialogRef } from "../../hooks";
import type { ApiClientWithSecret } from "../../types";

/** The one place a client's secret is ever shown: the server keeps only its hash, so once this
 * closes there is no way to read it again -- only to rotate it for a new one. */
export default function ClientSecretDialog({
  result,
  heading,
  onClose,
}: {
  result: ApiClientWithSecret | null;
  heading: string;
  onClose: () => void;
}) {
  const ref = useDialogRef(result !== null);

  return (
    // Escape is ignored on purpose: the secret can't be brought back, so leaving needs a click.
    <dialog ref={ref} className="modal" onCancel={(e) => e.preventDefault()}>
      <h2 className="panel-title">{heading}</h2>
      {result && (
        <>
          <p className="alert alert-warning">
            Copy the secret now — it is shown only this once and can't be looked up later. Lost it? Rotate the secret
            for a new one.
          </p>
          <div className="client-credential">
            <span className="client-credential-label">Client ID</span>
            <code className="mono client-credential-value">{result.client.client_id}</code>
            <CopyButton text={result.client.client_id} />
          </div>
          <div className="client-credential">
            <span className="client-credential-label">Client secret</span>
            <code className="mono client-credential-value">{result.secret}</code>
            <CopyButton text={result.secret} />
          </div>
          <p className="muted" style={{ fontSize: "0.82rem" }}>
            The embedding app sends both with each run. Keep the secret out of source control and URLs.
          </p>
        </>
      )}
      <div className="dialog-actions">
        <button type="button" className="btn btn-primary" onClick={onClose}>
          I've saved it
        </button>
      </div>
    </dialog>
  );
}
