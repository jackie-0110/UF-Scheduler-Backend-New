import { Env, json, readJson } from "./http";
import { termKey } from "./terms";

interface GraphBody {
  selectedMajorServ?: string;
  selectedCoursesServ?: string[];
  year?: string;
  term?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  kind: string;
  group: string | null;
}

interface StoredGraph {
  nodes: string[];
  edges: GraphEdge[];
}

const EMPTY: StoredGraph = { nodes: [], edges: [] };
const majorIndexes = new Map<string, Record<string, string>>();
const graphs = new Map<string, StoredGraph>();

async function loadAsset<T>(env: Env, path: string): Promise<T | null> {
  const response = await env.DATA.fetch(`https://assets.local/${path}`);
  return response.ok ? ((await response.json()) as T) : null;
}

async function loadGraph(env: Env, key: string, major: string): Promise<StoredGraph> {
  let index = majorIndexes.get(key);
  if (!index) {
    index = (await loadAsset<Record<string, string>>(env, `graphs/${key}/index.json`)) ?? {};
    majorIndexes.set(key, index);
  }
  const file = Object.prototype.hasOwnProperty.call(index, major) ? index[major] : null;
  if (!file) return EMPTY;

  const path = `graphs/${key}/${file}`;
  let graph = graphs.get(path);
  if (!graph) {
    graph = (await loadAsset<StoredGraph>(env, path)) ?? EMPTY;
    graphs.set(path, graph);
  }
  return graph;
}

/** "COP3502C" -> "COP\n3502": the node id the graph uses (lab/section letters dropped). */
export const graphNodeId = (code: string) => {
  const base = code.replace(/[A-Z ]+$/, "");
  return `${base.slice(0, 3)}\n${base.slice(3)}`;
};

/** POST /generate_a_list: a major's prerequisite graph with the taken courses marked selected. */
export async function handleGraph(request: Request, env: Env): Promise<Response> {
  const body = await readJson<GraphBody>(request);
  const taken = body?.selectedCoursesServ;
  if (!body || typeof body.selectedMajorServ !== "string" || !Array.isArray(taken)) {
    return json({ error: "Missing 'selectedMajorServ' or 'selectedCoursesServ'" }, 400);
  }

  const key = termKey(body.year, body.term);
  const base = key ? await loadGraph(env, key, body.selectedMajorServ) : EMPTY;

  const selected = new Set(taken.map((course) => graphNodeId(String(course))));
  // every taken course is shown, even when it isn't part of the major's graph
  const nodeIds = new Set(base.nodes);
  selected.forEach((id) => nodeIds.add(id));

  return json({
    nodes: Array.from(nodeIds, (id) => ({
      data: { id },
      classes: selected.has(id) ? "selected" : "not_selected",
    })),
    edges: base.edges.map((edge) => ({
      data: { source: edge.source, target: edge.target, kind: edge.kind, group: edge.group },
      classes: edge.kind,
    })),
  });
}
