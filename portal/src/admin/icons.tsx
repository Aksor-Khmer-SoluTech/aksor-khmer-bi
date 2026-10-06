/** Icon set for the admin sidebar/nav/top bar — lucide-react (MIT,
 * tree-shakeable: only the icons actually imported below end up in the
 * bundle) rather than the hand-drawn SVGs this file used to hold. Every
 * icon is re-exported under its original name at a fixed size/stroke
 * weight, so every call site elsewhere (`<UsersIcon />`, `s.icon` in
 * sections.tsx, etc.) is unchanged — this file is the one place that
 * knows which library icon backs which console concept, and the one
 * place to retune weight if the console's overall line weight changes. */
import {
  ArrowUpRight,
  Bell,
  BookOpen,
  Building2,
  CalendarClock,
  Cable,
  ChevronLeft,
  ClipboardList,
  Code2,
  Coffee,
  FileBarChart,
  Folder,
  FolderOpen,
  FolderTree,
  Gauge,
  GripVertical,
  HeartHandshake,
  History,
  Image,
  Info,
  KeyRound,
  KeySquare,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  List,
  Mail,
  Monitor,
  MonitorSmartphone,
  MoreHorizontal,
  Phone,
  Puzzle,
  QrCode,
  RefreshCw,
  ScrollText,
  ServerCog,
  Shield,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  SlidersHorizontal,
  Smartphone,
  SpellCheck,
  Tablet,
  Upload,
  User,
  Users,
  Wrench,
} from "lucide-react";

// Lucide defaults to a 2px stroke at 24px — a touch heavier than this
// console's own line weight (BrandMark.tsx, the wordmark glyph), so both
// are dialed down slightly rather than left at the library default.
const ICON_PROPS = { size: 18, strokeWidth: 1.6 } as const;

export function UsersIcon() {
  return <Users {...ICON_PROPS} />;
}

export function RolesIcon() {
  return <ShieldCheck {...ICON_PROPS} />;
}

/** Admin's API Clients screen -- a server with a cog: machine identities (client id + secret)
 * that run reports without a person signing in. Distinct from AccessIcon's KeyRound, which is
 * the Settings panel about *your own* password. */
export function ClientsIcon() {
  return <ServerCog {...ICON_PROPS} />;
}

/** Admin's Connections screen -- a cable: the named base URLs (with their headers and
 * authentication) that reports fetch their data and choice lists through. Distinct from
 * ClientsIcon's server, which is the machines calling *in*; this is where Aksor calls *out*. */
export function ConnectionsIcon() {
  return <Cable {...ICON_PROPS} />;
}

/** Admin's Access Review screen -- a checklist/audit glyph: distinct from
 * RolesIcon's ShieldCheck ("what a role can do") and ShieldIcon's
 * per-folder manage-access affordance ("who can reach this one folder"):
 * this one means "every grant across the org, in one list to review." */
/** Admin's JDBC drivers screen -- the vendor driver files (.jar) database connections run on. */
export function DriversIcon() {
  return <Coffee {...ICON_PROPS} />;
}

/** Admin's Secrets screen -- a distinct glyph (KeySquare) from AccessIcon's
 * KeyRound (an account's own 2FA/password screen): this is the shared vault
 * of named credentials a connection or a report's data source can refer to. */
export function SecretsIcon() {
  return <KeySquare {...ICON_PROPS} />;
}

export function AccessReviewIcon() {
  return <ClipboardList {...ICON_PROPS} />;
}

/** Admin's Audit Log -- a scroll of entries: the running record of who
 * changed what (api/app/audit.py), as opposed to AccessReviewIcon's "who can
 * do what right now." */
export function AuditIcon() {
  return <ScrollText {...ICON_PROPS} />;
}

/** Admin's Protected Terms screen -- a spell-check glyph: it's about how
 * *words* are treated (kept whole by the Khmer word-breaker), not access,
 * so it deliberately doesn't borrow one of the shield icons above. */
export function ProtectedTermsIcon() {
  return <SpellCheck {...ICON_PROPS} />;
}

export function OrganizationsIcon() {
  return <Building2 {...ICON_PROPS} />;
}

export function ApiIcon() {
  return <Code2 {...ICON_PROPS} />;
}

export function MonitorIcon() {
  return <Gauge {...ICON_PROPS} />;
}

export function DashboardIcon() {
  return <LayoutDashboard {...ICON_PROPS} />;
}

export function LdapIcon() {
  return <List {...ICON_PROPS} />;
}

export function JobsIcon() {
  return <RefreshCw {...ICON_PROPS} />;
}

export function PluginsIcon() {
  return <Puzzle {...ICON_PROPS} />;
}

/** Primary sidebar nav icons — Templates/Reports/Batch/Admin — same set as
 * the admin section icons above, so the sidebar reads as one consistent
 * icon family regardless of which list it's rendering. */
export function TemplatesIcon() {
  return <LayoutGrid {...ICON_PROPS} />;
}

/** The end-user Reports page: a document with a chart on it -- the thing
 * you open and read, as opposed to TemplatesIcon's grid of things you
 * register and integrate. */
export function ReportsIcon() {
  return <FileBarChart {...ICON_PROPS} />;
}

export function BatchIcon() {
  return <Layers {...ICON_PROPS} />;
}

/** Schedules — the non-admin sidebar's today's-jobs summary, distinct
 * from admin Jobs' RefreshCw (that page manages job definitions; this
 * one is a read-only "what's running/ran/still to run today" view). */
