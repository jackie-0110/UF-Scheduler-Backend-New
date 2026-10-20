from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import glob
import sqlite3
import re
import networkx as nx
import gc
import os
from prereq_parser import parse_course, normalize_code

app = Flask(__name__)
# Comma-separated list of sites allowed to call this API; override with ALLOWED_ORIGINS
ALLOWED_ORIGINS = os.environ.get(
    'ALLOWED_ORIGINS',
    'https://ufscheduler.jackie-courtney.com,https://uf-scheduler.jackieec956.workers.dev,http://localhost:3000'
).split(',')
CORS(app, origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()])

# -------------------------------------------------------------------
# 1. Locate and load all course JSON files corresponding to (_{year}_{term}_final.json)
#    Create a dictionary of code->course for each (year, term).
# -------------------------------------------------------------------

json_files = glob.glob('courses/*_final.json')

# Instead, add a new global dictionary to hold all pre-built graphs:
major_graph_map = {}  # {(year, term): {departmentName: nx.DiGraph}}
course_info_map = {}  # {(year, term): {courseCode: parsed prerequisite info}}

# Keep the parse_year_term_from_filename, get_connection, etc. as they are...

def parse_year_term_from_filename(filename):
    """
    Parses the filename to extract the year and term.
    Assumes filename ends with something like: '_{year}_{term}_final.json'
    For example: 'UF_Feb-21-2025_25_fall_final.json' -> (year='25', term='fall')
    """
    # This is a simple approach; adapt to your file naming as needed.
    # We'll split on underscores and take indices from the end.
    parts = os.path.basename(filename).split('_')
    # e.g. ['UF', 'Feb-21-2025', '25', 'fall', 'final.json']
    # year might be parts[-3], term might be parts[-2] (depending on your naming)
    year = parts[-3]
    term = parts[-2]
    # strip off any file extension from term if needed, e.g. "fall_final.json" -> "fall"
    if 'final.json' in term:
        term = term.replace('final.json', '')
    return year, term

# -------------------------------------------------------------------
# 2. Create/Open SQLite Database(s) for each (year, term)
#    and Create FTS Table with Prefixes, then insert data.
# -------------------------------------------------------------------

def get_connection(db_name):
    """
    Returns a connection to the given SQLite database.
    """
    return sqlite3.connect(db_name)

# Create a new in-memory structure to store all courses by (year, term):
year_term_course_list = {}  # {(year, term): [courses...]}

def init_db_for_file(json_path):
    """
    - Parses (year, term) from json_path
    - Creates a DB named 'courses_{year}_{term}.db'
    - Initializes the FTS table (with prefix) if needed
    - Inserts all courses specific to that file
    """
    year, term = parse_year_term_from_filename(json_path)
    db_name = f'courses_{year}_{term}.db'
    
    with open(json_path) as f:
        all_courses = json.load(f)

    conn = get_connection(db_name)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")

    cur.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS courses_fts
        USING fts5(
            code,
            codeWithSpace,
            name,
            description,
            instructors,
            json_data UNINDEXED,
            prefix='2 3 4'
        )
    ''')

    row_count = cur.execute('SELECT count(*) FROM courses_fts;').fetchone()[0]
    if row_count == 0:
        for course in all_courses:
            code = course['code']
            codeWithSpace = course.get('codeWithSpace', '')
            name = course.get('name', '')
            description = course.get('description', '')

            instructor_names = []
            for section in course.get('sections', []):
                for inst in section.get('instructors', []):
                    instructor_names.append(inst.get('name', ''))
            instructors_joined = ' '.join(instructor_names)

            # Store the entire course JSON
            json_str = json.dumps(course)

            cur.execute('''
                INSERT INTO courses_fts (
                    code, codeWithSpace, name, description, 
                    instructors, json_data
                )
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (code, codeWithSpace, name, description, 
                  instructors_joined, json_str))

        conn.commit()

    conn.close()

    # Instead of storing course_data_map and course_dept_map,
    # keep a list of all courses for this (year, term):
    year_term_course_list[(year, term)] = all_courses

