from services.analysis.domain import Evidence
from services.analysis.graph import neighbors, resolve_imports
from services.analysis.retrieval import rank


def test_relative_import_resolution_is_conservative():
    edges = [
        {"from": "src/main.ts", "to": value}
        for value in ["./price.js", "./ambiguous", "external", "../../outside"]
    ]
    graph = resolve_imports(edges, {"src/price.ts", "src/ambiguous.ts", "src/ambiguous.js"})
    assert graph[0]["target"] == "src/price.ts"
    assert all(edge["resolution"] == "unresolved" for edge in graph[1:])
    assert neighbors(graph, {"src/price.ts"}) == {"src/main.ts"}
    assert neighbors(graph, {"src/main.ts"}, limit=0) == set()


def test_graph_boost_is_visible_and_requires_lexical_match():
    chunk = Evidence(
        id="x",
        revision="a" * 40,
        path="price.ts",
        start_line=1,
        end_line=1,
        quote="export const discount = 10;",
        symbol="discount",
        kind="variable",
    )
    plain = rank("discount", [chunk])[0]
    boosted = rank("discount", [chunk], neighbor_paths={"price.ts"})[0]
    assert boosted.score > plain.score
    assert boosted.score_breakdown["import_neighbor"] > 0
    assert rank("unrelated", [chunk], neighbor_paths={"price.ts"}) == []
