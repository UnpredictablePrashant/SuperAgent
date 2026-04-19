from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path
from urllib.parse import unquote, urlparse



def wrap_text(text: str, width: int = 22) -> str:
    return "\n".join(textwrap.wrap(str(text), width=width))


def extract_node(token: str):
    """
    Parse Mermaid node syntax:
      A[Text]
      B{Decision}
      C(Text)
      D
    Returns: (node_id, label, shape)
    """
    token = token.strip()

    patterns = [
        (r'^([A-Za-z0-9_]+)\[(.+)\]$', 'rect'),
        (r'^([A-Za-z0-9_]+)\{(.+)\}$', 'diamond'),
        (r'^([A-Za-z0-9_]+)\((.+)\)$', 'round'),
        (r'^([A-Za-z0-9_]+)$', 'plain'),
    ]

    for pattern, shape in patterns:
        m = re.match(pattern, token)
        if m:
            node_id = m.group(1)
            label = m.group(2) if len(m.groups()) > 1 else node_id
            return node_id, label.strip(), shape

    raise ValueError(f"Could not parse Mermaid node: {token}")


def split_mermaid_chain(line: str):
    """
    Supports:
      A --> B
      A -->|Yes| B
      A -- Yes --> B
      A --> B --> C
    """
    token_pattern = re.compile(r'(-->\|[^|]+\||--\s*[^-][^-]*?\s*-->|-->)')
    parts = token_pattern.split(line)
    return [p.strip() for p in parts if p and p.strip()]


def parse_edge_operator(op: str) -> str:
    """
    Parse Mermaid edge operators:
      -->
      -->|Yes|
      -- Yes -->
    """
    op = op.strip()

    m = re.match(r'^-->\|(.+)\|$', op)
    if m:
        return m.group(1).strip()

    m = re.match(r'^--\s*(.+?)\s*-->$', op)
    if m:
        return m.group(1).strip()

    return '' if op == '-->' else ''


def parse_mermaid_flowchart(mermaid_text: str):
    """
    Parse simplified Mermaid flowcharts.
    Supports:
      flowchart TD
      A[Start] --> B[Next]
      B -->|Yes| C[Approved]
      B -- No --> D[Rejected]
      A --> B --> C
    """
    lines = [line.strip() for line in mermaid_text.strip().splitlines() if line.strip()]

    if not lines:
        return [], {}, {}

    if lines[0].lower().startswith("flowchart"):
        lines = lines[1:]

    edges = []
    node_labels = {}
    node_shapes = {}

    for line in lines:
        if line.lower().startswith(("classdef ", "class ", "style ", "linkstyle ", "subgraph ", "end")):
            continue

        parts = split_mermaid_chain(line)
        if len(parts) < 3:
            continue

        for i in range(0, len(parts) - 2, 2):
            left_raw = parts[i]
            op = parts[i + 1]
            right_raw = parts[i + 2]

            try:
                left_id, left_label, left_shape = extract_node(left_raw)
                right_id, right_label, right_shape = extract_node(right_raw)
            except ValueError:
                continue

            edge_label = parse_edge_operator(op)

            node_labels[left_id] = left_label
            node_labels[right_id] = right_label
            node_shapes[left_id] = left_shape
            node_shapes[right_id] = right_shape
            edges.append((left_id, right_id, edge_label))

    return edges, node_labels, node_shapes


def compute_hierarchical_positions(graph: nx.DiGraph):
    """
    Create a basic top-down layout for DAG-like graphs.
    Falls back to spring layout if needed.
    """
    try:
        roots = [n for n in graph.nodes() if graph.in_degree(n) == 0]
        if not roots:
            raise ValueError("No roots found")

        levels = {}
        frontier = roots
        visited = set()
        level = 0

        while frontier:
            next_frontier = []
            for node in frontier:
                if node in visited:
                    continue
                visited.add(node)
                levels[node] = level
                for succ in graph.successors(node):
                    if succ not in visited:
                        next_frontier.append(succ)
            frontier = list(dict.fromkeys(next_frontier))
            level += 1

        for node in graph.nodes():
            if node not in levels:
                levels[node] = level

        level_map = {}
        for node, lvl in levels.items():
            level_map.setdefault(lvl, []).append(node)

        pos = {}
        for lvl, nodes in sorted(level_map.items()):
            count = len(nodes)
            for idx, node in enumerate(nodes):
                x = (idx + 1) / (count + 1)
                y = -lvl
                pos[node] = (x, y)

        return pos
    except Exception:
        return nx.spring_layout(graph, seed=42, k=2.0)


