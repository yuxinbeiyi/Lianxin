import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "conversations.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

print("=== 会话表 sessions ===")
cur = conn.execute("SELECT * FROM sessions")
for row in cur.fetchall():
    print(f"ID: {row['id']}, 标题: {row['title']}, 创建时间: {row['created_at']}")

print("\n=== 消息表 messages ===")
cur = conn.execute("SELECT * FROM messages")
for row in cur.fetchall():
    print(f"ID: {row['id']}, 会话ID: {row['session_id']}, 角色: {row['role']}, 时间: {row['timestamp']}")
    print(f"内容: {row['content'][:50]}...")
    print("-" * 50)

conn.close()