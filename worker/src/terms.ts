import { Env } from "./http";

const YEAR = /^\d{2}$/;
const TERM = /^[a-z]+$/;

/** A term key like "27_spring", or null when year/term aren't shaped like one. */
export function termKey(year: unknown, term: unknown): string | null {
  if (typeof year !== "string" || typeof term !== "string") return null;
  return YEAR.test(year) && TERM.test(term) ? `${year}_${term}` : null;
}

let knownTables: Set<string> | null = null;

/** Terms that have been seeded into D1 (one courses_{year}_{term} table each). */
export async function isSeededTerm(env: Env, key: string): Promise<boolean> {
  if (!knownTables) {
    const { results } = await env.DB.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'courses\\_%' ESCAPE '\\'"
    ).all<{ name: string }>();
    knownTables = new Set(results.map((row) => row.name));
  }
  return knownTables.has(`courses_${key}`);
}
