import { X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { isManageRoute } from "../admin/sections";
import type { Route } from "../hooks";
import { useUserSettings } from "../userSettings";

/** One stop of a tour: the element it points at (a `data-tour` name; none = a centred note), and what to say. */
export interface TourStep {
  target?: string;
  title: string;
  body: string;
}

export type TourId = "home" | "manage";

/** The first-visit tours. A step whose element isn't on the page for this person (no Manage button, no Templates
 * in their sidebar, the phone layout...) is simply left out, so each person gets the tour of what they can use. */
const TOURS: Record<TourId, TourStep[]> = {
  home: [
    {
      title: "Welcome to Aksor Khmer",
      body: "A quick look around, one stop at a time. Skip it whenever you like — Show me around in your account menu brings it back.",
    },
    { target: "nav-reports", title: "Reports", body: "Every report you've been given. Open one, pick its filters, and view or download it as PDF, Word or Excel." },
    { target: "nav-my-runs", title: "My runs", body: "Everything you've run, newest first — run any of them again with one click." },
    { target: "nav-starred", title: "Starred", body: "Star the reports you use most. They're kept here and on your Home page." },
    { target: "home-cards", title: "Your Home page", body: "Below: your own activity, shortcuts and recent runs. Drag the cards by their handle to arrange them the way you like." },
    { target: "notifications", title: "Notifications", body: "You'll be asked here if your account signs in on a browser it hasn't used before — so you can sign it out if it wasn't you." },
    {
      target: "docs",
      title: "Guides",
      body: "How-tos for everything here — running and sharing reports, filters, Khmer text — searchable, and always one click away.",
    },
    { target: "manage", title: "Manage", body: "Templates, schedules, data sources and people — only what your role lets you manage. Opening it gives you its own tour." },
    { target: "account", title: "Your account", body: "Your profile, password, two-step verification, sessions and preferences — and this tour again, under Show me around." },
  ],
  manage: [
    {
      target: "manage-sidebar",
      title: "This is Manage",
      body: "Everything you can manage, grouped by job: authoring, scheduling, data sources, people, operations. You only see the pages your role allows.",
    },
    { target: "manage-templates", title: "Templates", body: "Where reports are made. New report starts from your data: run it, get the fields, design the look, preview, publish." },
    { target: "manage-connections", title: "Data sources", body: "Connections to your REST APIs and databases, set up once and shared by every report that uses them." },
    { target: "manage-users", title: "People & access", body: "Accounts, roles and who can open which reports." },
    {
      target: "docs",
      title: "Building reports",
      body: "The guides cover the template syntax — placeholders, table-row loops, number and date formats, charts, images, Khmer text — with copy-ready examples.",
    },
    { target: "manage-back", title: "Back to your work", body: "Returns to the page you opened Manage from." },
  ],
};

const TOUR_VERSION = 1;
const settingCode = (tour: TourId) => `tour.${tour}`;
const START_EVENT = "aksor:start-tour";

/** Start a tour now -- the account menu's "Show me around". Without an id, the one for the page you're on. */
export function startTour(tour?: TourId) {
  window.dispatchEvent(new CustomEvent<TourId | undefined>(START_EVENT, { detail: tour }));
}

function visible(el: Element | null): el is HTMLElement {
  if (!el || !(el instanceof HTMLElement)) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
}

const find = (name: string) => document.querySelector(`[data-tour="${name}"]`);

/** Decides when a tour runs: once per person per area (Home on first sign-in, Manage the first time it's opened),
 * remembered on their account -- and in this browser too, for the built-in admin, which has no account row. A
 * finished or skipped tour stays done; "Show me around" replays it. */
export function TourHost({ route }: { route: Route }) {
  const settings = useUserSettings();
  const [active, setActive] = useState<TourId | null>(null);
  const area: TourId | null = route.view === "home" ? "home" : isManageRoute(route) ? "manage" : null;

  const seen = useCallback(
    (tour: TourId) => {
      if (settings.get(settingCode(tour)) !== undefined) return true;
      try {
        return localStorage.getItem(`aksor_${settingCode(tour)}`) !== null;
      } catch {
        return false;
      }
    },
    [settings],
  );

  useEffect(() => {
    if (!settings.loaded || active || !area || seen(area)) return;
    // Let the page draw first: the tour points at things on it.
    const timer = window.setTimeout(() => setActive(area), 700);
    return () => window.clearTimeout(timer);
  }, [settings.loaded, area, active, seen]);

  useEffect(() => {
    const onStart = (e: Event) => setActive((e as CustomEvent<TourId | undefined>).detail ?? area ?? "home");
    window.addEventListener(START_EVENT, onStart);
    return () => window.removeEventListener(START_EVENT, onStart);
  }, [area]);

  function finish(how: "done" | "skipped") {
    if (!active) return;
    const value = { how, version: TOUR_VERSION, at: new Date().toISOString() };
    settings.set(settingCode(active), value).catch(() => {});
    try {
      localStorage.setItem(`aksor_${settingCode(active)}`, how);
    } catch {
      // Private window: the account copy is enough.
    }
    setActive(null);
  }

  if (!active) return null;
  return <GuidedTour key={active} steps={TOURS[active]} onFinish={finish} />;
}

const GAP = 12;
const PAD = 6;

/** The tour itself: the page dimmed except for the element being explained, and a small card beside it with Back /
 * Next and Skip. Esc skips, the arrow keys move. Steps whose element isn't there are left out. */
function GuidedTour({ steps: all, onFinish }: { steps: TourStep[]; onFinish: (how: "done" | "skipped") => void }) {
  const steps = useMemo(() => all.filter((s) => !s.target || visible(find(s.target))), [all]);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [card, setCard] = useState<{ width: number; height: number }>({ width: 340, height: 180 });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[index];
  const last = index === steps.length - 1;

  const measure = useCallback(() => {
    const el = step?.target ? find(step.target) : null;
    setRect(visible(el) ? el.getBoundingClientRect() : null);
  }, [step]);

  useLayoutEffect(() => {
    const el = step?.target ? find(step.target) : null;
    if (visible(el)) el.scrollIntoView({ block: "nearest", inline: "nearest" });
    measure();
    nextRef.current?.focus();
  }, [step, measure]);

  useLayoutEffect(() => {
    if (cardRef.current) setCard({ width: cardRef.current.offsetWidth, height: cardRef.current.offsetHeight });
  }, [index, rect]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onFinish("skipped");
      else if (e.key === "ArrowRight") setIndex((i) => Math.min(i + 1, steps.length - 1));
      else if (e.key === "ArrowLeft") setIndex((i) => Math.max(i - 1, 0));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onFinish, steps.length]);

  if (!step) return null;

  // Below the element if it fits, else above, else centred; kept inside the window either way.
  let position: React.CSSProperties;
  if (rect) {
    const below = rect.bottom + PAD + GAP;
    const above = rect.top - PAD - GAP - card.height;
    const top = below + card.height <= window.innerHeight - GAP ? below : above >= GAP ? above : Math.max(GAP, (window.innerHeight - card.height) / 2);
    const left = Math.min(Math.max(GAP, rect.left + rect.width / 2 - card.width / 2), window.innerWidth - card.width - GAP);
    position = { top, left };
  } else {
    position = { top: Math.max(GAP, (window.innerHeight - card.height) / 2), left: Math.max(GAP, (window.innerWidth - card.width) / 2) };
  }

  return createPortal(
    <div className="tour-layer">
      {rect ? (
        <div
          className="tour-spotlight"
          style={{ top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }}
          aria-hidden="true"
        />
      ) : (
        <div className="tour-dim" aria-hidden="true" />
      )}
      <div ref={cardRef} className="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" style={position}>
        <button type="button" className="tour-close" onClick={() => onFinish("skipped")} aria-label="Skip the tour">
          <X size={16} aria-hidden="true" />
        </button>
        <h2 id="tour-title" className="tour-title">
          {step.title}
        </h2>
        <p id="tour-body" className="tour-body">
          {step.body}
        </p>
        <div className="tour-foot">
          <span className="tour-dots" aria-label={`Step ${index + 1} of ${steps.length}`}>
            {steps.map((s, i) => (
              <span key={s.title} className={`tour-dot${i === index ? " active" : ""}`} />
            ))}
          </span>
          <div className="tour-actions">
            {index === 0 ? (
              <button type="button" className="link-btn tour-skip" onClick={() => onFinish("skipped")}>
                Skip tour
              </button>
            ) : (
              <button type="button" className="btn btn-sm" onClick={() => setIndex(index - 1)}>
                Back
              </button>
            )}
            <button ref={nextRef} type="button" className="btn btn-sm btn-primary" onClick={() => (last ? onFinish("done") : setIndex(index + 1))}>
              {last ? "Done" : index === 0 ? "Show me" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
