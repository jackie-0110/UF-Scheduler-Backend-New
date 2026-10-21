import { Env, json } from "./http";
import { termKey } from "./terms";

/** GET /api/prereqs?year=27&term=spring: the prebuilt file for that term, streamed through. */
export async function handlePrereqs(url: URL, env: Env): Promise<Response> {
  const key = termKey(url.searchParams.get("year"), url.searchParams.get("term"));
  const asset = key ? await env.DATA.fetch(`https://assets.local/prereqs/${key}.json`) : null;
  if (!asset || !asset.ok) return json({ error: "unknown term" }, 404);
  return new Response(asset.body, {
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
