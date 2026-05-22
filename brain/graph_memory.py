"""
五元组知识图谱记忆存储 — SQLite 图结构（零额外依赖）。

与现有的 6 分类 JSON 记忆并行运作：
- JSON 记忆：独立事实/偏好
- 图记忆：实体间的关系（主体, 主体类型, 关系, 客体, 客体类型）

两张表存在于 memory/conversations.db 中。
"""

import sqlite3
import threading
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "memory" / "conversations.db"
_local = threading.local()

ENTITY_TYPES = ("人物", "地点", "组织", "物品", "概念", "时间", "事件", "活动", "技术", "文件")


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("PRAGMA synchronous=NORMAL")
        _init_tables(conn)
        _local.conn = conn
    return _local.conn


def _init_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS graph_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(name, entity_type)
        );
        CREATE TABLE IF NOT EXISTS graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            head_id INTEGER NOT NULL,
            head_type TEXT NOT NULL,
            relation TEXT NOT NULL,
            tail_id INTEGER NOT NULL,
            tail_type TEXT NOT NULL,
            source TEXT DEFAULT 'auto',
            strength INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY(head_id) REFERENCES graph_entities(id),
            FOREIGN KEY(tail_id) REFERENCES graph_entities(id),
            UNIQUE(head_id, relation, tail_id)
        );
        CREATE INDEX IF NOT EXISTS idx_graph_entities_name ON graph_entities(name);
        CREATE INDEX IF NOT EXISTS idx_graph_entities_type ON graph_entities(entity_type);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_head ON graph_edges(head_id);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_tail ON graph_edges(tail_id);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_relation ON graph_edges(relation);
    """)


def _get_or_create_entity(conn: sqlite3.Connection, name: str, entity_type: str) -> int:
    name = name.strip()
    entity_type = entity_type.strip()
    row = conn.execute(
        "SELECT id FROM graph_entities WHERE name=? AND entity_type=?",
        (name, entity_type)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO graph_entities(name, entity_type) VALUES (?, ?)",
        (name, entity_type)
    )
    return cur.lastrowid


def store_quintuple(head: str, head_type: str, relation: str,
                    tail: str, tail_type: str, source: str = "auto") -> bool:
    """写入一条五元组记忆。实体自动 merge，关系重复则 strength+1。返回是否新增。"""
    head = head.strip()
    tail = tail.strip()
    relation = relation.strip()
    if not head or not tail or not relation:
        return False
    if head_type not in ENTITY_TYPES:
        head_type = "概念"
    if tail_type not in ENTITY_TYPES:
        tail_type = "概念"

    conn = _get_conn()
    hid = _get_or_create_entity(conn, head, head_type)
    tid = _get_or_create_entity(conn, tail, tail_type)

    cur = conn.execute(
        """INSERT INTO graph_edges(head_id, head_type, relation, tail_id, tail_type, source)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(head_id, relation, tail_id) DO UPDATE SET strength = strength + 1""",
        (hid, head_type, relation, tid, tail_type, source)
    )
    conn.commit()
    return cur.lastrowid is not None and cur.rowcount > 0


def query_by_entity(keyword: str, entity_type: str = None) -> list[dict]:
    """按实体名模糊搜索，返回该实体的所有关联边。"""
    conn = _get_conn()
    q = "%" + keyword.strip() + "%"
    if entity_type:
        rows = conn.execute("""
            SELECT h.name AS head, e.head_type, e.relation,
                   t.name AS tail, e.tail_type, e.source, e.strength
            FROM graph_edges e
            JOIN graph_entities h ON e.head_id = h.id
            JOIN graph_entities t ON e.tail_id = t.id
            WHERE (h.name LIKE ? OR t.name LIKE ?) AND (h.entity_type=? OR t.entity_type=?)
            ORDER BY e.strength DESC
            LIMIT 30
        """, (q, q, entity_type, entity_type)).fetchall()
    else:
        rows = conn.execute("""
            SELECT h.name AS head, e.head_type, e.relation,
                   t.name AS tail, e.tail_type, e.source, e.strength
            FROM graph_edges e
            JOIN graph_entities h ON e.head_id = h.id
            JOIN graph_entities t ON e.tail_id = t.id
            WHERE h.name LIKE ? OR t.name LIKE ?
            ORDER BY e.strength DESC
            LIMIT 30
        """, (q, q)).fetchall()
    return [dict(r) for r in rows]


def query_by_relation(relation_keyword: str, head_type: str = None,
                     tail_type: str = None) -> list[dict]:
    """按关系关键词搜索，可选过滤头尾实体类型。"""
    conn = _get_conn()
    q = "%" + relation_keyword.strip() + "%"
    sql = """
        SELECT h.name AS head, e.head_type, e.relation,
               t.name AS tail, e.tail_type, e.source, e.strength
        FROM graph_edges e
        JOIN graph_entities h ON e.head_id = h.id
        JOIN graph_entities t ON e.tail_id = t.id
        WHERE e.relation LIKE ?
    """
    params = [q]
    if head_type:
        sql += " AND e.head_type = ?"
        params.append(head_type)
    if tail_type:
        sql += " AND e.tail_type = ?"
        params.append(tail_type)
    sql += " ORDER BY e.strength DESC LIMIT 30"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_connected(entity_name: str, depth: int = 1) -> list[dict]:
    """BFS 多跳遍历，找到与指定实体间接关联的实体和路径。"""
    if depth > 3:
        depth = 3  # 安全上限

    conn = _get_conn()
    # 先找到起始实体
    start_rows = conn.execute(
        "SELECT id, name, entity_type FROM graph_entities WHERE name LIKE ? LIMIT 3",
        ("%" + entity_name.strip() + "%",)
    ).fetchall()
    if not start_rows:
        return []

    results = []
    visited = set()

    for start in start_rows:
        current_ids = {start["id"]}
        # 第 0 跳：直接关联边
        direct_rows = conn.execute("""
            SELECT h.name AS head, e.head_type, e.relation,
                   t.name AS tail, e.tail_type, e.strength
            FROM graph_edges e
            JOIN graph_entities h ON e.head_id = h.id
            JOIN graph_entities t ON e.tail_id = t.id
            WHERE e.head_id = ? OR e.tail_id = ?
            ORDER BY e.strength DESC LIMIT 20
        """, (start["id"], start["id"])).fetchall()

        for r in direct_rows:
            key = (r["head"], r["relation"], r["tail"])
            if key not in visited:
                visited.add(key)
                results.append(dict(r))
                current_ids.add(conn.execute(
                    "SELECT id FROM graph_entities WHERE name=?",
                    (r["head"],)
                ).fetchone()["id"])
                current_ids.add(conn.execute(
                    "SELECT id FROM graph_entities WHERE name=?",
                    (r["tail"],)
                ).fetchone()["id"])

        # 第 N 跳
        for _ in range(1, depth):
            if not current_ids:
                break
            placeholders = ",".join("?" * len(current_ids))
            next_rows = conn.execute(f"""
                SELECT h.name AS head, e.head_type, e.relation,
                       t.name AS tail, e.tail_type, e.strength
                FROM graph_edges e
                JOIN graph_entities h ON e.head_id = h.id
                JOIN graph_entities t ON e.tail_id = t.id
                WHERE e.head_id IN ({placeholders}) OR e.tail_id IN ({placeholders})
                ORDER BY e.strength DESC LIMIT 30
            """, list(current_ids) + list(current_ids)).fetchall()

            new_ids = set()
            for r in next_rows:
                key = (r["head"], r["relation"], r["tail"])
                if key not in visited:
                    visited.add(key)
                    results.append(dict(r))
            if not new_ids:
                break
            current_ids = new_ids

    return results


def search_graph(keywords: list[str]) -> list[dict]:
    """综合搜索：匹配实体名 + 关系名。"""
    if isinstance(keywords, str):
        keywords = [keywords]
    if not keywords:
        return []

    conn = _get_conn()
    results = []
    seen = set()

    for kw in keywords:
        q = "%" + kw.strip() + "%"
        rows = conn.execute("""
            SELECT h.name AS head, e.head_type, e.relation,
                   t.name AS tail, e.tail_type, e.source, e.strength
            FROM graph_edges e
            JOIN graph_entities h ON e.head_id = h.id
            JOIN graph_entities t ON e.tail_id = t.id
            WHERE h.name LIKE ? OR t.name LIKE ? OR e.relation LIKE ?
            ORDER BY e.strength DESC LIMIT 10
        """, (q, q, q)).fetchall()

        for r in rows:
            key = (r["head"], r["relation"], r["tail"])
            if key not in seen:
                seen.add(key)
                results.append(dict(r))

    return results[:50]


def format_graph_result(rows: list[dict]) -> str:
    """将图查询结果格式化为 LLM 可读文本。"""
    if not rows:
        return "图记忆中未找到相关信息。"

    lines = [f"找到 {len(rows)} 条关联记忆："]
    for i, r in enumerate(rows, 1):
        src = "自动" if r.get("source", "auto") == "auto" else "手动"
        strength = r.get("strength", 1)
        lines.append(
            f"{i}. ({r['head']}, {r['head_type']}) "
            f"—[{r['relation']}]→ "
            f"({r['tail']}, {r['tail_type']}) "
            f"[强度:{strength}, {src}]"
        )
    return "\n".join(lines)


def get_graph_stats() -> dict:
    """获取图统计信息。"""
    conn = _get_conn()
    entity_count = conn.execute("SELECT COUNT(*) FROM graph_entities").fetchone()[0]
    edge_count = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
    top_relations = conn.execute("""
        SELECT relation, COUNT(*) AS cnt FROM graph_edges
        GROUP BY relation ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    top_entities = conn.execute("""
        SELECT name, entity_type FROM graph_entities
        ORDER BY id DESC LIMIT 10
    """).fetchall()
    return {
        "entity_count": entity_count,
        "edge_count": edge_count,
        "top_relations": [(r["relation"], r["cnt"]) for r in top_relations],
        "recent_entities": [(r["name"], r["entity_type"]) for r in top_entities],
    }


def delete_entity(name: str) -> int:
    """删除实体及其所有关联边。返回删除的边数。"""
    conn = _get_conn()
    entity_rows = conn.execute(
        "SELECT id FROM graph_entities WHERE name=?",
        (name.strip(),)
    ).fetchall()
    if not entity_rows:
        return 0
    ids = [r["id"] for r in entity_rows]
    placeholders = ",".join("?" * len(ids))
    cur = conn.execute(
        f"DELETE FROM graph_edges WHERE head_id IN ({placeholders}) OR tail_id IN ({placeholders})",
        ids + ids
    )
    edge_count = cur.rowcount
    conn.execute(f"DELETE FROM graph_entities WHERE id IN ({placeholders})", ids)
    conn.commit()
    return edge_count
