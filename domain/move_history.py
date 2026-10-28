"""
Tree-structured MoveHistory supporting per-move variations and nested sub-variations (serialized via JSON).
Every position/move node can have multiple alternative continuations (`children[0]` = main continuation at that point,
`children[1..k]` = variations at that move), and any move inside a variation can itself have sub-variations.
"""
from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional
import chess
import chess.pgn


@dataclass(frozen=True)
class MoveNode:
    """Represents a single recorded ply in a mainline or variation continuation."""
    ply: int  # 1-based ply index from initial_fen
    uci: str
    san: str
    fen_before: str
    fen_after: str
    turn_before: str  # "white" or "black"
    fullmove_number: int
    is_capture: bool
    is_check: bool
    is_checkmate: bool
    is_castling: bool
    is_en_passant: bool
    promotion: Optional[str] = None
    comment: str = ""
    nag: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ply": self.ply,
            "uci": self.uci,
            "san": self.san,
            "fen_before": self.fen_before,
            "fen_after": self.fen_after,
            "turn_before": self.turn_before,
            "fullmove_number": self.fullmove_number,
            "is_capture": self.is_capture,
            "is_check": self.is_check,
            "is_checkmate": self.is_checkmate,
            "is_castling": self.is_castling,
            "is_en_passant": self.is_en_passant,
            "promotion": self.promotion,
            "comment": self.comment,
            "nag": self.nag,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MoveNode":
        return cls(
            ply=int(data["ply"]),
            uci=data["uci"],
            san=data["san"],
            fen_before=data["fen_before"],
            fen_after=data["fen_after"],
            turn_before=data["turn_before"],
            fullmove_number=int(data["fullmove_number"]),
            is_capture=bool(data.get("is_capture", False)),
            is_check=bool(data.get("is_check", False)),
            is_checkmate=bool(data.get("is_checkmate", False)),
            is_castling=bool(data.get("is_castling", False)),
            is_en_passant=bool(data.get("is_en_passant", False)),
            promotion=data.get("promotion"),
            comment=data.get("comment", ""),
            nag=data.get("nag"),
        )


@dataclass
class MoveTreeNode:
    """
    A node in the recursive variation tree.
    - The root node has `move=None` (representing `initial_fen`).
    - `children[0]` is the primary continuation from this position; `children[1..]` are variations at this ply.
    - `active_child_idx` tracks which continuation branch is currently selected at this position.
    """
    move: Optional[MoveNode] = None
    children: List["MoveTreeNode"] = field(default_factory=list)
    active_child_idx: int = 0
    parent: Optional["MoveTreeNode"] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "move": self.move.to_dict() if self.move is not None else None,
            "active_child_idx": self.active_child_idx,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], parent: Optional["MoveTreeNode"] = None) -> "MoveTreeNode":
        mv = MoveNode.from_dict(data["move"]) if data.get("move") else None
        node = cls(move=mv, active_child_idx=int(data.get("active_child_idx", 0)), parent=parent)
        node.children = [cls.from_dict(ch, parent=node) for ch in data.get("children", [])]
        if node.children and not (0 <= node.active_child_idx < len(node.children)):
            node.active_child_idx = 0
        return node


@dataclass
class MoveVariant:
    """Summary descriptor for a variation branch in the tree."""
    variant_id: int
    name: str
    branch_ply: int
    nodes: List[MoveNode] = field(default_factory=list)


