import { Env, json, readJson } from "./http";
import { termKey } from "./terms";
import { currentUser, ensureSchema, randomToken } from "./auth";

// One subscribable calendar per account. The site POSTs each term's classes
// and calendar apps poll /cal/{feed token}.ics.

export type FeedEvent = {
  uid: string;
  title: string;
  location: string;
  start: string; // 20260824T093500, Gainesville time
  end: string;
  until: string; // 20261204
  days: string; // MO,WE,FR
};

type SaveBody = { year?: unknown; term?: unknown; events?: unknown };

const TOKEN = /^[a-z0-9]{24,48}$/;
const STAMP = /^\d{8}T\d{6}$/;
const DATE = /^\d{8}$/;
const DAYS = /^(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*$/;
const MAX_EVENTS = 80;

const text = (v: unknown, max: number) => (typeof v === "string" ? v.slice(0, max) : "");

const cleanEvent = (raw: unknown): FeedEvent | null => {
  if (!raw || typeof raw !== "object") return null;
  const e = raw as Record<string, unknown>;
  const event = {
    uid: text(e.uid, 120),
    title: text(e.title, 200),
    location: text(e.location, 200),
    start: text(e.start, 15),
    end: text(e.end, 15),
    until: text(e.until, 8),
    days: text(e.days, 20),
  };
  if (!event.uid || !event.title) return null;
  if (!STAMP.test(event.start) || !STAMP.test(event.end) || !DATE.test(event.until) || !DAYS.test(event.days)) return null;
  return event;
};

/** POST /api/calendar {year, term, events}: replaces that term's classes in the signed-in user's feed. */
export async function handleSaveCalendar(request: Request, env: Env): Promise<Response> {
  if (Number(request.headers.get("Content-Length") ?? 0) > 64_000) return json({ error: "too big" }, 413);
  const user = await currentUser(request, env);
  if (!user) return json({ error: "signed out" }, 401);
  const body = await readJson<SaveBody>(request);
  if (!body) return json({ error: "bad json" }, 400);
  const term = termKey(body.year, body.term);
  if (!term || !Array.isArray(body.events) || body.events.length > MAX_EVENTS) return json({ error: "bad events" }, 400);

  const events = body.events.map(cleanEvent).filter((e): e is FeedEvent => e !== null);
  await env.DB.prepare(
    `INSERT INTO calendar_feeds (user_id, term, events, updated_at) VALUES (?, ?, ?, ?)
     ON CONFLICT (user_id, term) DO UPDATE SET events = excluded.events, updated_at = excluded.updated_at`
  )
    .bind(user.id, term, JSON.stringify(events), Date.now())
    .run();
  return json({ ok: true, saved: events.length, feed: user.feed_token });
}

/** POST /api/calendar/reset: a new feed link, for when the old one got shared around. */
export async function handleResetFeed(request: Request, env: Env): Promise<Response> {
  const user = await currentUser(request, env);
  if (!user) return json({ error: "signed out" }, 401);
  const feed = randomToken(16);
  await env.DB.prepare("UPDATE users SET feed_token = ? WHERE id = ?").bind(feed, user.id).run();
  return json({ feed });
}

// Calendar text needs commas, semicolons and newlines escaped, and lines kept under 75 bytes
const escape = (value: string) => value.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

const fold = (line: string) => {
  const bytes = new TextEncoder();
  if (bytes.encode(line).length <= 75) return line;
  const parts: string[] = [];
  let current = "";
  for (const ch of line) {
    if (bytes.encode(current + ch).length > (parts.length ? 74 : 75)) {
      parts.push(current);
      current = "";
    }
    current += ch;
  }
  parts.push(current);
  return parts.join("\r\n ");
};

const TIMEZONE = [
  "BEGIN:VTIMEZONE",
  "TZID:America/New_York",
  "BEGIN:DAYLIGHT",
  "TZOFFSETFROM:-0500",
  "TZOFFSETTO:-0400",
  "TZNAME:EDT",
  "DTSTART:19700308T020000",
  "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
  "END:DAYLIGHT",
  "BEGIN:STANDARD",
  "TZOFFSETFROM:-0400",
  "TZOFFSETTO:-0500",
  "TZNAME:EST",
  "DTSTART:19701101T020000",
  "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU",
  "END:STANDARD",
  "END:VTIMEZONE",
];

const utcStamp = (ms: number) => new Date(ms).toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");

// UNTIL has to be UTC; the end of the last day in Gainesville is ~5am UTC the next day
const untilStamp = (day: string) => {
  const next = Date.UTC(+day.slice(0, 4), +day.slice(4, 6) - 1, +day.slice(6, 8) + 1, 4, 59, 59);
  return utcStamp(next);
};

export const renderCalendar = (rows: { events: FeedEvent[]; updated: number }[]) => {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//UF Scheduler//Class feed//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:UF Classes",
    "X-WR-TIMEZONE:America/New_York",
    "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    "X-PUBLISHED-TTL:PT6H",
    ...TIMEZONE,
  ];
  for (const { events, updated } of rows) {
    for (const e of events) {
      lines.push(
        "BEGIN:VEVENT",
        `UID:${escape(e.uid)}@ufscheduler`,
        `DTSTAMP:${utcStamp(updated)}`,
        `DTSTART;TZID=America/New_York:${e.start}`,
        `DTEND;TZID=America/New_York:${e.end}`,
        `RRULE:FREQ=WEEKLY;BYDAY=${e.days};UNTIL=${untilStamp(e.until)}`,
        `SUMMARY:${escape(e.title)}`,
        ...(e.location.trim() ? [`LOCATION:${escape(e.location.trim())}`] : []),
        "END:VEVENT"
      );
    }
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
};

/** GET /cal/{token}.ics: every term the student has synced, as one feed. */
export async function handleCalendarFeed(token: string, env: Env): Promise<Response> {
  if (!TOKEN.test(token)) return new Response("not found", { status: 404 });
  await ensureSchema(env);
  const { results } = await env.DB.prepare(
    `SELECT f.events, f.updated_at FROM users u JOIN calendar_feeds f ON f.user_id = u.id
     WHERE u.feed_token = ? ORDER BY f.term`
  )
    .bind(token)
    .all<{ events: string; updated_at: number }>();
  const user = results.length ? null : await env.DB.prepare("SELECT 1 FROM users WHERE feed_token = ?").bind(token).first();
  // a real feed with nothing saved yet is an empty calendar, not a 404
  if (!results.length && !user) return new Response("not found", { status: 404 });
  const rows = results.map((r) => ({ events: JSON.parse(r.events) as FeedEvent[], updated: r.updated_at }));
  return new Response(renderCalendar(rows), {
    headers: {
      "Content-Type": "text/calendar; charset=utf-8",
      "Content-Disposition": 'inline; filename="uf-classes.ics"',
      "Cache-Control": "public, max-age=300",
    },
  });
}
