import { Env, json, readJson } from "./http";

// Google sign-in: the site gets an ID token from Google's button, we check its
// signature against Google's public keys and hand back our own session.

export type User = { id: string; email: string; name: string; picture: string; feed_token: string };

const SESSION_DAYS = 180;
const ISSUERS = ["accounts.google.com", "https://accounts.google.com"];
const CERTS = "https://www.googleapis.com/oauth2/v3/certs";

const b64url = (text: string) => Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
const b64urlJson = (text: string) => JSON.parse(new TextDecoder().decode(b64url(text)));

export const randomToken = (bytes = 24) =>
  Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(36).padStart(2, "0"))
    .join("")
    .slice(0, bytes * 2)
    .toLowerCase();

export const sha256 = async (value: string) => {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
};

type Jwk = JsonWebKey & { kid: string };
let certCache: { keys: Jwk[]; until: number } | null = null;
const googleKeys = async (): Promise<Jwk[]> => {
  if (certCache && certCache.until > Date.now()) return certCache.keys;
  const response = await fetch(CERTS);
  if (!response.ok) throw new Error(`google certs ${response.status}`);
  const { keys } = (await response.json()) as { keys: Jwk[] };
  const maxAge = Number(response.headers.get("Cache-Control")?.match(/max-age=(\d+)/)?.[1] ?? 3600);
  certCache = { keys, until: Date.now() + maxAge * 1000 };
  return keys;
};

export type GoogleClaims = { sub: string; email: string; email_verified?: boolean; name?: string; picture?: string };

/** Returns the token's claims if Google signed it for our client and it hasn't expired. */
export async function verifyGoogleToken(
  credential: string,
  clientId: string,
  keys: () => Promise<Jwk[]> = googleKeys,
  now = Date.now()
): Promise<GoogleClaims | null> {
  const parts = credential.split(".");
  if (parts.length !== 3) return null;
  try {
    const header = b64urlJson(parts[0]);
    const claims = b64urlJson(parts[1]);
    if (header.alg !== "RS256") return null;
    const jwk = (await keys()).find((k) => k.kid === header.kid);
    if (!jwk) return null;
    const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    const ok = await crypto.subtle.verify(
      "RSASSA-PKCS1-v1_5",
      key,
      b64url(parts[2]),
      new TextEncoder().encode(`${parts[0]}.${parts[1]}`)
    );
    if (!ok) return null;
    if (!ISSUERS.includes(claims.iss) || claims.aud !== clientId) return null;
    // a minute of slack for clock drift
    if (typeof claims.exp !== "number" || claims.exp * 1000 < now - 60_000) return null;
    if (typeof claims.sub !== "string" || typeof claims.email !== "string" || claims.email_verified === false) return null;
    return claims as GoogleClaims;
  } catch {
    return null;
  }
}

let schemaReady = false;
export const ensureSchema = async (env: Env) => {
  if (schemaReady) return;
  await env.DB.batch([
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        picture TEXT NOT NULL DEFAULT '',
        feed_token TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL
      )`
    ),
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        expires_at INTEGER NOT NULL
      )`
    ),
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS calendar_feeds (
        user_id TEXT NOT NULL,
        term TEXT NOT NULL,
        events TEXT NOT NULL,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, term)
      )`
    ),
  ]);
  schemaReady = true;
};

const publicUser = (u: User) => ({ email: u.email, name: u.name, picture: u.picture, feed: u.feed_token });

/** The signed-in user for a request's Bearer session, or null. */
export async function currentUser(request: Request, env: Env): Promise<User | null> {
  const token = request.headers.get("Authorization")?.match(/^Bearer ([a-z0-9]{20,80})$/)?.[1];
  if (!token) return null;
  await ensureSchema(env);
  return env.DB.prepare(
    `SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?`
  )
    .bind(await sha256(token), Date.now())
    .first<User>();
}

/** POST /api/auth/google {credential}: signs in, making the account the first time. */
export async function handleGoogleSignIn(request: Request, env: Env): Promise<Response> {
  if (!env.GOOGLE_CLIENT_ID) return json({ error: "sign-in not configured" }, 503);
  const body = await readJson<{ credential?: unknown }>(request);
  if (typeof body?.credential !== "string" || body.credential.length > 4096) return json({ error: "bad credential" }, 400);
  const claims = await verifyGoogleToken(body.credential, env.GOOGLE_CLIENT_ID);
  if (!claims) return json({ error: "invalid credential" }, 401);

  await ensureSchema(env);
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO users (id, email, name, picture, feed_token, created_at) VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT (id) DO UPDATE SET email = excluded.email, name = excluded.name, picture = excluded.picture`
  )
    .bind(claims.sub, claims.email, claims.name ?? "", claims.picture ?? "", randomToken(16), now)
    .run();
  const user = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(claims.sub).first<User>();
  if (!user) return json({ error: "internal error" }, 500);

  const session = randomToken(24);
  await env.DB.batch([
    env.DB.prepare("DELETE FROM sessions WHERE user_id = ? AND expires_at < ?").bind(user.id, now),
    env.DB.prepare("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)").bind(
      await sha256(session),
      user.id,
      now + SESSION_DAYS * 86_400_000
    ),
  ]);
  return json({ session, user: publicUser(user) });
}

/** GET /api/me */
export async function handleMe(request: Request, env: Env): Promise<Response> {
  const user = await currentUser(request, env);
  return user ? json({ user: publicUser(user) }) : json({ error: "signed out" }, 401);
}

/** POST /api/auth/logout */
export async function handleSignOut(request: Request, env: Env): Promise<Response> {
  const token = request.headers.get("Authorization")?.match(/^Bearer ([a-z0-9]{20,80})$/)?.[1];
  if (token) {
    await ensureSchema(env);
    await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(await sha256(token)).run();
  }
  return json({ ok: true });
}
