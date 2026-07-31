import sqlite3
from pathlib import Path

db_path = Path(__file__).parent / "conversations.db"
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

print("=== 会话统计 ===")
cur = conn.execute("SELECT COUNT(*) as count FROM sessions")
session_count = cur.fetchone()['count']
print(f"总会话数: {session_count}")

cur = conn.execute("SELECT COUNT(*) as count FROM messages")
message_count = cur.fetchone()['count']
print(f"总消息数: {message_count}")

print(f"\n=== 最近10个会话 ===")
cur = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 10")
for row in cur.fetchall():
    print(f"ID: {row['id']}, 标题: {row['title']}, 创建时间: {row['created_at']}")

print(f"\n=== 最近10条消息 ===")
cur = conn.execute("SELECT * FROM messages ORDER BY timestamp DESC LIMIT 10")
for row in cur.fetchall():
    print(f"会话ID: {row['session_id']}, 角色: {row['role']}, 时间: {row['timestamp']}")
    print(f"内容: {row['content'][:80]}...")
    print("-" * 50)

conn.close()