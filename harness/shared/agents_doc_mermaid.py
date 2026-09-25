"""Mermaid diagram structure for the per-directory documents.

Split from :mod:`agents_doc` along the seam the `god-file-decomposer` skill
names: *is this diagram well-formed* and *are this document's claims true*
grow for different reasons, and one module carrying both had reached
``limits.size_budget_lines``. Nothing here reads the tree.

A broken diagram fails silently in the worst way available: GitHub renders the
fence as an error box, which looks like a rendering glitch rather than a defect,
so it survives review. These checks are deliberately not a mermaid parser --
that would be a dependency in a stdlib gate -- but each one is a shape that has
actually shipped broken somewhere in this repository's history.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

try:
    from harness.shared.agents_doc_policy import AgentsDocConfig
except ImportError:  # sibling import when this dir is sys.path[0]
    from agents_doc_policy import AgentsDocConfig  # type: ignore[no-redef]

MERMAID_BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)

#: A node given a shape: an identifier immediately followed by a shape opener.
MERMAID_SHAPED_NODE = re.compile(r"(?<![\w-])([A-Za-z_][\w-]*)\s*[\[\(\{]")

#: Labels, edge captions and quoted text. Removed before bare identifiers are
#: counted, so `A -->|"yes"| B` contributes `A` and `B` rather than `yes`.
MERMAID_DECORATION = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]|\|[^|]*\||\"[^\"]*\"")

#: An edge, in mermaid's several flavours: `-->`, `---`, `==>`, `-.->`, `~~~`.
#: A line carrying none declares no bare endpoints, which keeps `style`,
#: `classDef` and the opening keyword out of the count.
MERMAID_EDGE = re.compile(r"-{2,}[->ox]?|={2,}[=>]?|-\.-*>?|~{3}")

MERMAID_IDENTIFIER = re.compile(r"(?<![\w-])([A-Za-z_][\w-]*)")

#: Mermaid syntax that reads as an identifier but names no node.
MERMAID_NON_NODES = frozenset(
    "subgraph end direction style classDef class click linkStyle callback call "
    "accTitle accDescr TB TD BT RL LR o x".split()
)


def declared_nodes(body: str, config: AgentsDocConfig) -> set[str]:
    """Every identifier the diagram uses as a node, shaped or bare.

    Counting only shaped nodes made the cap vacuous for the commonest diagram
    there is: `A --> B` with no labels declared *zero* nodes, so a diagram of
    any size passed. The previous comment claimed the approximation erred by
    over-counting, which was the reassuring direction and the wrong one.

    Bare endpoints are read only from lines carrying an edge, after labels,
    captions and quoted text are stripped. That still over-counts a captioned
    edge -- `A -- note --> B` contributes `note` -- and over-counting is the
    safe direction for a legibility budget, so it is left rather than parsed.
    """
    nodes: set[str] = set()
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        nodes |= {match.group(1) for match in MERMAID_SHAPED_NODE.finditer(line)}
        bare = MERMAID_DECORATION.sub(" ", line)
        if not MERMAID_EDGE.search(bare):
            continue
        for match in MERMAID_IDENTIFIER.finditer(bare):
            name = match.group(1)
            if name not in MERMAID_NON_NODES and name not in config.diagram_types:
                nodes.add(name)
    return nodes


def mermaid_findings(diagrams: Sequence[str], config: AgentsDocConfig) -> list[str]:
    """Structural checks the existing bracket-quoting rule cannot make.

    `test_documentation_truth` catches one failure mode -- a bare bracket in a
    label -- leaving an unknown opening keyword, an unbalanced quote and an
    unreadably dense diagram all passing. Each renders as an error box or as
    something nobody can follow, and none is visible until the page is opened.
    """
    findings: list[str] = []
    if len(diagrams) > config.max_diagrams:
        findings.append(f"{len(diagrams)} diagrams; at most {config.max_diagrams} keeps a document scannable")
    for index, body in enumerate(diagrams):
        lines = [line for line in body.splitlines() if line.strip()]
        if not lines:
            findings.append(f"diagram {index} is empty")
            continue
        opening = lines[0].strip()
        # The first whitespace-delimited token, not a prefix: `startswith` accepted
        # `flowchartX LR`, which shares a prefix with `flowchart` and renders as an
        # error box. A check that admits the typo it exists to catch is not a check.
        keyword = opening.split()[0] if opening.split() else opening
        if keyword not in config.diagram_types:
            findings.append(f"diagram {index} opens with {opening!r}, which is not a known mermaid diagram type")
        for lineno, line in enumerate(lines, 1):
            if line.count('"') % 2:
                findings.append(f"diagram {index} line {lineno} has an unbalanced quote: {line.strip()}")
            if line.count("[") != line.count("]"):
                findings.append(f"diagram {index} line {lineno} has unbalanced brackets: {line.strip()}")
        nodes = declared_nodes(body, config)
        if len(nodes) > config.max_diagram_nodes:
            findings.append(
                f"diagram {index} declares {len(nodes)} nodes; at most {config.max_diagram_nodes} stays legible"
            )
    return findings
