"""Personalised PageRank over a typed fact graph (card W4-03, PRD 6.3 step 3).

Pure computation, no I/O. The loader that reads the edges lives in
``channels.py``.
"""


def personalised_pagerank(
    edges: list[tuple[str, str, float]],
    seeds: dict[str, float],
    alpha: float,
    iterations: int,
    degree_damping: float,
) -> dict[str, float]:
    """Score every node by Personalised PageRank from ``seeds``.

    ``edges`` are undirected ``(a, b, weight)``. ``alpha`` is the teleport
    probability back to the seeds. A node's outgoing mass is the usual
    weight-proportional split divided by ``degree ** degree_damping``, so a
    hub passes on less than a node with few neighbours. Returns a score per
    node (seeds included).
    """
    adjacency: dict[str, dict[str, float]] = {}
    for a, b, weight in edges:
        adjacency.setdefault(a, {})[b] = adjacency.get(a, {}).get(b, 0.0) + weight
        adjacency.setdefault(b, {})[a] = adjacency.get(b, {}).get(a, 0.0) + weight

    total = sum(seeds.values())
    if total <= 0:
        return {}
    restart = {node: value / total for node, value in seeds.items()}

    # Per node: the factor applied to each neighbour's weight when spreading.
    spread = {
        node: 1.0 / (sum(nbrs.values()) * len(nbrs) ** degree_damping)
        for node, nbrs in adjacency.items()
    }

    scores = dict(restart)
    for _ in range(iterations):
        nxt = {node: alpha * value for node, value in restart.items()}
        for node, value in scores.items():
            nbrs = adjacency.get(node)
            if not nbrs:
                continue
            share = (1.0 - alpha) * value * spread[node]
            for other, weight in nbrs.items():
                nxt[other] = nxt.get(other, 0.0) + share * weight
        scores = nxt
    return scores
