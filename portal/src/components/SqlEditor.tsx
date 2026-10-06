import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap, type CompletionContext } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, indentOnInput, syntaxHighlighting, HighlightStyle, syntaxTree } from "@codemirror/language";
import { Compartment, EditorState, type Extension } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  placeholder as placeholderExtension,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { MSSQL, MariaSQL, MySQL, PLSQL, PostgreSQL, StandardSQL, sql, type SQLDialect } from "@codemirror/lang-sql";
import { tags as t } from "@lezer/highlight";

/** Which keyword/quoting rules to colour by, for each database engine a connection can be (api/app/jdbc.py).
 * Oracle -> PL/SQL, SQL Server -> T-SQL, ... ; DB2 has no dialect of its own, so it gets standard SQL. */
const DIALECTS: Record<string, { dialect: SQLDialect; label: string }> = {
  postgresql: { dialect: PostgreSQL, label: "PostgreSQL" },
  mysql: { dialect: MySQL, label: "MySQL" },
  mariadb: { dialect: MariaSQL, label: "MariaDB" },
  sqlserver: { dialect: MSSQL, label: "SQL Server (T-SQL)" },
  oracle: { dialect: PLSQL, label: "Oracle (PL/SQL)" },
  db2: { dialect: StandardSQL, label: "DB2 (standard SQL)" },
};
const FALLBACK = { dialect: StandardSQL, label: "standard SQL" };

export interface SqlFilter {
  name: string;
  /** The filter's input type (text, number, date, datetime, time) -- decides how it is offered. */
  type: string;
}

/** What to write for a filter in a query. A filter's value always reaches the database as text, whatever its
 * type, so a date or number needs converting in the SQL; this is the usual way to do that on each engine
 * (Oracle's date functions need the format spelled out). Text filters are used as they are. */
export function bindSnippet(filter: SqlFilter, engine: string | null | undefined, typed = false): string {
  const bound = `:${filter.name}`;
  if (typed) return bound; // already a real date / number when it arrives
  switch (filter.type) {
    case "number":
      return engine === "oracle" ? `TO_NUMBER(${bound})` : engine === "db2" || engine === "sqlserver" || engine === "mysql" || engine === "mariadb" ? `CAST(${bound} AS DECIMAL(31, 10))` : `CAST(${bound} AS NUMERIC)`;
    case "date":
      return engine === "oracle" ? `TO_DATE(${bound}, 'YYYY-MM-DD')` : `CAST(${bound} AS DATE)`;
    case "datetime":
      return engine === "oracle" ? `TO_TIMESTAMP(${bound}, 'YYYY-MM-DD"T"HH24:MI')` : engine === "sqlserver" ? `CAST(${bound} AS DATETIME2)` : engine === "mysql" || engine === "mariadb" ? `CAST(${bound} AS DATETIME)` : `CAST(${bound} AS TIMESTAMP)`;
    case "time":
      return engine === "oracle" ? `TO_DATE(${bound}, 'HH24:MI')` : `CAST(${bound} AS TIME)`;
    default:
      return bound;
  }
}

export const sqlDialectLabel = (engine: string | null | undefined) => (DIALECTS[engine ?? ""] ?? FALLBACK).label;

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.operatorKeyword, t.modifier], color: "var(--accent-strong)", fontWeight: "600" },
  { tag: [t.string, t.special(t.string)], color: "var(--success-strong)" },
  { tag: [t.number, t.bool, t.null], color: "var(--highlight-strong)" },
  { tag: [t.lineComment, t.blockComment], color: "var(--text-faint)", fontStyle: "italic" },
  { tag: [t.typeName, t.standard(t.name)], color: "var(--highlight-strong)" },
  { tag: [t.operator, t.punctuation, t.separator], color: "var(--text-dim)" },
  { tag: [t.special(t.name), t.quote], color: "var(--text)" },
]);

/** JOIN words get a colour of their own -- they're what shapes a query, and what people look for. */
const JOIN_WORDS = /\b(?:(?:natural|left|right|full|inner|cross|outer)\s+)*join\b|\b(?:on|using)\b(?=\s|\()/gi;
const NOT_CODE = new Set(["String", "Comment", "LineComment", "BlockComment", "QuotedIdentifier", "Literal"]);

function decorator(regexp: RegExp, className: string) {
  const mark = Decoration.mark({ class: className });
  const matcher = new MatchDecorator({
    regexp,
    // Only real code: the word "join" inside a string or a comment is just text.
    decoration: (_match, view, pos) => {
      const node = syntaxTree(view.state).resolveInner(pos, 1).name;
      return NOT_CODE.has(node) || node.includes("Comment") || node.includes("String") ? null : mark;
    },
  });
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;
      constructor(view: EditorView) {
        this.decorations = matcher.createDeco(view);
      }
      update(u: ViewUpdate) {
        this.decorations = matcher.updateDeco(u, this.decorations);
      }
    },
    { decorations: (v) => v.decorations },
  );
}

