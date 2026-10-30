import { corsHeaders, withCors } from "./cors";
import { Env, json } from "./http";
import { handleGraph } from "./graph";
import { handlePrereqs } from "./prereqs";
import { handleSearch } from "./search";
import { handleCalendarFeed, handleResetFeed, handleSaveCalendar } from "./calendar";
import { handleGoogleSignIn, handleMe, handleSignOut } from "./auth";
import { handleGetData, handlePutData } from "./data";

export type { Env };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }

    const url = new URL(request.url);
    // calendar apps fetch this directly, so no CORS wrapping needed
    const feed = url.pathname.match(/^\/cal\/([a-z0-9]+)\.ics$/);
    if (feed && (request.method === "GET" || request.method === "HEAD")) {
      try {
        return await handleCalendarFeed(feed[1], env);
      } catch (error) {
        console.error(error);
        return new Response("error", { status: 500 });
      }
    }

    let response: Response;
    try {
      if (request.method === "GET" && url.pathname === "/api/prereqs") {
        response = await handlePrereqs(url, env);
      } else if (request.method === "POST" && url.pathname === "/api/get_courses") {
        response = await handleSearch(request, env);
      } else if (request.method === "POST" && url.pathname === "/api/auth/google") {
        response = await handleGoogleSignIn(request, env);
      } else if (request.method === "POST" && url.pathname === "/api/auth/logout") {
        response = await handleSignOut(request, env);
      } else if (request.method === "GET" && url.pathname === "/api/me") {
        response = await handleMe(request, env);
      } else if (request.method === "GET" && url.pathname === "/api/data") {
        response = await handleGetData(request, url, env);
      } else if (request.method === "POST" && url.pathname === "/api/data") {
        response = await handlePutData(request, env);
      } else if (request.method === "POST" && url.pathname === "/api/calendar") {
        response = await handleSaveCalendar(request, env);
      } else if (request.method === "POST" && url.pathname === "/api/calendar/reset") {
        response = await handleResetFeed(request, env);
      } else if (request.method === "POST" && url.pathname === "/generate_a_list") {
        response = await handleGraph(request, env);
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