def mermaid_to_png(mermaid_text: str, output_path: str):
    """
    Render Mermaid-like flowchart to PNG.
    """
    import networkx as nx
    import matplotlib.pyplot as plt

    edges, node_labels, node_shapes = parse_mermaid_flowchart(mermaid_text)

    if not edges:
        raise ValueError("Could not parse Mermaid flowchart content.")

    g = nx.DiGraph()
    for src, dst, edge_label in edges:
        g.add_node(src)
        g.add_node(dst)
        g.add_edge(src, dst, label=edge_label)

    pos = compute_hierarchical_positions(g)

    plt.figure(figsize=(14, 10))
    ax = plt.gca()
    ax.set_axis_off()

    nx.draw_networkx_edges(
        g,
        pos,
        arrows=True,
        arrowstyle='-|>',
        arrowsize=18,
        width=1.5,
        connectionstyle='arc3,rad=0.03'
    )

    shape_map = {
        'rect': 's',
        'diamond': 'D',
        'round': 'o',
        'plain': 'o'
    }

    for shape_name, marker in shape_map.items():
        nodes = [n for n in g.nodes() if node_shapes.get(n, 'plain') == shape_name]
        if nodes:
            nx.draw_networkx_nodes(
                g,
                pos,
                nodelist=nodes,
                node_shape=marker,
                node_size=5000,
                linewidths=1.5
            )

    wrapped_labels = {node: wrap_text(node_labels.get(node, node), 22) for node in g.nodes()}
    nx.draw_networkx_labels(g, pos, labels=wrapped_labels, font_size=9)

    edge_labels = {(u, v): d.get("label", "") for u, v, d in g.edges(data=True) if d.get("label")}
    if edge_labels:
        nx.draw_networkx_edge_labels(g, pos, edge_labels=edge_labels, font_size=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close()


def replace_mermaid_blocks(md_text: str, asset_dir: Path) -> str:
    """
    Replace fenced mermaid blocks with generated PNG images.
    """
    asset_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r"```mermaid\s+(.*?)```", re.DOTALL | re.IGNORECASE)
    counter = 1

    def repl(match):
        nonlocal counter
        mermaid_code = match.group(1).strip()
        img_name = f"mermaid_diagram_{counter}.png"
        img_path = asset_dir / img_name

        try:
            mermaid_to_png(mermaid_code, str(img_path))
            replacement = f"\n![Flowchart]({img_path.as_posix()})\n"
        except Exception:
            replacement = (
                "\n\n**Flowchart could not be rendered automatically.**\n\n"
                "```text\n"
                f"{mermaid_code}\n"
                "```\n"
            )

        counter += 1
        return replacement

    return pattern.sub(repl, md_text)


def preprocess_markdown(md_text: str, asset_dir: Path) -> str:
    return replace_mermaid_blocks(md_text, asset_dir)


def _resolve_local_resource(uri: str, *, base_path: str | Path | None = None, rel: str | None = None) -> str:
    if not uri:
        return uri

    parsed = urlparse(uri)
    if parsed.scheme in {"http", "https", "data", "mailto"}:
        return uri
    if parsed.scheme == "file":
        file_path = Path(unquote(parsed.path))
        return str(file_path) if file_path.exists() else uri

    path = Path(uri)
    if path.is_absolute() and path.exists():
        return str(path)

    roots = []
    if base_path:
        roots.append(Path(base_path))
    if rel:
        roots.append(Path(rel))
    roots.append(Path.cwd())

    for root in roots:
        try:
            candidate = (root / uri).resolve()
        except Exception:
            continue
        if candidate.exists():
            return str(candidate)

    return uri