const theme = EditorView.theme({
  "&": {
    fontFamily: "var(--font-mono)",
    fontSize: "0.82rem",
    fontVariantLigatures: "none", // `>=` and `<>` must look like what they are
    color: "var(--text)",
    backgroundColor: "var(--bg-input)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm, 6px)",
  },
  "&.cm-focused": { outline: "none", borderColor: "var(--accent)", boxShadow: "0 0 0 3px var(--accent-soft)" },
  ".cm-scroller": { fontFamily: "inherit", lineHeight: "1.6", overflow: "auto" },
  ".cm-content": { caretColor: "var(--text)", padding: "8px 0" },
  ".cm-line": { padding: "0 12px" },
  ".cm-cursor": { borderLeftColor: "var(--text)" },
  ".cm-gutters": {
    backgroundColor: "var(--bg-panel)",
    color: "var(--text-faint)",
    border: "none",
    borderRight: "1px solid var(--border-soft)",
    borderRadius: "var(--radius-sm, 6px) 0 0 var(--radius-sm, 6px)",
  },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 10px 0 12px", minWidth: "2.2em" },
  ".cm-activeLine": { backgroundColor: "var(--accent-soft)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--bg-panel-hover)", color: "var(--text)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": { backgroundColor: "var(--accent-soft)" },
  ".cm-placeholder": { color: "var(--text-faint)" },
  ".cm-matchingBracket": { backgroundColor: "var(--highlight-soft)", outline: "1px solid var(--highlight)" },
  ".cm-sql-join": { color: "var(--highlight-strong)", fontWeight: "700" },
  ".cm-sql-param": { color: "var(--highlight-strong)", backgroundColor: "var(--highlight-soft)", borderRadius: "3px", padding: "0 2px" },
  ".cm-tooltip": { backgroundColor: "var(--bg-raised)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "var(--accent-soft)", color: "var(--text)" },
});

export interface SqlEditorHandle {
  /** Put `text` where the cursor is (replacing a selection) and keep typing from there. */
  insertAtCursor: (text: string) => void;
}

/** A small SQL editor: line numbers, syntax colours for the connection's database engine (JOINs and `:filter`
 * placeholders stand out), auto-closing brackets, undo, Tab to indent and keyword / filter suggestions. */
const SqlEditor = forwardRef<SqlEditorHandle, {
  value: string;
  onChange: (value: string) => void;
  /** Engine id of the chosen connection (postgresql, mysql, oracle ...); unknown -> standard SQL. */
  engine?: string | null;
  /** Filter names offered after typing `:`. */
  filters?: SqlFilter[];
  /** The source binds filters by type, so a date or number needs no conversion written. */
  typedBinding?: boolean;
  placeholder?: string;
  rows?: number;
  ariaLabel?: string;
}>(function SqlEditor({ value, onChange, engine, filters = [], typedBinding = false, placeholder, rows = 10, ariaLabel = "SQL query" }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const language = useRef(new Compartment());
  const onChangeRef = useRef(onChange);
  const filtersRef = useRef(filters);
  const engineRef = useRef(engine);
  const typedRef = useRef(typedBinding);
  onChangeRef.current = onChange;
  filtersRef.current = filters;
  engineRef.current = engine;
  typedRef.current = typedBinding;

  const languageFor = (id: string | null | undefined): Extension => sql({ dialect: (DIALECTS[id ?? ""] ?? FALLBACK).dialect, upperCaseKeywords: true });

  useImperativeHandle(ref, () => ({
    insertAtCursor(text: string) {
      const v = view.current;
      if (!v) return;
      const { from, to } = v.state.selection.main;
      v.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length }, userEvent: "input" });
      v.focus();
    },
  }));

  useEffect(() => {
    const filterCompletions = (context: CompletionContext) => {
      const word = context.matchBefore(/:\w*/);
      if (!word || (word.from === word.to && !context.explicit)) return null;
      return {
        from: word.from,
        options: filtersRef.current.flatMap((filter) => {
          const plain = { label: `:${filter.name}`, type: "variable", detail: `filter (${filter.type})` };
          const converted = bindSnippet(filter, engineRef.current, typedRef.current);
          // A date or number is offered a second time with the engine's conversion already written.
          return converted === `:${filter.name}` ? [plain] : [plain, { label: converted, apply: converted, type: "variable", detail: `${filter.type}, converted` }];
        }),
        validFor: /^:\w*$/,
      };
    };
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        history(),
        drawSelection(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        autocompletion({ icons: false }),
        EditorState.languageData.of(() => [{ autocomplete: filterCompletions }]),
        language.current.of(languageFor(engine)),
        syntaxHighlighting(highlight),
        decorator(JOIN_WORDS, "cm-sql-join"),
        decorator(/:[A-Za-z_]\w*/g, "cm-sql-param"),
        keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, ...completionKeymap, indentWithTab]),
        placeholderExtension(placeholder ?? ""),
        EditorView.contentAttributes.of({ "aria-label": ariaLabel, spellcheck: "false" }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) onChangeRef.current(u.state.doc.toString());
        }),
        theme,
      ],
    });
    view.current = new EditorView({ state, parent: host.current! });
    return () => {
      view.current?.destroy();
      view.current = null;
    };
    // The editor is created once; value / engine changes are pushed in by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A change from outside (a different report, or Reset) -- not one the editor itself just made.
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: language.current.reconfigure(languageFor(engine)) });
  }, [engine]);

  // Height: `rows` lines, growing no further, then it scrolls.
  const lineHeight = 0.82 * 1.6;
  return <div ref={host} className="sql-editor" style={{ ["--sql-rows" as string]: `${rows * lineHeight + 1}rem` }} />;
});

export default SqlEditor;
