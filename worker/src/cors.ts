import { Env } from "./http";

const allowedOrigins = (env: Env) =>
  env.ALLOWED_ORIGINS.split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);

/** Same behaviour as flask_cors with an origin allow-list: only listed sites get the headers. */
export function corsHeaders(request: Request, env: Env): Record<string, string> {
  const origin = request.headers.get("Origin");
  if (!origin || !allowedOrigins(env).includes(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers":
      request.headers.get("Access-Control-Request-Headers") ?? "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

export function withCors(response: Response, request: Request, env: Env): Response {
  const headers = corsHeaders(request, env);
  const wrapped = new Response(response.body, response);
  Object.entries(headers).forEach(([key, value]) => wrapped.headers.set(key, value));
  return wrapped;
}
