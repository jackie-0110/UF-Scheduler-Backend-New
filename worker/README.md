# UF Scheduler API (Cloudflare Worker)

Same endpoints as the Flask app in the repo root, running on Workers + D1 so it never sleeps:

| Endpoint | Source |
| --- | --- |
| `POST /api/get_courses` | FTS5 search in D1 (`courses_{year}_{term}` tables) |
| `GET /api/prereqs?year=&term=` | prebuilt `data/prereqs/{year}_{term}.json` |
| `POST /generate_a_list` | prebuilt `data/graphs/{year}_{term}/*.json` |
| `POST /api/auth/google`, `GET /api/me`, `POST /api/auth/logout` | Google sign-in, sessions in D1 |
| `POST /api/calendar`, `POST /api/calendar/reset` | save a term's classes to the user's feed, or make a new feed link |
| `GET /cal/{token}.ics` | the subscribable calendar feed |
| `GET /api/data?since=`, `POST /api/data` | the signed-in user's saved app state (planner, schedules, friends) |

The prerequisite parser and graph builders stay in Python. A build step exports their output,
so the Worker only serves data.

## Refreshing the data (after a new scrape)

```sh
# from the repo root, with the Flask requirements installed
python scripts/export_worker_data.py   # worker/data  (static prereqs + graphs)
python scripts/export_d1_seed.py       # worker/seed  (SQL for the search tables)
```

## Local development

```sh
cd worker
npm install
npm run seed:local
npm run dev                            # http://localhost:8787
python ../scripts/parity_check.py http://localhost:8787 http://localhost:5055
```

The parity script runs the same searches, graph and prereq requests against the Worker and the
Flask app and compares the JSON.

## Google sign-in and calendar feeds

Each account gets one calendar feed. The site POSTs the pinned schedule per term and calendar
apps poll `/cal/{token}.ics`. The `users`, `sessions` and `calendar_feeds` tables are created on
first use, as is `user_data`, which holds the site's saved state as key/value pairs stamped with
server time so devices can fetch what changed since their last sync.

Sign-in uses Google's button, which returns a signed ID token; the Worker checks it against
Google's public keys, so there's no client secret. To set it up:

1. Google Cloud console → APIs & Services → Credentials → Create OAuth client ID → Web application.
2. Authorized JavaScript origins: `https://ufscheduler.jackie-courtney.com`,
   `https://uf-scheduler.jackieec956.workers.dev`, `http://localhost:3000`. No redirect URIs.
3. Put the client ID in `GOOGLE_CLIENT_ID` in `wrangler.jsonc` and in the frontend's
   `REACT_APP_GOOGLE_CLIENT_ID`.

`npm test` checks the token verification.

## Deploying

The API token needs the **Account > D1 > Edit** permission in addition to Workers.

```sh
npx wrangler d1 create uf-scheduler-courses   # paste the database_id into wrangler.jsonc
npm run seed:remote
npx wrangler deploy
```

Then set the frontend's `REACT_APP_API_SERVER_IP` to the Worker URL and redeploy the frontend.
Allowed origins live in `ALLOWED_ORIGINS` in `wrangler.jsonc`.
