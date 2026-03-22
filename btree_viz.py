"""
B-Tree Visualizer — renders SQLite's internal B-tree structure using graphviz.

Uses `sqlite3_analyzer`-style introspection via the undocumented but stable
sqlite_dbpage virtual table and manual page parsing. For the lab we take a
simpler approach: we build a pure-Python B-tree that mirrors SQLite's behavior
(order-4 B+tree) so participants can *see* splits and rebalancing happen
step-by-step.

Usage:
    from btree_viz import BPlusTree, render_tree
    tree = BPlusTree(order=4)
    for key in [10, 20, 5, 15, 25, 30, 35]:
        tree.insert(key)
        render_tree(tree, f"step_{key}")
"""

from __future__ import annotations
import math
import subprocess
import shutil
from typing import Optional


# ── B+Tree implementation (educational, not production) ─────────────────────

class Node:
    def __init__(self, leaf: bool = False):
        self.keys: list[int] = []
        self.children: list[Node] = []
        self.leaf: bool = leaf
        self.parent: Optional[Node] = None
        # For tracking stats
        self.id: int = id(self)

    def __repr__(self):
        return f"Node(keys={self.keys}, leaf={self.leaf})"


class BPlusTree:
    """
    Order-m B+Tree.  m = max children per internal node.
    - Internal node: ceil(m/2) .. m children,  ceil(m/2)-1 .. m-1 keys
    - Leaf node: ceil(m/2)-1 .. m-1 keys (values omitted for clarity)
    """

    def __init__(self, order: int = 4):
        self.order = order  # max children for internal nodes
        self.root = Node(leaf=True)
        self.split_count = 0
        self.insert_count = 0
        self.history: list[dict] = []  # tracks every mutation for replay

    # ── Public API ──────────────────────────────────────────────────────

    def insert(self, key: int) -> dict:
        """Insert a key and return stats about what happened."""
        self.insert_count += 1
        splits_before = self.split_count
        comparisons = self._insert(key)
        event = {
            "op": "insert",
            "key": key,
            "comparisons": comparisons,
            "splits": self.split_count - splits_before,
            "tree_height": self.height(),
            "total_keys": self.count_keys(),
        }
        self.history.append(event)
        return event

    def search(self, key: int) -> tuple[bool, int]:
        """Search for a key. Returns (found, comparisons)."""
        node = self.root
        comparisons = 0
        while not node.leaf:
            i = 0
            while i < len(node.keys):
                comparisons += 1
                if key < node.keys[i]:
                    break
                i += 1
            node = node.children[i]
        comparisons_in_leaf = 0
        for k in node.keys:
            comparisons_in_leaf += 1
            if k == key:
                return True, comparisons + comparisons_in_leaf
        return False, comparisons + comparisons_in_leaf

    def height(self) -> int:
        h = 0
        node = self.root
        while not node.leaf:
            h += 1
            node = node.children[0]
        return h + 1

    def count_keys(self) -> int:
        return self._count_keys(self.root)

    # ── Internal insert logic ───────────────────────────────────────────

    def _insert(self, key: int) -> int:
        """Insert key, return number of comparisons made."""
        node = self.root
        comparisons = 0

        # Traverse to leaf
        while not node.leaf:
            i = 0
            while i < len(node.keys):
                comparisons += 1
                if key < node.keys[i]:
                    break
                i += 1
            node = node.children[i]

        # Insert into leaf in sorted order
        i = 0
        while i < len(node.keys):
            comparisons += 1
            if key < node.keys[i]:
                break
            i += 1
        node.keys.insert(i, key)

        # Split if overflow
        if len(node.keys) >= self.order:
            self._split(node)

        return comparisons

    def _split(self, node: Node):
        self.split_count += 1
        mid = len(node.keys) // 2

        new_node = Node(leaf=node.leaf)

        if node.leaf:
            # Leaf split: copy mid key up, keep it in right node
            new_node.keys = node.keys[mid:]
            node.keys = node.keys[:mid]
            promote_key = new_node.keys[0]
        else:
            # Internal split: push mid key up, don't keep in either
            promote_key = node.keys[mid]
            new_node.keys = node.keys[mid + 1:]
            node.keys = node.keys[:mid]
            new_node.children = node.children[mid + 1:]
            node.children = node.children[:mid + 1]
            for child in new_node.children:
                child.parent = new_node

        if node.parent is None:
            # Splitting the root — tree grows taller
            new_root = Node(leaf=False)
            new_root.keys = [promote_key]
            new_root.children = [node, new_node]
            node.parent = new_root
            new_node.parent = new_root
            self.root = new_root
        else:
            new_node.parent = node.parent
            parent = node.parent
            # Find position in parent
            i = parent.children.index(node)
            parent.keys.insert(i, promote_key)
            parent.children.insert(i + 1, new_node)
            # Check if parent overflows
            if len(parent.keys) >= self.order:
                self._split(parent)

    def _count_keys(self, node: Node) -> int:
        if node.leaf:
            return len(node.keys)
        return len(node.keys) + sum(self._count_keys(c) for c in node.children)

    # ── Traversal helpers ───────────────────────────────────────────────

    def all_nodes(self) -> list[Node]:
        """BFS traversal returning all nodes."""
        result = []
        queue = [self.root]
        while queue:
            node = queue.pop(0)
            result.append(node)
            if not node.leaf:
                queue.extend(node.children)
        return result

    def leaf_scan(self) -> list[int]:
        """Return all keys via leaf-level scan (simulates full table scan)."""
        node = self.root
        while not node.leaf:
            node = node.children[0]
        keys = []
        # In a real B+tree leaves are linked; here we just collect from tree
        self._collect_leaf_keys(self.root, keys)
        return keys

    def _collect_leaf_keys(self, node: Node, keys: list[int]):
        if node.leaf:
            keys.extend(node.keys)
        else:
            for child in node.children:
                self._collect_leaf_keys(child, keys)


