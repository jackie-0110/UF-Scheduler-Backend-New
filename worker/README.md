# UF Scheduler API (Cloudflare Worker)

Same endpoints as the Flask app in the repo root, running on Workers + D1 so it never sleeps:

| Endpoint | Source |
| --- | --- |
| `POST /api/get_courses` | FTS5 search in D1 (`courses_{year}_{term}` tables) |
| `GET /api/prereqs?year=&term=` | prebuilt `data/prereqs/{year}_{term}.json` |
| `POST /generate_a_list` | prebuilt `data/graphs/{year}_{term}/*.json` |

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

## Deploying

The API token needs the **Account > D1 > Edit** permission in addition to Workers.

```sh
npx wrangler d1 create uf-scheduler-courses   # paste the database_id into wrangler.jsonc
npm run seed:remote
npx wrangler deploy
```

Then set the frontend's `REACT_APP_API_SERVER_IP` to the Worker URL and redeploy the frontend.
Allowed origins live in `ALLOWED_ORIGINS` in `wrangler.jsonc`.
