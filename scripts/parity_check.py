"""
Compares the Worker against the Flask app on the same requests.

    python scripts/parity_check.py http://localhost:8787 http://localhost:5055

Run `wrangler dev` (in worker/) and the Flask app, then give the Worker URL first.
Responses are compared as parsed JSON, so key order and whitespace don't matter.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

SEARCHES = [
    'cop 3502', 'COP3502C', 'calculus', 'C++', 'smith', 'AND OR', 'mac', 'intro to',
    'a', '   ', '!!!', 'cop-3503', 'organic chemistry', 'statistics', 'zzzzqqq', 'ENC 1101',
]
TERMS = [('27', 'spring'), ('26', 'fall'), ('25', 'fall'), ('99', 'winter')]


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAKEN = [['COP3502C', 'MAC2311'], [], ['CHM2046L', 'XYZ9999', 'ENC1101']]


def request(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, headers={'Content-Type': 'application/json', 'User-Agent': 'parity-check/1.0'}
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
        except urllib.error.URLError:
            # a dropped connection to the remote Worker shouldn't end a long run
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def compare(label, worker, flask, failures):
    ok = worker == flask
    if not ok:
        failures.append(label)
    print(('ok   ' if ok else 'FAIL ') + label)


def main(worker_url, flask_url):
    failures = []

    for year, term in TERMS:
        for text in SEARCHES:
            for page in (0, 20):
                body = {'searchTerm': text, 'itemsPerPage': 20, 'startFrom': page,
                        'year': year, 'term': term}
                compare(
                    f'search {year}_{term} {text!r} from {page}',
                    request(worker_url, '/api/get_courses', body),
                    request(flask_url, '/api/get_courses', body),
                    failures,
                )

    bad = {'searchTerm': 'x'}
    compare('search missing year/term', request(worker_url, '/api/get_courses', bad),
            request(flask_url, '/api/get_courses', bad), failures)

    for year, term in TERMS:
        path = f'/api/prereqs?year={year}&term={term}'
        compare(f'prereqs {year}_{term}', request(worker_url, path), request(flask_url, path), failures)

    for year, term in TERMS:
        index_path = os.path.join(ROOT, 'worker', 'data', 'graphs', f'{year}_{term}', 'index.json')
        majors = list(json.load(open(index_path))) if os.path.exists(index_path) else []
        for major in majors + ['No Such Major']:
            for taken in TAKEN:
                body = {'selectedMajorServ': major, 'selectedCoursesServ': taken,
                        'year': year, 'term': term}
                compare(
                    f'graph {year}_{term} {major!r} taken={len(taken)}',
                    request(worker_url, '/generate_a_list', body),
                    request(flask_url, '/generate_a_list', body),
                    failures,
                )

    print(f'\n{len(failures)} mismatches')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1].rstrip('/'), sys.argv[2].rstrip('/')))
