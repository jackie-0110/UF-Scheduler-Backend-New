export interface Env {
  DB: D1Database;
  DATA: Fetcher;
  ALLOWED_ORIGINS: string;
}

export default {
  async fetch(): Promise<Response> {
    return new Response("UF Scheduler API", { status: 200 });
  },
} satisfies ExportedHandler<Env>;