export function SchedulesIcon() {
  return <CalendarClock {...ICON_PROPS} />;
}

export function AdminIcon() {
  return <Wrench {...ICON_PROPS} />;
}

/** Resources — the folder tree of report templates + images (see
 * ResourcesPage.tsx). Distinct from TemplatesIcon's flat grid: this one's
 * a tree, signaling "these are organized," not just "here's a list." */
export function ResourcesIcon() {
  return <FolderTree {...ICON_PROPS} />;
}

export function FolderIcon() {
  return <Folder {...ICON_PROPS} />;
}

export function FolderOpenIcon() {
  return <FolderOpen {...ICON_PROPS} />;
}

export function ImageIcon() {
  return <Image {...ICON_PROPS} />;
}

export function UploadIcon() {
  return <Upload {...ICON_PROPS} />;
}

export function MoreIcon() {
  return <MoreHorizontal {...ICON_PROPS} />;
}

export function GripIcon() {
  return <GripVertical {...ICON_PROPS} />;
}

/** Manage-access affordance on a folder row — distinct from AdminIcon's
 * wrench (system administration) and RolesIcon's ShieldCheck (a role's
 * own permission set): this one is specifically "who can reach this
 * folder," attached to one Resources node, not a global concept. */
export function ShieldIcon() {
  return <Shield {...ICON_PROPS} />;
}

/** Sidebar collapse toggle — rotated 180° via the `.collapsed` state in
 * CSS rather than swapped for a mirror-image icon. */
export function ChevronIcon() {
  return <ChevronLeft {...ICON_PROPS} />;
}

/** Personal Preferences (mode/accent) in the top bar — three sliders,
 * deliberately distinct from AdminIcon's wrench so the two aren't
 * confused at a glance: one is "how the system is configured", this is
 * "how it looks to me". */
export function PreferencesIcon() {
  return <SlidersHorizontal {...ICON_PROPS} />;
}

/** About, in the top bar. */
export function InfoIcon() {
  return <Info {...ICON_PROPS} />;
}

/** Notifications bell, in the top bar. */
export function BellIcon() {
  return <Bell {...ICON_PROPS} />;
}

/** Settings modal sidebar — Profile: a plain person, distinct from
 * UsersIcon's group-of-people (that's "manage other accounts"; this is
 * "my own account"). */
export function ProfileIcon() {
  return <User {...ICON_PROPS} />;
}

/** Settings modal sidebar — Access: password + authentication type,
 * distinct from RolesIcon's ShieldCheck (that's "what this role can do";
 * this is "how I prove it's me"). */
export function AccessIcon() {
  return <KeyRound {...ICON_PROPS} />;
}

/** Settings modal sidebar — Active Sessions: the devices/browsers
 * currently signed in, not AdminIcon's wrench or MonitorIcon's system
 * gauge (that's server health, this is "where am I signed in"). */
export function SessionsIcon() {
  return <MonitorSmartphone {...ICON_PROPS} />;
}

/** Settings modal sidebar — Authentication log: a history/timeline mark,
 * distinct from SessionsIcon's device glyph -- this is "what's happened
 * over time," not "what's connected right now." */
export function AuthLogIcon() {
  return <History {...ICON_PROPS} />;
}

/** Active Sessions list — one per app/types.ts DeviceType, so each row
 * reads at a glance instead of everything sharing SessionsIcon. */
export function DeviceDesktopIcon() {
  return <Monitor {...ICON_PROPS} />;
}

export function DeviceMobileIcon() {
  return <Smartphone {...ICON_PROPS} />;
}

export function DeviceTabletIcon() {
  return <Tablet {...ICON_PROPS} />;
}

/** Sign-in activity's success/failure rows. */
export function AuthSuccessIcon() {
  return <ShieldCheck {...ICON_PROPS} />;
}

export function AuthFailureIcon() {
  return <ShieldAlert {...ICON_PROPS} />;
}

/** The dashboard's security feed: an access-denied (authorization)
 * event reads as a distinct glyph from AuthFailureIcon's authentication
 * failure above, even though both are "something was rejected." */
export function AccessDeniedIcon() {
  return <ShieldX {...ICON_PROPS} />;
}

/** Documentation, in the top bar — distinct from InfoIcon's "what/who is
 * this" (About): this one is "how do I use it," an open book rather
 * than a circled i. */
export function DocsIcon() {
  return <BookOpen {...ICON_PROPS} />;
}

/** External-link cue on an outbound doc/repo link. */
export function ExternalLinkIcon() {
  return <ArrowUpRight {...ICON_PROPS} />;
}

/** About dialog's "support this project" section. */
export function SupportIcon() {
  return <HeartHandshake {...ICON_PROPS} />;
}

export function MailIcon() {
  return <Mail {...ICON_PROPS} />;
}

export function PhoneIcon() {
  return <Phone {...ICON_PROPS} />;
}

/** Telegram contact link — the actual brand mark (path from Simple
 * Icons, MIT-licensed, verified against their published data), filled
 * with Telegram's own blue rather than `currentColor` like every other
 * icon here: a brand logo reads as itself only in its own color, not
 * whatever text color it happens to sit in. The path is a single
 * silhouette (solid circle with the paper-plane cut out of it, not two
 * separate shapes) -- it reads correctly on light backgrounds, where the
 * cutout shows through as the surrounding surface. */
export function TelegramIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="#26A5E4" aria-hidden="true">
      <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
    </svg>
  );
}

export function QrCodeIcon() {
  return <QrCode {...ICON_PROPS} />;
}
