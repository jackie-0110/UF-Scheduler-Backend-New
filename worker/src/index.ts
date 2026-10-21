import { corsHeaders, withCors } from "./cors";
import { Env, json } from "./http";
import { handlePrereqs } from "./prereqs";
import { handleSearch } from "./search";

export type { Env };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }

    const url = new URL(request.url);
    let response: Response;
    try {
      if (request.method === "GET" && url.pathname === "/api/prereqs") {
        response = await handlePrereqs(url, env);
      } else if (request.method === "POST" && url.pathname === "/api/get_courses") {
        response = await handleSearch(request, env);
      } else {
        response = json({ error: "not found" }, 404);
      }
    } catch (error) {
      console.error(error);
      response = json({ error: "internal error" }, 500);
    }
    return withCors(response, request, env);
  },
} satisfies ExportedHandler<Env>;
