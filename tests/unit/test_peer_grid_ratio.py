"""Layout regression tests enforcing the strict 2:2:2 Peer Grid ratio and button alignment."""

from __future__ import annotations

import re
from pathlib import Path

from bitchat.tui.theme import TCSS_FILE


def test_peer_grid_tcss_ratio_is_strictly_2_2_2() -> None:
    """Validate that app.tcss enforces grid-columns: 2fr 2fr 2fr across desktop and compact modes."""
    content = TCSS_FILE.read_text(encoding="utf-8")

    # Match `#peers-footer-buttons` rule blocks
    pattern = re.compile(
        r"#peers-footer-buttons\s*\{([^}]+)\}",
        re.MULTILINE,
    )
    matches = pattern.findall(content)
    assert len(matches) >= 1, "Could not find #peers-footer-buttons rule in app.tcss"

    for block in matches:
        # Check grid-columns declaration
        cols_match = re.search(r"grid-columns:\s*([^;]+);", block)
        if cols_match:
            cols_val = cols_match.group(1).strip()
            assert cols_val == "2fr 2fr 2fr", (
                f"Peer grid ratio must be strictly '2fr 2fr 2fr', got {cols_val!r}"
            )

        # Check grid-size declaration
        size_match = re.search(r"grid-size:\s*([^;]+);", block)
        if size_match:
            size_val = size_match.group(1).strip()
            assert size_val == "3 2", (
                f"Peer grid size must be 3 columns by 2 rows ('3 2'), got {size_val!r}"
            )


def test_peer_grid_widget_structure_and_column_arrangement() -> None:
    """Verify that PeersScreen compose yields buttons in exactly 3 equal columns across 2 rows."""
    import ast

    peers_source_path = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "bitchat"
        / "tui"
        / "screens"
        / "peers.py"
    )
    assert peers_source_path.exists(), f"Source file not found: {peers_source_path}"

    tree = ast.parse(peers_source_path.read_text(encoding="utf-8"))

    # Find PeersScreen class
    peers_screen_cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "PeersScreen":
            peers_screen_cls = node
            break
    assert peers_screen_cls is not None, "PeersScreen class definition not found"

    # Find compose method
    compose_fn = None
    for item in peers_screen_cls.body:
        if isinstance(item, ast.FunctionDef) and item.name == "compose":
            compose_fn = item
            break
    assert compose_fn is not None, "compose method not found in PeersScreen"

    # Find Grid with id="peers-footer-buttons"
    footer_grid = None
    for node in ast.walk(compose_fn):
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    call = item.context_expr
                    # Check if Grid(..., id="peers-footer-buttons")
                    for kw in call.keywords:
                        if (
                            kw.arg == "id"
                            and isinstance(kw.value, ast.Constant)
                            and kw.value.value == "peers-footer-buttons"
                        ):
                            footer_grid = node
                            break

    assert footer_grid is not None, (
        "Grid(id='peers-footer-buttons') not found in compose"
    )

    # Inspect the yields inside footer_grid
    yielded_items = []
    for stmt in footer_grid.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Yield):
            yield_val = stmt.value.value
            if isinstance(yield_val, ast.Call):
                widget_type = getattr(yield_val.func, "id", None)
                widget_id = None
                classes = None
                for kw in yield_val.keywords:
                    if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                        widget_id = kw.value.value
                    elif kw.arg == "classes" and isinstance(kw.value, ast.Constant):
                        classes = kw.value.value
                yielded_items.append((widget_type, widget_id, classes))

    # Strict 2:2:2 ratio across 2 rows requires 3 columns x 2 rows = 6 items
    assert len(yielded_items) == 6, (
        f"Expected 6 items in 3x2 grid, found {len(yielded_items)}"
    )

    # Row 1 (3 items): Connect, Disconnect, Back
    row1 = yielded_items[0:3]
    assert [item[1] for item in row1] == [
        "btn-peers-connect",
        "btn-peers-disconnect",
        "btn-peers-back",
    ]
    assert all(item[0] == "Button" for item in row1)
    assert all(item[2] == "action-btn" for item in row1)

    # Row 2 (3 items): Refresh, Open Chat, Spacer
    row2 = yielded_items[3:6]
    assert [item[1] for item in row2] == [
        "btn-peers-refresh",
        "btn-peers-chat",
        "peers-grid-spacer",
    ]
    assert row2[0][0] == "Button" and row2[0][2] == "action-btn"
    assert row2[1][0] == "Button" and row2[1][2] == "action-btn"
    assert row2[2][0] == "Static" and row2[2][2] == "action-btn-spacer"


def test_compact_footer_responsive_fallback_preserves_2_2_2_ratio() -> None:
    """Ensure that the compact responsive fallback retains the strict 2:2:2 ratio."""
    content = TCSS_FILE.read_text(encoding="utf-8")

    compact_pattern = re.compile(
        r"#peers-action-bar\.compact-footer\s+#peers-footer-buttons\s*\{([^}]+)\}",
        re.MULTILINE,
    )
    compact_matches = compact_pattern.findall(content)
    assert len(compact_matches) >= 1, "Compact footer style rule missing"

    for block in compact_matches:
        cols_match = re.search(r"grid-columns:\s*([^;]+);", block)
        assert cols_match is not None, "Compact footer missing grid-columns declaration"
        assert cols_match.group(1).strip() == "2fr 2fr 2fr", (
            f"Compact footer grid-columns must be '2fr 2fr 2fr', got {cols_match.group(1)!r}"
        )
