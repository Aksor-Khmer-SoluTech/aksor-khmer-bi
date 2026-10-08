import {
  closestCenter,
  defaultDropAnimationSideEffects,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MeasuringStrategy,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable } from "@dnd-kit/sortable";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Activity, AlertTriangle, BookOpen, CalendarClock, FileText, GripVertical, Layers, Play, RotateCcw, ShieldCheck, Star } from "lucide-react";
import { api } from "../api";
import { has } from "../admin/sections";
import { useFavoriteReports } from "../favorites";
import { useHomeLayout } from "../homeLayout";
import type { Route } from "../hooks";
import type { AccessibleReport, AuthInfo, MyDashboard } from "../types";
import { LinesSkeleton, StatRowSkeleton } from "./Skeletons";

/** "5 minutes ago" / "yesterday" / a date -- how long ago something happened. */
function ago(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  if (seconds < 172_800) return "yesterday";
  return new Date(iso).toLocaleDateString();
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

const greeting = () => {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
};

/** The cards, in their default order. Each has a fixed width on the 12-column grid; a person only chooses the
 * order (drag a card by its grip, or focus the grip and use Space + arrow keys), remembered in this browser. */
const CARDS = ["kpis", "trend", "shortcuts", "starred", "top", "recent"] as const;
type CardId = (typeof CARDS)[number];
const SPAN: Record<CardId, string> = { kpis: "span-12", trend: "span-8", shortcuts: "span-4", starred: "span-6", top: "span-6", recent: "span-12" };

/** Cards are different sizes, so dnd-kit's own sortable transforms (which slide a card onto its neighbour's
 * rectangle, scaling it to fit) look jumpy. Instead the order is changed live while dragging, the grid simply
 * re-flows, and each card glides from where it was to where it now is (a FLIP animation). The pointer is the
 * thing that picks the target, so a big card dragged over a small one doesn't flip back and forth. */
const collide: CollisionDetection = (args) => {
  const hits = pointerWithin(args);
  return hits.length ? hits : closestCenter(args);
};

/** Animate the grid's children from their previous position to their new one whenever `order` changes. */
function useFlip(grid: React.RefObject<HTMLElement | null>, order: string[]) {
  const last = useRef(new Map<string, { x: number; y: number }>());
  useLayoutEffect(() => {
    const el = grid.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const next = new Map<string, { x: number; y: number }>();
    for (const child of Array.from(el.children) as HTMLElement[]) {
      const id = child.dataset.cardId;
      if (!id) continue;
      const now = { x: child.offsetLeft, y: child.offsetTop };
      next.set(id, now);
      const before = last.current.get(id);
      if (!before || reduce) continue;
      // Where it still appears to be, if a previous glide hasn't finished.
      const inFlight = new DOMMatrix(getComputedStyle(child).transform);
      const dx = before.x + inFlight.m41 - now.x;
      const dy = before.y + inFlight.m42 - now.y;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      child.style.transition = "none";
      child.style.transform = `translate(${dx}px, ${dy}px)`;
      child.getBoundingClientRect(); // commit the starting position
      child.style.transition = "transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1)";
      child.style.transform = "";
      child.addEventListener("transitionend", () => (child.style.transition = ""), { once: true });
    }
    last.current = next;
  }, [grid, order]);
}

/** Everyone's landing page: what *they* have been doing, the reports they use most, and the shortcuts they
 * are likely to want. The numbers come from GET /me/dashboard (only the caller's own runs); what they may
 * open comes from the accessible-reports list, so a report they've since lost access to is shown but can't
 * be run from here. */
export default function HomePage({
  auth,
  canAdmin,
  navigate,
}: {
  auth: AuthInfo;
  canAdmin: boolean;
  navigate: (route: Route) => void;
}) {
  const [mine, setMine] = useState<MyDashboard | null>(null);
  const [reports, setReports] = useState<AccessibleReport[] | null>(null);
  const [failed, setFailed] = useState(false);
  const { favorites, toggle } = useFavoriteReports(auth.username);
  const { order, save, reset, customised } = useHomeLayout(auth.username, CARDS);
  const [live, setLive] = useState<string[] | null>(null); // the order while a card is being dragged
  const [activeId, setActiveId] = useState<string | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const shown = live ?? order;
  useFlip(grid, shown);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));

  useEffect(() => {
    api.me.dashboard().then(setMine).catch(() => setFailed(true));
    api.listAccessibleReports().then(setReports).catch(() => setReports([]));
  }, []);

  const runnable = useMemo(() => new Map((reports ?? []).filter((r) => r.access_level !== "view").map((r) => [r.report_id, r])), [reports]);
  const starred = favorites.map((id) => runnable.get(id)).filter((r): r is AccessibleReport => Boolean(r));
  const run = (id: string) => navigate({ view: "run", id });

  const onDragStart = ({ active }: DragStartEvent) => setActiveId(String(active.id));
  const onDragOver = ({ active, over }: DragOverEvent) => {
    if (!over || active.id === over.id) return;
    setLive((current) => {
      const now = current ?? order;
      const from = now.indexOf(String(active.id));
      const to = now.indexOf(String(over.id));
      return from < 0 || to < 0 || from === to ? current : arrayMove(now, from, to);
    });
  };
  const onDragEnd = (_: DragEndEvent) => {
    if (live) save(live);
    setLive(null);
    setActiveId(null);
  };
  const onDragCancel = () => {
    setLive(null);
    setActiveId(null);
  };

  const cards: Record<CardId, { title: string; icon: ReactNode; body: ReactNode }> = {
    kpis: {
      title: "Your activity",
      icon: <Activity size={16} aria-hidden="true" />,
      body: (
        <>
          {failed && <p className="alert alert-error">Couldn't load your activity.</p>}
          {!mine && !failed && <StatRowSkeleton count={4} />}
          {mine && (
            <div className="home-kpis">
              <Kpi value={mine.runs_7d} label="runs this week" series={mine.daily.slice(-7).map((d) => d.runs)} />
              <Kpi value={mine.runs_30d} label="runs in 30 days" series={mine.daily.map((d) => d.runs)} />
              <Kpi value={mine.failed_30d} label="failed in 30 days" series={mine.daily.map((d) => d.failed)} tone={mine.failed_30d ? "danger" : undefined} />
              <Kpi value={reports ? reports.length : "…"} label="reports you can see" />
            </div>
          )}
        </>
      ),
    },
    trend: {
      title: "Runs, last 30 days",
      icon: <Layers size={16} aria-hidden="true" />,
      body: !mine && !failed ? <LinesSkeleton count={4} /> : mine ? <RunsChart days={mine.daily} /> : null,
    },
    shortcuts: {
      title: "Shortcuts",
      icon: <FileText size={16} aria-hidden="true" />,
      body: (
        <div className="home-shortcuts">
          <Shortcut icon={<FileText size={15} />} label="All reports" onClick={() => navigate({ view: "reports" })} />
          <Shortcut icon={<BookOpen size={15} />} label="Guides" onClick={() => navigate({ view: "docs" })} />
          {has(auth, "job:view") && <Shortcut icon={<CalendarClock size={15} />} label="Schedules" onClick={() => navigate({ view: "schedules" })} />}
          {canAdmin && <Shortcut icon={<ShieldCheck size={15} />} label="Admin console" onClick={() => navigate({ view: "admin", section: "dashboard" })} />}
        </div>
      ),
    },
    starred: {
      title: "Starred reports",
      icon: <Star size={16} aria-hidden="true" />,
      body: (
        <>
          {reports === null && <LinesSkeleton count={3} />}
          {reports !== null && starred.length === 0 && (
            <p className="muted">
              Nothing starred yet. Press <Star size={13} style={{ display: "inline", verticalAlign: "-2px" }} aria-hidden="true" /> on a report in{" "}
              <a className="link-btn" href="#/reports">
                Reports
              </a>{" "}
              to keep it here.
            </p>
          )}
          {starred.map((r) => (
            <ReportLine key={r.report_id} name={r.name} hint={r.description} onRun={() => run(r.report_id)} onUnstar={() => toggle(r.report_id)} />
          ))}
        </>
      ),
    },
    top: {
      title: "Most used",
      icon: <Layers size={16} aria-hidden="true" />,
      body: (
        <>
          {!mine && !failed && <LinesSkeleton count={3} />}
          {mine && mine.top_reports.length === 0 && <p className="muted">Reports you run will show up here.</p>}
          {mine?.top_reports.map((t) => {
            const known = runnable.get(t.report_id);
            return (
              <ReportLine
                key={t.report_id}
                name={known?.name ?? t.name ?? t.report_id}
                hint={plural(t.runs, "run") + " in 30 days"}
                share={t.runs / Math.max(1, mine.top_reports[0].runs)}
                onRun={known ? () => run(t.report_id) : undefined}
              />
            );
          })}
        </>
      ),
    },
    recent: {
      title: "Recent runs",
      icon: <Play size={16} aria-hidden="true" />,
      body: (
        <>
          {!mine && !failed && <LinesSkeleton count={4} />}
          {mine && mine.recent.length === 0 && <p className="muted">You haven't run a report yet. Pick one from Reports to get started.</p>}
          {mine && mine.recent.length > 0 && (
            <div className="stack">
              {mine.recent.map((r, i) => {
                const known = runnable.get(r.report_id);
                return (
                  <div key={i} className="spread home-run-row" style={{ gap: 12 }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 500 }}>{known?.name ?? r.name ?? r.report_id}</div>
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        {ago(r.at)}
                        {r.parameters_selected != null && ` · ${plural(r.parameters_selected, "filter")} chosen`}
                        {r.format && ` · ${r.format.toUpperCase()}`}
                        {!r.ok && <span style={{ color: "var(--danger)" }}> · didn't finish{r.reason ? ` (${r.reason})` : ""}</span>}
                      </div>
                    </div>
                    {known && (
                      <button type="button" className="btn" onClick={() => run(r.report_id)} aria-label={`Run ${known.name} again`}>
                        <Play size={14} aria-hidden="true" /> Run again
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      ),
    },
  };

  return (
    <div className="home">
      <div className="home-hero">
        <div>
          <p className="home-eyebrow">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}</p>
          <h1 className="page-title">
            {greeting()}, {auth.username}
          </h1>
          <p className="page-subtitle">{mine?.last_run_at ? `You last ran a report ${ago(mine.last_run_at)}.` : "Your recent activity and shortcuts."}</p>
        </div>
        <div className="home-hero-actions">
          {customised && (
            <button type="button" className="btn" onClick={reset} data-tip="Back to the default arrangement">
              <RotateCcw size={14} aria-hidden="true" /> Reset layout
            </button>
          )}
          <span className="home-hint">
            <GripVertical size={14} aria-hidden="true" /> Drag cards to arrange
          </span>
        </div>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={collide}
        measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={onDragCancel}
      >
        <SortableContext items={shown} strategy={() => null}>
          <div className="home-grid" ref={grid}>
            {shown.map((id) => (
              <HomeCard key={id} id={id} span={SPAN[id as CardId]} title={cards[id as CardId].title} icon={cards[id as CardId].icon} placeholder={id === activeId}>
                {cards[id as CardId].body}
              </HomeCard>
            ))}
          </div>
        </SortableContext>
        <DragOverlay
          dropAnimation={{
            duration: 240,
            easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
            sideEffects: defaultDropAnimationSideEffects({ styles: { active: { opacity: "0" } } }),
          }}
        >
          {activeId ? (
            <HomeCardView title={cards[activeId as CardId].title} icon={cards[activeId as CardId].icon} className={`${SPAN[activeId as CardId]} overlay`}>
              {cards[activeId as CardId].body}
            </HomeCardView>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}

/** One draggable card. Only the grip starts a drag, so text inside stays selectable and buttons stay clickable.
 * While it's being dragged the card in the grid is a faint placeholder; the DragOverlay shows the one that
 * follows the pointer. */
function HomeCard({ id, span, title, icon, placeholder, children }: { id: string; span: string; title: string; icon: ReactNode; placeholder: boolean; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef } = useSortable({ id, animateLayoutChanges: () => false });
  return (
    <HomeCardView
      ref={setNodeRef}
      cardId={id}
      title={title}
      icon={icon}
      className={`${span}${placeholder ? " placeholder" : ""}`}
      grip={
        <button type="button" ref={setActivatorNodeRef} className="home-grip" aria-label={`Move ${title}`} {...attributes} {...listeners}>
          <GripVertical size={16} aria-hidden="true" />
        </button>
      }
    >
      {children}
    </HomeCardView>
  );
}

function HomeCardView({
  ref,
  cardId,
  title,
  icon,
  className,
  grip,
  children,
}: {
  ref?: React.Ref<HTMLElement>;
  cardId?: string;
  title: string;
  icon: ReactNode;
  className: string;
  grip?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section ref={ref} data-card-id={cardId} className={`home-card ${className}`} aria-label={title}>
      <header className="home-card-head">
        <span className="home-card-icon">{icon}</span>
        <h2 className="home-card-title">{title}</h2>
        {grip ?? (
          <span className="home-grip" aria-hidden="true">
            <GripVertical size={16} />
          </span>
        )}
      </header>
      <div className="home-card-body">{children}</div>
    </section>
  );
}

/** A big number with an optional tiny bar trend behind it. */
function Kpi({ value, label, series, tone }: { value: number | string; label: string; series?: number[]; tone?: "danger" }) {
  const max = Math.max(1, ...(series ?? []));
  return (
    <div className={`home-kpi${tone ? ` ${tone}` : ""}`}>
      <div className="home-kpi-top">
        <span className="mono stat-number">{value}</span>
        {tone === "danger" && <AlertTriangle size={16} aria-hidden="true" />}
      </div>
      <div className="muted">{label}</div>
      {series && (
        <div className="home-spark" aria-hidden="true">
          {series.map((n, i) => (
            <span key={i} style={{ height: `${Math.max(n ? 12 : 4, (n / max) * 100)}%` }} className={n ? "on" : ""} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Runs per day as stacked bars (successful, with failures on top). Plain divs rather than an SVG, so it
 * stretches to any card width without distorting; each bar carries its day and counts as a tooltip. */
function RunsChart({ days }: { days: MyDashboard["daily"] }) {
  const max = Math.max(1, ...days.map((d) => d.runs + d.failed));
  const total = days.reduce((n, d) => n + d.runs + d.failed, 0);
  const label = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { day: "numeric", month: "short", timeZone: "UTC" });
  if (total === 0) return <p className="muted">No runs in the last 30 days. They'll be charted here.</p>;
  return (
    <div>
      <div className="home-chart" role="img" aria-label={`${total} runs over the last 30 days, busiest day ${max}`}>
        {days.map((d) => (
          <div key={d.date} className="home-bar" title={`${label(d.date)}: ${plural(d.runs, "run")}${d.failed ? `, ${d.failed} failed` : ""}`}>
            <span className="ok" style={{ height: `${(d.runs / max) * 100}%` }} />
            <span className="fail" style={{ height: `${(d.failed / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <div className="home-chart-axis">
        <span>{label(days[0].date)}</span>
        <span>{label(days[14].date)}</span>
        <span>{label(days[days.length - 1].date)}</span>
      </div>
    </div>
  );
}

function Shortcut({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button type="button" className="btn home-shortcut" onClick={onClick}>
      {icon} {label}
    </button>
  );
}

function ReportLine({ name, hint, share, onRun, onUnstar }: { name: string; hint?: string | null; share?: number; onRun?: () => void; onUnstar?: () => void }) {
  return (
    <div className="spread home-line" style={{ gap: 12 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</div>
        {hint && (
          <div className="muted" style={{ fontSize: "0.8rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {hint}
          </div>
        )}
        {share != null && (
          <div className="home-share" aria-hidden="true">
            <span style={{ width: `${Math.max(4, share * 100)}%` }} />
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 6, flex: "none" }}>
        {onUnstar && (
          <button type="button" className="star-btn starred" onClick={onUnstar} aria-label={`Remove ${name} from starred`} data-tip="Unstar">
            <Star size={16} fill="currentColor" aria-hidden="true" />
          </button>
        )}
        {onRun && (
          <button type="button" className="btn" onClick={onRun}>
            <Play size={14} aria-hidden="true" /> Run
          </button>
        )}
      </div>
    </div>
  );
}