def link_callback(uri, rel, *, base_path: str | Path | None = None):
    """
    Resolve local image/file paths for xhtml2pdf.
    """
    return _resolve_local_resource(uri, base_path=base_path, rel=rel)


def _report_stylesheet(*, for_pdf: bool) -> str:
    page_css = """
            @page {
                size: A4;
                margin: 0.82in 0.72in 0.86in 0.72in;
            }
    """ if for_pdf else ""
    body_padding = "0" if for_pdf else "36px 22px 54px"
    shell_width = "100%" if for_pdf else "960px"
    shell_shadow = "none" if for_pdf else "0 18px 52px rgba(15, 23, 42, 0.12)"
    shell_radius = "0" if for_pdf else "24px"
    return f"""
            {page_css}
            body {{
                font-family: "Georgia", "Times New Roman", serif;
                font-size: 11pt;
                line-height: 1.72;
                color: #1f2937;
                background: #eef3f8;
                margin: 0;
                padding: {body_padding};
            }}

            .report-shell {{
                max-width: {shell_width};
                margin: 0 auto;
                background: #ffffff;
                border: 1px solid #dbe4ee;
                border-radius: {shell_radius};
                box-shadow: {shell_shadow};
                padding: 0.8in 0.72in 0.9in;
            }}

            h1, h2, h3, h4, h5, h6 {{
                color: #0f172a;
                font-family: "Georgia", "Times New Roman", serif;
                page-break-after: avoid;
            }}

            h1 {{
                font-size: 28pt;
                margin: 0 0 18px;
                padding-bottom: 10px;
                border-bottom: 2px solid #0f766e;
                letter-spacing: -0.02em;
            }}

            h2 {{
                font-size: 18pt;
                margin: 28px 0 10px;
                padding-bottom: 4px;
                border-bottom: 1px solid #d7e1eb;
            }}

            h3 {{
                font-size: 14pt;
                margin: 20px 0 8px;
                color: #134e4a;
            }}

            h4, h5, h6 {{
                margin: 14px 0 6px;
            }}

            p {{
                margin: 0 0 12px;
                text-align: justify;
            }}

            blockquote {{
                margin: 14px 0;
                padding: 10px 14px;
                border-left: 4px solid #0f766e;
                background: #f3fbfa;
                color: #334155;
                font-style: italic;
            }}

            ul, ol {{
                margin: 8px 0 14px 24px;
                padding: 0;
            }}

            li {{
                margin-bottom: 5px;
            }}

            li p {{
                margin-bottom: 4px;
                text-align: justify;
            }}

            a {{
                color: #0f766e;
                text-decoration: none;
                font-weight: 600;
            }}

            strong {{
                font-weight: 700;
                color: #0f172a;
            }}

            em {{
                font-style: italic;
                color: #475569;
            }}

            code {{
                font-family: "Courier New", monospace;
                background-color: #f8fafc;
                padding: 2px 4px;
                border: 1px solid #dbe4ee;
                border-radius: 3px;
                font-size: 9.6pt;
            }}

            pre {{
                font-family: "Courier New", monospace;
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #1e293b;
                border-radius: 10px;
                padding: 12px 14px;
                white-space: pre-wrap;
                word-wrap: break-word;
                font-size: 9pt;
                line-height: 1.5;
                overflow-x: auto;
            }}

            pre code {{
                background-color: transparent;
                border: none;
                padding: 0;
                color: inherit;
            }}

            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 16px 0;
                table-layout: fixed;
                background: #ffffff;
                border: 1px solid #dbe4ee;
            }}

            th, td {{
                border: 1px solid #dbe4ee;
                padding: 8px 10px;
                vertical-align: top;
                word-wrap: break-word;
                font-size: 10pt;
                text-align: left;
            }}

            th {{
                background: #0f172a;
                color: #f8fafc;
                font-weight: 700;
            }}

            tr:nth-child(even) td {{
                background: #f8fafc;
            }}

            img {{
                max-width: 100%;
                display: block;
                margin: 16px auto 8px;
                border-radius: 8px;
                border: 1px solid #dbe4ee;
            }}

            hr {{
                border: none;
                border-top: 1px solid #cbd5e1;
                margin: 22px 0;
            }}

            .report-footer {{
                margin-top: 34px;
                padding-top: 16px;
                border-top: 1px solid #d7e1eb;
                page-break-inside: avoid;
                text-align: center;
            }}

            .brand-lockup {{
                display: inline-flex;
                align-items: center;
                gap: 10px;
                color: #0f172a;
                font-family: "Georgia", "Times New Roman", serif;
                font-weight: 700;
                letter-spacing: 0.02em;
            }}

            .brand-mark {{
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 28px;
                height: 28px;
                border-radius: 9px;
                background: linear-gradient(135deg, #0f766e 0%, #134e4a 100%);
                color: #f8fafc;
                font-size: 12pt;
                line-height: 1;
                box-shadow: 0 8px 18px rgba(15, 118, 110, 0.16);
            }}

            .brand-name {{
                font-size: 11pt;
                color: #0f172a;
            }}
    """


