import { useEffect, useId, useRef, useState, type ClipboardEvent, type KeyboardEvent, type ReactNode } from "react";
import { X } from "lucide-react";
import { MAX_TERM_LENGTH, MAX_TERMS, parseTerms } from "../terms";
import TermChips from "./TermChips";

/** A tag-style editor for a list of protected terms: type a term and press
 * Enter and it becomes a pill; paste a column of them and each becomes one;
 * click a pill to correct it; × removes it. Much quicker to fill in -- and to
 * read back -- than a block of one-per-line text, and it says so at once when
 * a term is already there or too long instead of at save time.
 *
 * Khmer specifics: a term is often several words ("ធនាគារ អេស៊ីលីដា"), so
 * only Enter ends one, never Space; and Enter that is merely *committing an
 * IME composition* must not add a half-typed term. Whatever is still typed
 * when the box loses focus is added too -- clicking Save straight after
 * typing must not silently drop the last term. */
export default function TermsInput({
  label,
  hint,
  terms,
  onChange,
  variant = "protect",
  readOnly = false,
  placeholder = "Type a term, press Enter — or paste a list",
}: {
  label: string;
  hint?: ReactNode;
  terms: string[];
  onChange: (next: string[]) => void;
  /** "exclude" draws the pills dashed and quiet, matching how the same
   * terms look everywhere else they are shown read-only. */
  variant?: "protect" | "exclude";
  readOnly?: boolean;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  // First Backspace on an empty box only *marks* the last pill; the second
  // removes it -- so a stray keypress can't silently delete a term.
  const [armed, setArmed] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [tick, setTick] = useState(0);

  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const chipRefs = useRef(new Map<string, HTMLElement>());
  const pulse = useRef<{ term: string; kind: "new" | "dupe" } | null>(null);
  // An edit that has already been applied (or abandoned with Escape) must
  // not be applied a second time by the blur that follows it unmounting.
  const editHandled = useRef(false);

  // After a change lands in the DOM, scroll the affected pill into view and
  // give it a short highlight (new = accent wash, dupe = a nudge on the
  // existing one). Done on the element directly so it can restart on demand.
  useEffect(() => {
    const p = pulse.current;
    if (!p) return;
    pulse.current = null;
    const el = chipRefs.current.get(p.term);
    if (!el) return;
    el.scrollIntoView({ block: "nearest" });
    const cls = p.kind === "new" ? "terms-pulse-new" : "terms-pulse-dupe";
    el.classList.remove("terms-pulse-new", "terms-pulse-dupe");
    void el.offsetWidth; // restart the animation if it was already running
    el.classList.add(cls);
    el.addEventListener("animationend", () => el.classList.remove(cls), { once: true });
  }, [tick]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4500);
    return () => clearTimeout(timer);
  }, [notice]);

  function say(text: string) {
    setAnnouncement(text);
  }

  /** Adds each of `raw` that is new and valid; reports what it skipped. */
  function add(raw: string[]) {
    const next = [...terms];
    const seen = new Set(terms);
    let added = 0;
    let dupes = 0;
    let tooLong = 0;
    let full = false;
    let lastAdded: string | null = null;
    let lastDupe: string | null = null;
    for (const item of raw) {
      const term = item.trim();
      if (!term) continue;
      if (seen.has(term)) {
        dupes++;
        lastDupe = term;
      } else if (term.length > MAX_TERM_LENGTH) {
        tooLong++;
      } else if (next.length >= MAX_TERMS) {
        full = true;
        break;
      } else {
        next.push(term);
        seen.add(term);
        added++;
        lastAdded = term;
      }
    }
    if (added > 0) onChange(next);

    const bits: string[] = [];
    if (raw.length > 1 && added > 0) bits.push(`Added ${added}`);
    if (dupes > 0) bits.push(raw.length === 1 && lastDupe ? `“${lastDupe}” is already in the list` : `${dupes} already in the list`);
    if (tooLong > 0) bits.push(`${tooLong} too long (max ${MAX_TERM_LENGTH} characters)`);
    if (full) bits.push(`The list is full (max ${MAX_TERMS} terms)`);
    setNotice(bits.length ? bits.join(" · ") : null);
    say(added === 1 && lastAdded ? `Added ${lastAdded}` : added > 1 ? `Added ${added} terms` : dupes > 0 ? "Already in the list" : "");

    const target = lastAdded ?? lastDupe;
    if (target) {
      pulse.current = { term: target, kind: lastAdded ? "new" : "dupe" };
      setTick((n) => n + 1);
    }
  }

  function commitDraft() {
    const text = draft.trim();
    if (!text) return;
    if (text.length > MAX_TERM_LENGTH) {
      // Keep what was typed so it can be shortened rather than retyped.
      setNotice(`Too long (max ${MAX_TERM_LENGTH} characters)`);
      return;
    }
    add([text]);
    setDraft("");
  }

  function remove(term: string) {
    onChange(terms.filter((t) => t !== term));
    say(`Removed ${term}`);
    inputRef.current?.focus();
  }

  function startEdit(term: string) {
    editHandled.current = false;
    setEditing(term);
    setEditText(term);
  }

  function commitEdit() {
    if (editing === null || editHandled.current) return;
    editHandled.current = true;
    const old = editing;
    const next = editText.trim();
    setEditing(null);
    if (next === old) return;
    if (!next) {
      onChange(terms.filter((t) => t !== old));
      return;
    }
    if (next.length > MAX_TERM_LENGTH) {
      setNotice(`Too long (max ${MAX_TERM_LENGTH} characters) — kept as it was`);
      return;
    }
    if (terms.includes(next)) {
      // Edited into a term that already exists: merge into that one.
      onChange(terms.filter((t) => t !== old));
      setNotice(`“${next}” is already in the list`);
      pulse.current = { term: next, kind: "dupe" };
    } else {
      onChange(terms.map((t) => (t === old ? next : t)));
      pulse.current = { term: next, kind: "new" };
    }
    setTick((n) => n + 1);
  }

  // Enter that finishes an IME composition reports isComposing (or the
  // legacy keyCode 229); it must confirm the text, not add a term.
  const composing = (e: KeyboardEvent) => e.nativeEvent.isComposing || e.keyCode === 229;

  function onInputKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (composing(e)) return;
    if (e.key === "Enter") {
      // Also keeps Enter from submitting a surrounding form.
      e.preventDefault();
      commitDraft();
    } else if (e.key === "Backspace" && draft === "" && terms.length > 0) {
      e.preventDefault();
      if (armed) {
        remove(terms[terms.length - 1]);
        setArmed(false);
      } else {
        setArmed(true);
      }
    } else if (armed && e.key !== "Shift") {
      setArmed(false);
    }
  }

  function onInputPaste(e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    // One line pastes into the box as usual; several lines (a column copied
    // from a spreadsheet, a text file) become several terms at once.
    if (!/[\r\n\t]/.test(text.trim())) return;
    e.preventDefault();
    add(parseTerms(text));
  }

  const count = `${terms.length} ${terms.length === 1 ? "term" : "terms"}`;
  const exclude = variant === "exclude";

  return (
    <div className={`terms-field${exclude ? " terms-field-exclude" : ""}`}>
      <label className="terms-label" htmlFor={readOnly ? undefined : inputId}>
        {label}
      </label>

      {readOnly ? (
        <div className="terms-box terms-box-readonly">
          <TermChips terms={terms} muted={exclude} empty="None" />
        </div>
      ) : (
        <div
          className="terms-box"
          onMouseDown={(e) => {
            // Anywhere in the box that isn't itself a control puts the
            // caret in the input, like clicking into a text field.
            if ((e.target as HTMLElement).closest("button, input")) return;
            e.preventDefault();
            inputRef.current?.focus();
          }}
        >
          <ul className="terms-chips terms-chips-editing">
            {terms.map((t, i) =>
              editing === t ? (
                <li key={t} className="terms-chip terms-chip-editing">
                  <input
                    className="terms-chip-input"
                    value={editText}
                    autoFocus
                    aria-label={`Edit ${t}`}
                    style={{ width: `${Math.max(8, editText.length + 2)}ch` }}
                    onChange={(e) => setEditText(e.target.value)}
                    onFocus={(e) => e.currentTarget.select()}
                    onKeyDown={(e) => {
                      if (composing(e)) return;
                      if (e.key === "Enter") {
                        e.preventDefault();
                        commitEdit();
                      } else if (e.key === "Escape") {
                        e.preventDefault();
                        e.stopPropagation();
                        editHandled.current = true;
                        setEditing(null);
                        inputRef.current?.focus();
                      }
                    }}
                    onBlur={commitEdit}
                  />
                </li>
              ) : (
                <li
                  key={t}
                  ref={(el) => {
                    if (el) chipRefs.current.set(t, el);
                    else chipRefs.current.delete(t);
                  }}
                  className={`terms-chip terms-chip-editable${armed && i === terms.length - 1 ? " is-armed" : ""}`}
                >
                  <button type="button" className="terms-chip-text" title="Click to edit" onClick={() => startEdit(t)}>
                    {t}
                  </button>
                  <button type="button" className="terms-chip-x" aria-label={`Remove ${t}`} title="Remove" onClick={() => remove(t)}>
                    <X size={12} strokeWidth={2.2} aria-hidden="true" />
                  </button>
                </li>
              ),
            )}
            <li className="terms-add">
              <input
                id={inputId}
                ref={inputRef}
                type="text"
                value={draft}
                maxLength={MAX_TERM_LENGTH * 2}
                placeholder={terms.length === 0 ? placeholder : "Add another…"}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => {
                  setDraft(e.target.value);
                  if (armed) setArmed(false);
                }}
                onKeyDown={onInputKeyDown}
                onPaste={onInputPaste}
                onBlur={() => {
                  setArmed(false);
                  commitDraft();
                }}
              />
            </li>
          </ul>
        </div>
      )}

      <div className="terms-field-foot">
        <span className={`field-hint${notice ? " terms-notice" : ""}`}>
          {notice ??
            (draft.trim() ? (
              <>
                Press <kbd>Enter</kbd> to add
              </>
            ) : (
              hint
            ))}
        </span>
        <span className="terms-count">{count}</span>
      </div>
      <span className="sr-only" role="status" aria-live="polite">
        {announcement}
      </span>
    </div>
  );
}