# ── Visualization ───────────────────────────────────────────────────────────

def render_tree(tree: BPlusTree, filename: str = "btree",
                output_dir: str = ".", fmt: str = "png",
                highlight_key: Optional[int] = None) -> str:
    """
    Render B+tree to an image using graphviz DOT format.
    Falls back to ASCII if graphviz is not installed.
    Returns the path to the generated file (or ASCII string).
    """
    dot_lines = [
        'digraph BPlusTree {',
        '    node [shape=record, height=0.4, fontsize=12, fontname="Courier"];',
        '    edge [fontsize=10];',
        f'    labelloc="t"; label="B+Tree  |  height={tree.height()}  |  keys={tree.count_keys()}  |  splits={tree.split_count}";',
        '',
    ]

    node_ids = {}
    counter = [0]

    def get_id(node):
        if id(node) not in node_ids:
            node_ids[id(node)] = f"n{counter[0]}"
            counter[0] += 1
        return node_ids[id(node)]

    def add_node(node):
        nid = get_id(node)
        # Build record label
        if node.leaf:
            parts = [f"<f{i}> {k}" for i, k in enumerate(node.keys)]
            label = "|".join(parts)
            color = "lightblue"
        else:
            # Internal node: <ptr0> | key0 | <ptr1> | key1 | <ptr2>
            parts = []
            for i, k in enumerate(node.keys):
                parts.append(f"<p{i}>  ")
                parts.append(f"<k{i}> {k}")
            parts.append(f"<p{len(node.keys)}>  ")
            label = "|".join(parts)
            color = "lightyellow"

        # Highlight
        if highlight_key is not None and highlight_key in node.keys:
            color = "salmon"

        dot_lines.append(f'    {nid} [label="{label}", style=filled, fillcolor={color}];')

        if not node.leaf:
            for i, child in enumerate(node.children):
                child_id = get_id(child)
                dot_lines.append(f'    {nid}:p{i} -> {child_id};')
                add_node(child)

    add_node(tree.root)
    dot_lines.append('}')
    dot_src = "\n".join(dot_lines)

    # Try graphviz
    dot_path = f"{output_dir}/{filename}.dot"
    img_path = f"{output_dir}/{filename}.{fmt}"

    with open(dot_path, "w") as f:
        f.write(dot_src)

    if shutil.which("dot"):
        subprocess.run(["dot", f"-T{fmt}", dot_path, "-o", img_path],
                       check=True, capture_output=True)
        return img_path
    else:
        return dot_path  # user can paste into online graphviz viewer


def ascii_tree(tree: BPlusTree) -> str:
    """Simple text representation for terminals without graphviz."""
    lines = []
    levels: list[list[Node]] = []
    current_level = [tree.root]

    while current_level:
        levels.append(current_level)
        next_level = []
        for node in current_level:
            if not node.leaf:
                next_level.extend(node.children)
        current_level = next_level

    for depth, level in enumerate(levels):
        prefix = "  " * (len(levels) - depth - 1)
        node_strs = []
        for node in level:
            tag = "L" if node.leaf else "I"
            node_strs.append(f"[{tag}: {','.join(map(str, node.keys))}]")
        lines.append(prefix + "  ".join(node_strs))

    return "\n".join(lines)


# ── Quick demo when run directly ────────────────────────────────────────────

if __name__ == "__main__":
    tree = BPlusTree(order=4)
    keys = [10, 20, 5, 15, 25, 30, 35, 40, 3, 7, 12, 18, 22, 28, 33, 38]
    print("B+Tree Insert Sequence Demo (order=4)")
    print("=" * 55)
    for k in keys:
        event = tree.insert(k)
        splits = event["splits"]
        split_msg = f" *** {splits} SPLIT(S)! ***" if splits > 0 else ""
        print(f"Insert {k:3d} → comparisons={event['comparisons']}, "
              f"height={event['tree_height']}, total_keys={event['total_keys']}{split_msg}")

    print(f"\nFinal tree: height={tree.height()}, "
          f"total splits={tree.split_count}, keys={tree.count_keys()}")
    print(f"\nASCII view:\n{ascii_tree(tree)}")
    print(f"\nTheoretical: O(log_{tree.order}({tree.count_keys()})) = "
          f"O({math.log(tree.count_keys(), tree.order):.2f}) per lookup")