# Initialize a DB for each final JSON on startup
for jpath in json_files:
    init_db_for_file(jpath)

def format_course_code(course):
    return course[:3] + '\n' + course[3:]


def graph_node_id(code):
    """Graph node id for a course code; a lab/section letter suffix (CHM2046L) folds into the base course."""
    return format_course_code(normalize_code(code).rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ '))


def build_course_info(all_courses):
    """
    code -> parsed prerequisite info plus the basics the UI needs (name, credits, department).
    The prerequisite fields come from prereq_parser (AND of OR groups).
    """
    info = {}
    for course in all_courses:
        sections = course.get('sections', [])
        first = sections[0] if sections else {}
        parsed = parse_course(course)
        info[normalize_code(course['code'])] = {
            'code': normalize_code(course['code']),
            'name': course.get('name', ''),
            'credits': first.get('credits'),
            'dept': first.get('deptName', ''),
            'prereq': parsed['prereq'],
            'softPrereq': parsed['softPrereq'],
            'coreq': parsed['coreq'],
            'concurrent': parsed['concurrent'],
            'minGrade': parsed['minGrade'],
            'standing': parsed['standing'],
            'requirements': parsed['requirements'],
            'notes': parsed['notes'],
        }
    return info


def build_graph_for_all_majors(course_info):
    """
    Return a dict: { major: nx.DiGraph }. Each edge points prerequisite -> course and carries
    `kind`: 'required' (single course), 'choice' (one of several, grouped by `group`),
    'soft' (can also be waived by permission etc.) or 'coreq' (must be taken together).
    """
    by_dept = {}
    for info in course_info.values():
        by_dept.setdefault(info['dept'], []).append(info)

    graphs_for_majors = {}
    for dept, courses in by_dept.items():
        G = nx.DiGraph()
        for info in courses:
            target = graph_node_id(info['code'])
            groups = (
                [(g, 'required' if len(g) == 1 else 'choice') for g in info['prereq']]
                + [(g, 'soft') for g in info['softPrereq']]
                + [(g, 'coreq') for g in info['coreq'] + info['concurrent']]
            )
            for index, (group, kind) in enumerate(groups):
                for prereq in group:
                    source = graph_node_id(prereq)
                    if source == target:
                        continue
                    existing = G.get_edge_data(source, target)
                    if existing and existing['kind'] == 'required':
                        continue
                    G.add_edge(source, target, kind=kind, group=f'{target}:{index}')
        graphs_for_majors[dept] = G

    return graphs_for_majors


# Build all major graphs for each (year, term) and store in major_graph_map
for (year, term), all_courses in year_term_course_list.items():
    course_info_map[(year, term)] = build_course_info(all_courses)
    major_graph_map[(year, term)] = build_graph_for_all_majors(course_info_map[(year, term)])

# We can discard the raw course lists now that graphs are built
del year_term_course_list

# -------------------------------------------------------------------
# 3. Modify the /api/get_courses route to accept year and term,
#    then query the correct DB.
# -------------------------------------------------------------------
@app.route("/api/get_courses", methods=['POST'])
def get_courses():
    """
    Receives a JSON body with:
      - searchTerm: the query string
      - itemsPerPage: number of items per page
      - startFrom: offset for pagination
      - year:  '25'
      - term:  'fall', 'summer', 'spring', etc.
    Returns a JSON list of matched courses, from the correct DB.
    """
    data = request.json
    searchTerm = data.get('searchTerm', '').strip()
    itemsPerPage = data.get('itemsPerPage', 20)
    startFrom = data.get('startFrom', 0)
    year = data.get('year')
    term = data.get('term')

    if not year or not term:
        return jsonify({"error": "Missing 'year' or 'term' in request body"}), 400

    # Only terms with scraped data have a database; anything else has no results
    if (year, term) not in major_graph_map:
        return jsonify([])

    db_name = f'courses_{year}_{term}.db'

    if not searchTerm:
        return jsonify([])

    # For prefix matching in FTS. Keep only alphanumeric tokens and quote them so
    # punctuation ("C++", "COP-3502") and FTS keywords (AND, OR, NOT) can't break the query.
    terms = re.findall(r'[A-Za-z0-9]+', searchTerm)
    if not terms:
        return jsonify([])
    prefix_terms = [f'"{t}"*' for t in terms]
    fts_query = ' '.join(prefix_terms)
    exact_code = ''.join(terms).upper()

    conn = get_connection(db_name)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = '''
        SELECT
            json_data,
            -- weight code and title matches above description / instructor matches
            bm25(courses_fts, 10.0, 10.0, 6.0, 1.0, 2.0) AS rank,
            CASE 
                WHEN upper(code) = :exactSearch THEN 0 
                ELSE 1 
            END AS top_sort
        FROM courses_fts
        WHERE courses_fts MATCH :ftsQuery
        ORDER BY top_sort, rank
        LIMIT :limit
        OFFSET :offset
    '''

    rows = cur.execute(query, {
        'exactSearch': exact_code,
        'ftsQuery': fts_query,
        'limit': itemsPerPage,
        'offset': startFrom
    }).fetchall()

    results = []
    for row in rows:
        # Each row corresponds to one specific entry
        course_json = row['json_data']
        course = json.loads(course_json)
        results.append(course)

    conn.close()
    return jsonify(results)

# -------------------------------------------------------------------
# 5. /generate_a_list (same as your original)
# -------------------------------------------------------------------
@app.route('/generate_a_list', methods=['POST'])
def generate_a_list():
    data = request.get_json()
    G = nx.DiGraph()

    selected_major = data['selectedMajorServ']
    taken_courses = data['selectedCoursesServ']
    year = data.get('year')
    term = data.get('term')

    # Format the taken courses:
    formatted_taken_courses = [
        format_course_code(course.rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ '))
        for course in taken_courses
    ]

    # Retrieve the pre-built graph. If we don't have that major, use empty graph.
    major_graphs = major_graph_map.get((year, term), {})
    base_graph = major_graphs.get(selected_major, nx.DiGraph())
    # Make a copy so we don't mutate our global graph:
    G = base_graph.copy()

    # Now each taken course is guaranteed to be in the final node set
    # (existing logic to highlight or 'select' them):
    for course in formatted_taken_courses:
        G.add_node(course)

    # Build the final node/edge lists including 'selected' class:
    nodes = [
        {
            "data": {"id": node},
            "classes": "selected" if node in formatted_taken_courses else "not_selected"
        }
        for node in G.nodes()
    ]
    edges = [
        {
            "data": {
                "source": u,
                "target": v,
                "kind": attrs.get("kind", "required"),
                "group": attrs.get("group"),
            },
            "classes": attrs.get("kind", "required"),
        }
        for u, v, attrs in G.edges(data=True)
    ]

    return jsonify({
        'nodes': nodes,
        'edges': edges
    })

# -------------------------------------------------------------------
# 5b. /api/prereqs: parsed prerequisites for every course in a term
# -------------------------------------------------------------------
@app.route('/api/prereqs', methods=['GET'])
def get_prereqs():
    """
    GET /api/prereqs?year=27&term=spring

    Returns { courseCode: { name, credits, dept, prereq, softPrereq, coreq, concurrent,
    minGrade, standing, requirements, notes } }. `prereq`, `softPrereq`, `coreq` and
    `concurrent` are ANDs of OR groups: [["MAC2312"], ["MAC2512", "MAC3473"]] means
    MAC2312 AND (MAC2512 OR MAC3473).
    """
    year = request.args.get('year')
    term = request.args.get('term')
    info = course_info_map.get((year, term))
    if info is None:
        return jsonify({'error': 'unknown term'}), 404
    response = jsonify(info)
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

# -------------------------------------------------------------------
# 6. Optional: run the app
# -------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)