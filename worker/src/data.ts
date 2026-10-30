import { Env, json, readJson } from "./http";
import { currentUser, ensureSchema } from "./auth";

// Saved app state (planner, schedules, friends...) as opaque key/value pairs.
// The server stamps each write so devices can ask for "what changed since".

const KEY = /^[A-Za-z0-9_:. -]{1,80}$/;
const MAX_VALUE = 1_000_000;
const MAX_KEYS = 400;

let tableReady = false;
const ensureTable = async (env: Env) => {
  await ensureSchema(env);
  if (tableReady) return;
  await env.DB.prepare(
    `CREATE TABLE IF NOT EXISTS user_data (
      user_id TEXT NOT NULL,
      key TEXT NOT NULL,
      value TEXT,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, key)
    )`
  ).run();
  tableReady = true;
};

/** GET /api/data?since=ms: every key written after `since` (deleted ones come back as null). */
export async function handleGetData(request: Request, url: URL, env: Env): Promise<Response> {
  const user = await currentUser(request, env);
  if (!user) return json({ error: "signed out" }, 401);
  await ensureTable(env);
  const since = Number(url.searchParams.get("since")) || 0;
  const now = Date.now();
  const { results } = await env.DB.prepare(
    "SELECT key, value, updated_at FROM user_data WHERE user_id = ? AND updated_at > ? ORDER BY updated_at"
  )
    .bind(user.id, since)
    .all<{ key: string; value: string | null; updated_at: number }>();
  return json({
    now,
    items: results.map((r) => ({ key: r.key, value: r.value, updated: r.updated_at })),
  });
}

type PutBody = { items?: unknown };

/** POST /api/data {items: [{key, value}]}: value null deletes. */
export async function handlePutData(request: Request, env: Env): Promise<Response> {
  if (Number(request.headers.get("Content-Length") ?? 0) > 4_000_000) return json({ error: "too big" }, 413);
  const user = await currentUser(request, env);
  if (!user) return json({ error: "signed out" }, 401);
  const body = await readJson<PutBody>(request);
  if (!body || !Array.isArray(body.items) || body.items.length > 100) return json({ error: "bad items" }, 400);

  const items: { key: string; value: string | null }[] = [];
  for (const raw of body.items) {
    const item = raw as { key?: unknown; value?: unknown };
    if (typeof item?.key !== "string" || !KEY.test(item.key)) return json({ error: "bad key" }, 400);
    if (item.value !== null && typeof item.value !== "string") return json({ error: "bad value" }, 400);
    if (typeof item.value === "string" && item.value.length > MAX_VALUE) return json({ error: `${item.key} too big` }, 413);
    items.push({ key: item.key, value: item.value });
  }

  await ensureTable(env);
  const count = await env.DB.prepare("SELECT COUNT(*) AS n FROM user_data WHERE user_id = ?")
    .bind(user.id)
    .first<{ n: number }>();
  if ((count?.n ?? 0) + items.length > MAX_KEYS) return json({ error: "too many keys" }, 413);

  const now = Date.now();
  if (items.length) {
    await env.DB.batch(
      items.map(({ key, value }) =>
        env.DB.prepare(
          `INSERT INTO user_data (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`
        ).bind(user.id, key, value, now)
      )
    );
  }
  return json({ ok: true, now });
}
