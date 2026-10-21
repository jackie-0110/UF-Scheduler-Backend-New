"""
Turns the local courses_{year}_{term}.db search databases into SQL files for D1.

    python scripts/export_d1_seed.py
    cd worker && npx wrangler d1 execute uf-scheduler-courses --local --file seed/27_spring.sql

Each term gets its own FTS5 table, courses_{year}_{term}, with the same columns and prefix
settings the Flask app uses, so the search query carries over unchanged.
"""
import glob
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'worker', 'seed')
COLUMNS = ['code', 'codeWithSpace', 'name', 'description', 'instructors', 'json_data']


def quote(value):
    return "'" + str(value if value is not None else '').replace("'", "''") + "'"


def main():
    os.makedirs(OUT, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(ROOT, 'courses_*.db'))):
        key = re.match(r'courses_(.+)\.db', os.path.basename(path)).group(1)
        table = f'courses_{key}'
        conn = sqlite3.connect(path)
        rows = conn.execute(f'SELECT {", ".join(COLUMNS)} FROM courses_fts').fetchall()
        conn.close()

        with open(os.path.join(OUT, f'{key}.sql'), 'w') as f:
            f.write(f'DROP TABLE IF EXISTS {table};\n')
            f.write(
                f'CREATE VIRTUAL TABLE {table} USING fts5('
                'code, codeWithSpace, name, description, instructors, json_data UNINDEXED, '
                "prefix='2 3 4');\n"
            )
            for row in rows:
                f.write(
                    f'INSERT INTO {table} ({", ".join(COLUMNS)}) VALUES ('
                    + ', '.join(quote(v) for v in row)
                    + ');\n'
                )
        print(f'{table}: {len(rows)} rows')


if __name__ == '__main__':
    main()
