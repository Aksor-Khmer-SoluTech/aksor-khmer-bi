/** A field's label row: its name with a required star or "(optional)", and -- when the field has a limit -- how much
 * of it is used ("12/100", turning to the warning colour at the limit). The New Template wizard's look
 * (field-label-row / char-counter), for any form. Goes inside the field's <label>, before its input. */
export default function FieldLabel({
  children,
  required = false,
  length,
  max,
}: {
  children: React.ReactNode;
  required?: boolean;
  /** The value's current length; with `max`, shows the counter. */
  length?: number;
  max?: number;
}) {
  return (
    <span className="field-label-row">
      <span>
        {children}{" "}
        {required ? (
          <span className="required-mark" aria-hidden="true">
            *
          </span>
        ) : (
          <span className="muted">(optional)</span>
        )}
      </span>
      {max !== undefined && length !== undefined && (
        <span className={length >= max ? "char-counter char-counter-limit" : "char-counter"} aria-live="polite">
          {length}/{max}
        </span>
      )}
    </span>
  );
}

/** The API's limits for a person's account fields (api/app/models/rbac.py: USERNAME_MAX, EMAIL_MAX, DISPLAY_NAME_MAX). */
export const USERNAME_MAX = 100;
export const EMAIL_MAX = 254;
export const DISPLAY_NAME_MAX = 100;
