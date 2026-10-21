export interface Env {
  DB: D1Database;
  DATA: Fetcher;
  ALLOWED_ORIGINS: string;
}

export const json = (body: unknown, status = 200, headers: HeadersInit = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

/** Reads a JSON request body, answering 400 instead of throwing when it is malformed. */
export async function readJson<T>(request: Request): Promise<T | null> {
  try {
    return (await request.json()) as T;
  } catch {
    return null;
  }
}