def _inject_named_anchors(html_body: str) -> str:
    def _replace(match):
        tag_name = match.group(1)
        attrs = match.group(2) or ""
        if re.search(r'\bname\s*=', attrs):
            return match.group(0)
        id_match = re.search(r'\bid\s*=\s*"([^"]+)"', attrs)
        if not id_match:
            return match.group(0)
        anchor = id_match.group(1)
        return f'<a name="{anchor}"></a><{tag_name}{attrs}>'

    return re.sub(r"<(h[1-6])([^>]*)>", _replace, html_body)


def _absolutize_local_media_paths(html_body: str, *, base_path: str | Path | None = None) -> str:
    if not base_path:
        return html_body

    def _replace(match):
        attr = match.group(1)
        quote = match.group(2)
        value = match.group(3)
        resolved = _resolve_local_resource(value, base_path=base_path)
        return f'{attr}={quote}{resolved}{quote}'

    return re.sub(r'(src)\s*=\s*(["\'])([^"\']+)\2', _replace, html_body)


def _report_footer_html() -> str:
    return """
            <footer class="report-footer" aria-label="Kendr footer">
                <div class="brand-lockup">
                    <span class="brand-mark">K</span>
                    <span class="brand-name">Kendr</span>
                </div>
            </footer>
    """


def build_html_from_markdown(
    md_text: str,
    *,
    for_pdf: bool = False,
    base_path: str | Path | None = None,
) -> str:
    import markdown
    html_body = markdown.markdown(
        md_text,
        extensions=[
            "extra",
            "tables",
            "fenced_code",
            "toc",
            "sane_lists",
            "nl2br",
            "attr_list",
        ]
    )
    html_body = _inject_named_anchors(html_body)
    html_body = _absolutize_local_media_paths(html_body, base_path=base_path)

    return f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            {_report_stylesheet(for_pdf=for_pdf)}
        </style>
    </head>
    <body>
        <main class="report-shell">
            {html_body}
            {_report_footer_html()}
        </main>
    </body>
    </html>
    """


def md_to_pdf(md_file: str, pdf_file: str) -> None:
    """Convert a Markdown file to PDF using xhtml2pdf.

    Mermaid fenced code blocks are rendered as PNG diagrams via matplotlib/networkx.
    Raises FileNotFoundError if *md_file* does not exist, RuntimeError on PDF failure.
    """
    md_path = Path(md_file)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_file}")

    asset_dir = md_path.parent / "generated_assets"
    md_text = md_path.read_text(encoding="utf-8")

    processed_md = preprocess_markdown(md_text, asset_dir)
    html_output = build_html_from_markdown(processed_md, for_pdf=True, base_path=md_path.parent)

    from xhtml2pdf import pisa
    with open(pdf_file, "wb") as pdf:
        result = pisa.CreatePDF(
            src=html_output,
            dest=pdf,
            link_callback=lambda uri, rel: link_callback(uri, rel, base_path=md_path.parent),
        )

    if result.err:
        raise RuntimeError("PDF generation failed")