class MoveHistory:
    """
    Recursive variation-tree MoveHistory:
    - Each position can have a main continuation (`children[0]`) and any number of alternative variations (`children[1..]`).
    - Variations can themselves contain sub-variations at any move!
    - At any cursor move, `get_variations_at_current_move()` returns only the variations belonging to THAT specific move
      (e.g., at move 10: Main `10.Nf3`, Var 1 `10.Bd3`, Var 2 `10.Rb1`), completely independent of variations at move 20!
    """

    def __init__(self, initial_fen: str = chess.STARTING_FEN) -> None:
        test_board = chess.Board(initial_fen)
        self._initial_fen: str = test_board.fen()
        self._root = MoveTreeNode(move=None)
        self._redo_stack: List[MoveNode] = []
        self._cursor: int = 0
        self._revision: int = 0

    @property
    def initial_fen(self) -> str:
        return self._initial_fen

    def _get_active_tree_path(self) -> List[MoveTreeNode]:
        """Return list of MoveTreeNodes along the currently selected path (excluding root)."""
        path: List[MoveTreeNode] = []
        curr = self._root
        while curr.children:
            idx = max(0, min(curr.active_child_idx, len(curr.children) - 1))
            curr.active_child_idx = idx
            nxt = curr.children[idx]
            path.append(nxt)
            curr = nxt
        return path

    def _get_mainline_tree_path(self) -> List[MoveTreeNode]:
        """Return list of MoveTreeNodes along the primary mainline (`children[0]` at every step)."""
        path: List[MoveTreeNode] = []
        curr = self._root
        while curr.children:
            nxt = curr.children[0]
            path.append(nxt)
            curr = nxt
        return path

    def _get_tree_node_at_ply(self, ply: int) -> MoveTreeNode:
        """Return the MoveTreeNode at `ply` (0 = root, k = k-th move on active path)."""
        if ply <= 0:
            return self._root
        path = self._get_active_tree_path()
        if ply > len(path):
            return path[-1] if path else self._root
        return path[ply - 1]

    @property
    def nodes(self) -> List[MoveNode]:
        return [tn.move for tn in self._get_active_tree_path() if tn.move is not None]

    @property
    def mainline_nodes(self) -> List[MoveNode]:
        return [tn.move for tn in self._get_mainline_tree_path() if tn.move is not None]

    @property
    def is_in_variant(self) -> bool:
        """Return True if any ancestor up to the current cursor (or along the active line) is a non-zero branch."""
        curr = self._root
        steps = 0
        while curr.children:
            if curr.active_child_idx != 0:
                return True
            curr = curr.children[0]
            steps += 1
        return False

    @property
    def variants(self) -> List[MoveVariant]:
        """Collect all variation branches in the tree for summary/persistence."""
        collected: List[MoveVariant] = []
        vid_counter = 1

        def _walk(parent_node: MoveTreeNode, prefix_moves: List[MoveNode]) -> None:
            nonlocal vid_counter
            if not parent_node.children:
                return
            for idx, child in enumerate(parent_node.children):
                if child.move is None:
                    continue
                if idx > 0:
                    # Collect the active continuation of this variation branch
                    branch_moves = list(prefix_moves)
                    ptr: Optional[MoveTreeNode] = child
                    while ptr is not None and ptr.move is not None:
                        branch_moves.append(ptr.move)
                        if ptr.children:
                            c_idx = max(0, min(ptr.active_child_idx, len(ptr.children) - 1))
                            ptr = ptr.children[c_idx]
                        else:
                            ptr = None
                    mv = child.move
                    mv_lbl = f"{mv.fullmove_number}.{mv.san}" if mv.turn_before == "white" else f"{mv.fullmove_number}...{mv.san}"
                    collected.append(
                        MoveVariant(
                            variant_id=vid_counter,
                            name=f"Var #{vid_counter} ({mv_lbl})",
                            branch_ply=len(prefix_moves),
                            nodes=branch_moves,
                        )
                    )
                    vid_counter += 1
                _walk(child, prefix_moves + [child.move])

        _walk(self._root, [])
        return collected

    @property
    def active_variant(self) -> Optional[MoveVariant]:
        if not self.is_in_variant:
            return None
        # Find the deepest non-zero branch along the active path
        curr = self._root
        prefix: List[MoveNode] = []
        deepest_branch_ply = 0
        deepest_move: Optional[MoveNode] = None
        deepest_idx = 1
        while curr.children:
            idx = max(0, min(curr.active_child_idx, len(curr.children) - 1))
            child = curr.children[idx]
            if idx > 0 and child.move is not None:
                deepest_branch_ply = len(prefix)
                deepest_move = child.move
                deepest_idx = idx
            if child.move is not None:
                prefix.append(child.move)
            curr = child

        if deepest_move is None:
            return None
        mv_lbl = (
            f"{deepest_move.fullmove_number}.{deepest_move.san}"
            if deepest_move.turn_before == "white"
            else f"{deepest_move.fullmove_number}...{deepest_move.san}"
        )
        return MoveVariant(
            variant_id=deepest_idx,
            name=f"Var {deepest_idx} ({mv_lbl})",
            branch_ply=deepest_branch_ply,
            nodes=self.nodes,
        )

    def _get_decision_parent_for_cursor(self) -> MoveTreeNode:
        """
        Return the decision parent MoveTreeNode whose alternative moves correspond to the current cursor:
        - If cursor > 0 and the parent of the move at `cursor` (`_get_tree_node_at_ply(cursor - 1)`) has >1 children,
          that parent holds the alternative moves for the move currently displayed on the board (e.g., move 10: Nf3, Bd3, Rb1).
        - Otherwise, if the node AT `cursor` (`_get_tree_node_at_ply(cursor)`) has >1 children (i.e. the NEXT move has variations),
          return that node.
        """
        if self._cursor > 0:
            parent_of_current = self._get_tree_node_at_ply(self._cursor - 1)
            if len(parent_of_current.children) > 1:
                return parent_of_current
        node_at_cursor = self._get_tree_node_at_ply(self._cursor)
        if len(node_at_cursor.children) > 1:
            return node_at_cursor
        if self._cursor > 0:
            return self._get_tree_node_at_ply(self._cursor - 1)
        return self._root

    def get_variations_at_current_move(self) -> Dict[str, Any]:
        """
        Return variation metadata specifically for the current move on the board:
        {
            "total_branches": int,         # 1 = only main line at this move; 3 = Main + 2 variations
            "variation_count": int,        # number of alternative variations (total_branches - 1)
            "active_index": int,           # 0 = main branch at this move, 1 = Var 1, 2 = Var 2
            "branch_San_list": List[str],  # e.g. ["10.Nf3", "10.Bd3", "10.Rb1"]
            "button_label": str,           # e.g. "Main + 2 Vars (10.Nf3)" or "Var 1/2 (10.Bd3)"
        }
        """
        parent = self._get_decision_parent_for_cursor()
        children = parent.children
        total = len(children)
        if total <= 1:
            return {
                "total_branches": total,
                "variation_count": 0,
                "active_index": 0,
                "branch_san_list": [c.move.san for c in children if c.move],
                "button_label": "No Vars Here",
            }

        act_idx = max(0, min(parent.active_child_idx, total - 1))
        san_list: List[str] = []
        for c in children:
            if c.move:
                p = f"{c.move.fullmove_number}." if c.move.turn_before == "white" else f"{c.move.fullmove_number}..."
                san_list.append(f"{p}{c.move.san}")
        curr_san = san_list[act_idx] if act_idx < len(san_list) else ""
        var_count = total - 1
        if act_idx == 0:
            btn_lbl = f"Main+{var_count}Var ({curr_san})"
        else:
            btn_lbl = f"Var {act_idx}/{var_count} ({curr_san})"

        return {
            "total_branches": total,
            "variation_count": var_count,
            "active_index": act_idx,
            "branch_san_list": san_list,
            "button_label": btn_lbl,
        }

    def cycle_variation_at_current_move(self) -> Optional[MoveVariant]:
        """
        Cycle strictly among the branches (Mainline + variations) at the CURRENT move!
        For example, if move 10 has Nf3 (Main), Bd3 (Var 1), and Rb1 (Var 2), cycling at move 10
        switches Nf3 -> Bd3 -> Rb1 -> Nf3 without jumping to unrelated variations at move 20.
        """
        parent = self._get_decision_parent_for_cursor()
        if len(parent.children) <= 1:
            return None

        # Determine the ply of the decision move
        path = self._get_active_tree_path()
        if parent is self._root:
            decision_ply = 1
        else:
            try:
                decision_ply = path.index(parent) + 2
            except ValueError:
                decision_ply = self._cursor

        parent.active_child_idx = (parent.active_child_idx + 1) % len(parent.children)
        new_path = self._get_active_tree_path()
        self._cursor = min(max(1, decision_ply), len(new_path))
        return self.active_variant

    def cycle_active_line(self) -> Optional[MoveVariant]:
        """Alias for cycling variations at the current move (or first available branch point)."""
        parent = self._get_decision_parent_for_cursor()
        if len(parent.children) > 1:
            return self.cycle_variation_at_current_move()
        # If current move has no variations, find the nearest node on the path with variations
        curr = self._root
        ply_idx = 0
        while curr.children:
            if len(curr.children) > 1:
                curr.active_child_idx = (curr.active_child_idx + 1) % len(curr.children)
                self._cursor = min(ply_idx + 1, len(self._get_active_tree_path()))
                return self.active_variant
            curr = curr.children[curr.active_child_idx]
            ply_idx += 1
        return None

    def switch_to_mainline(self, restore_branch_cursor: bool = True) -> int:
        """Reset all active_child_idx along the tree back to 0 (the primary Mainline)."""
        # Find first divergence ply so cursor stays at the branch point
        branch_ply: Optional[int] = None
        curr = self._root
        ply_count = 0
        while curr.children:
            if curr.active_child_idx != 0 and branch_ply is None:
                branch_ply = ply_count
            nxt = curr.children[curr.active_child_idx]
            curr.active_child_idx = 0
            curr = nxt
            ply_count += 1

        def _reset_all(node: MoveTreeNode) -> None:
            node.active_child_idx = 0
            for c in node.children:
                _reset_all(c)

        _reset_all(self._root)
        main_len = len(self._get_mainline_tree_path())
        if restore_branch_cursor and branch_ply is not None:
            self._cursor = min(branch_ply, main_len)
        else:
            self._cursor = min(self._cursor, main_len)
        return self._cursor

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def total_plies(self) -> int:
        return len(self.nodes)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def current_node(self) -> Optional[MoveNode]:
        active = self.nodes
        if self._cursor == 0 or not active:
            return None
        return active[min(self._cursor, len(active)) - 1]

    @property
    def current_fen(self) -> str:
        node = self.current_node
        return node.fen_after if node is not None else self._initial_fen

    def get_board_at_cursor(self) -> chess.Board:
        active = self.nodes
        board = chess.Board(self._initial_fen)
        for idx in range(min(self._cursor, len(active))):
            board.push(chess.Move.from_uci(active[idx].uci))
        return board

    def get_uci_moves_to_cursor(self) -> List[str]:
        active = self.nodes
        return [n.uci for n in active[: self._cursor]]

    def get_all_uci_moves(self) -> List[str]:
        return [n.uci for n in self.nodes]

    def record_move(
        self,
        move: chess.Move,
        comment: str = "",
        create_variant_on_branch: bool = True,
    ) -> MoveNode:
        """
        Record a legal move at the current cursor position in the variation tree:
        - If the parent node at `cursor` already has a child with `move.uci()`, switches `active_child_idx`
          to that child and advances `cursor` by 1!
        - If the parent node at `cursor` has no children yet (we are at the tip of the current line/variation),
          appends the move as `children[0]` of that node!
        - If the parent node at `cursor` already has `children` (there are moves ahead in the current line/variation),
          adds the new move as a new sibling branch `children.append(...)` at that exact node and selects it!
        """
        board = self.get_board_at_cursor()
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move {move.uci()} in position {board.fen()}")

        parent_tree_node = self._get_tree_node_at_ply(self._cursor)

        # 1. Check if this exact move already exists among parent_tree_node.children
        for idx, existing_child in enumerate(parent_tree_node.children):
            if existing_child.move is not None and existing_child.move.uci == move.uci():
                parent_tree_node.active_child_idx = idx
                self._cursor += 1
                assert existing_child.move is not None
                return existing_child.move

        # 2. Construct the MoveNode
        fen_before = board.fen()
        turn_before = "white" if board.turn == chess.WHITE else "black"
        fullmove_num = board.fullmove_number
        san = board.san(move)
        is_capture = board.is_capture(move)
        is_castling = board.is_castling(move)
        is_ep = board.is_en_passant(move)
        promo_symbol = chess.piece_symbol(move.promotion) if move.promotion else None

        board.push(move)
        fen_after = board.fen()
        is_check = board.is_check()
        is_checkmate = board.is_checkmate()

        node = MoveNode(
            ply=self._cursor + 1,
            uci=move.uci(),
            san=san,
            fen_before=fen_before,
            fen_after=fen_after,
            turn_before=turn_before,
            fullmove_number=fullmove_num,
            is_capture=is_capture,
            is_check=is_check,
            is_checkmate=is_checkmate,
            is_castling=is_castling,
            is_en_passant=is_ep,
            promotion=promo_symbol,
            comment=comment,
        )

        was_in_variant_before = self.is_in_variant
        if parent_tree_node.children and not create_variant_on_branch:
            parent_tree_node.children.clear()

        new_tree_node = MoveTreeNode(move=node, parent=parent_tree_node)
        parent_tree_node.children.append(new_tree_node)
        parent_tree_node.active_child_idx = len(parent_tree_node.children) - 1
        self._cursor += 1
        self._redo_stack.clear()

        # Only increment mainline revision if we extended the primary mainline (not a side variation)
        if not was_in_variant_before and parent_tree_node.active_child_idx == 0:
            self._revision += 1
        return node

    def can_undo(self) -> bool:
        return self._cursor > 0 and len(self.nodes) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0 and self._cursor == len(self.nodes)

    def undo(self) -> Optional[MoveNode]:
        if self._cursor <= 0:
            return None
        target_tree_node = self._get_tree_node_at_ply(self._cursor)
        parent = target_tree_node.parent
        if parent is None or target_tree_node.move is None:
            return None

        removed = target_tree_node.move
        was_mainline = not self.is_in_variant

        # If target_tree_node is a leaf at the tip of the active branch, remove it and push to redo_stack
        if not target_tree_node.children:
            idx = parent.children.index(target_tree_node)
            parent.children.pop(idx)
            parent.active_child_idx = max(0, min(parent.active_child_idx, len(parent.children) - 1))
            self._redo_stack.append(removed)
            self._cursor -= 1
            if was_mainline and idx == 0:
                self._revision += 1
            return removed

        # If undoing from mid-line on the mainline, pop from tip or step back
        self._cursor -= 1
        return removed

    def redo(self) -> Optional[MoveNode]:
        if not self.can_redo():
            return None
        node = self._redo_stack.pop()
        return self.record_move(chess.Move.from_uci(node.uci), comment=node.comment)

    def go_to_first(self) -> int:
        self._cursor = 0
        return self._cursor

    def go_to_previous(self) -> int:
        if self._cursor > 0:
            self._cursor -= 1
        return self._cursor

    def go_to_next(self) -> int:
        active = self.nodes
        if self._cursor < len(active):
            self._cursor += 1
        return self._cursor

    def go_to_last(self) -> int:
        self._cursor = len(self.nodes)
        return self._cursor

    def go_to_ply(self, ply: int) -> int:
        active = self.nodes
        if ply < 0 or ply > len(active):
            raise ValueError(f"Ply {ply} out of range [0, {len(active)}]")
        self._cursor = ply
        return self._cursor

    def to_tree_json(self) -> str:
        """Serialize the entire recursive variation tree to JSON."""
        return json.dumps(self._root.to_dict())

    def load_tree_json(self, tree_json: str) -> None:
        """Restore the entire recursive variation tree from JSON."""
        data = json.loads(tree_json)
        self._root = MoveTreeNode.from_dict(data, parent=None)
        self._cursor = min(self._cursor, len(self.nodes))

    def format_move_pairs(self) -> List[Dict[str, Optional[MoveNode]]]:
        active = self.nodes
        rows: List[Dict[str, Optional[MoveNode]]] = []
        current_row: Optional[Dict[str, Optional[MoveNode]]] = None
        for node in active:
            if node.turn_before == "white":
                current_row = {
                    "move_number": node.fullmove_number,
                    "white": node,
                    "black": None,
                }
                rows.append(current_row)
            else:
                if current_row is None or current_row["black"] is not None:
                    current_row = {
                        "move_number": node.fullmove_number,
                        "white": None,
                        "black": node,
                    }
                    rows.append(current_row)
                else:
                    current_row["black"] = node
        return rows

    def to_pgn(self, headers: Optional[Dict[str, str]] = None, result: Optional[str] = None) -> str:
        """Serialize the initial position and the entire recursive variation tree to standard PGN."""
        game = chess.pgn.Game()
        board = chess.Board(self._initial_fen)
        if self._initial_fen != chess.STARTING_FEN:
            game.setup(board)

        if headers:
            for k, v in headers.items():
                if v is not None:
                    game.headers[k] = str(v)

        def _populate_pgn(tree_node: MoveTreeNode, pgn_node: chess.pgn.GameNode) -> None:
            for child in tree_node.children:
                if child.move is not None:
                    mv = chess.Move.from_uci(child.move.uci)
                    sub_pgn = pgn_node.add_variation(mv, comment=child.move.comment or "")
                    _populate_pgn(child, sub_pgn)

        _populate_pgn(self._root, game)

        if result:
            game.headers["Result"] = result
        elif "Result" not in game.headers:
            final_board = self.get_board_at_ply(len(self.mainline_nodes))
            game.headers["Result"] = final_board.result(claim_draw=False)

        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        return game.accept(exporter).strip()

    def get_board_at_ply(self, ply: int) -> chess.Board:
        active = self.nodes
        if ply < 0 or ply > len(active):
            raise ValueError(f"Ply {ply} out of bounds")
        board = chess.Board(self._initial_fen)
        for idx in range(ply):
            board.push(chess.Move.from_uci(active[idx].uci))
        return board
