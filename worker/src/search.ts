import { Env, json, readJson } from "./http";
import { isSeededTerm, termKey } from "./terms";

interface SearchBody {
  searchTerm?: string;
  itemsPerPage?: number;
  startFrom?: number;
  year?: string;
  term?: string;
}

const MAX_PAGE_SIZE = 500;

const toCount = (value: unknown, fallback: number, max: number) => {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Math.min(Math.floor(number), max) : fallback;
};

/**
 * Turns the typed search into an FTS5 query: alphanumeric tokens only, each quoted and
 * prefix-matched, so punctuation ("C++", "COP-3502") and FTS keywords (AND, OR, NOT) can't
 * break the query.
 */
export function buildFtsQuery(searchTerm: string): { query: string; exactCode: string } | null {
  const tokens = searchTerm.match(/[A-Za-z0-9]+/g);
  if (!tokens) return null;
  return {
    query: tokens.map((token) => `"${token}"*`).join(" "),
    exactCode: tokens.join("").toUpperCase(),
  };
}

/** POST /api/get_courses: full-text course search for one term. */
export async function handleSearch(request: Request, env: Env): Promise<Response> {
  const body = await readJson<SearchBody>(request);
  if (!body || !body.year || !body.term) {
    return json({ error: "Missing 'year' or 'term' in request body" }, 400);
  }

  const key = termKey(body.year, body.term);
  const fts = buildFtsQuery((body.searchTerm ?? "").trim());
  // terms without scraped data, and empty searches, have no results
  if (!key || !fts || !(await isSeededTerm(env, key))) return json([]);

  const table = `courses_${key}`;
  const { results } = await env.DB.prepare(
    `SELECT json_data,
            CASE WHEN upper(code) = ?1 THEN 0 ELSE 1 END AS top_sort,
            bm25(${table}, 10.0, 10.0, 6.0, 1.0, 2.0) AS rank
       FROM ${table}
      WHERE ${table} MATCH ?2
      ORDER BY top_sort, rank
      LIMIT ?3 OFFSET ?4`
  )
    .bind(
      fts.exactCode,
      fts.query,
      toCount(body.itemsPerPage, 20, MAX_PAGE_SIZE),
      toCount(body.startFrom, 0, Number.MAX_SAFE_INTEGER)
    )
    .all<{ json_data: string }>();

  // json_data is already serialized course JSON: join it instead of parsing and re-encoding
  return new Response(`[${results.map((row) => row.json_data).join(",")}]`, {
    headers: { "Content-Type": "application/json" },
  });
}
