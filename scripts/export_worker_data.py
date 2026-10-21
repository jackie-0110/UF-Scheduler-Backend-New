"""
Exports the static data the Cloudflare Worker serves, using the same parser and graph
builders as the Flask app so both backends agree.

    python scripts/export_worker_data.py

Writes worker/data/:
  prereqs/{year}_{term}.json          parsed prerequisites for every course
  graphs/{year}_{term}/index.json     major name -> graph file
  graphs/{year}_{term}/{n}.json       {nodes: [id], edges: [{source, target, kind, group}]}
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import server  # noqa: E402  (loads the course files and builds every graph)

OUT = os.path.join(ROOT, 'worker', 'data')


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(value, f, separators=(',', ':'))


def main():
    for (year, term), info in server.course_info_map.items():
        key = f'{year}_{term}'
        write_json(os.path.join(OUT, 'prereqs', f'{key}.json'), info)

        index = {}
        for number, (major, graph) in enumerate(server.major_graph_map[(year, term)].items()):
            index[major] = f'{number}.json'
            write_json(os.path.join(OUT, 'graphs', key, f'{number}.json'), {
                'nodes': list(graph.nodes()),
                'edges': [
                    {
                        'source': u,
                        'target': v,
                        'kind': attrs.get('kind', 'required'),
                        'group': attrs.get('group'),
                    }
                    for u, v, attrs in graph.edges(data=True)
                ],
            })
        write_json(os.path.join(OUT, 'graphs', key, 'index.json'), index)
        print(f'{key}: {len(info)} courses, {len(index)} majors')


if __name__ == '__main__':
    main()
