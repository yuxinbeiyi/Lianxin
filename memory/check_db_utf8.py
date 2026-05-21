import sqlite3
import sys
from pathlib import Path

# 设置控制台编码为UTF-8
sys.stdout.reconfigure(encoding='utf-8')

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

print(f"\n=== 消息类型统计 ===")
cur = conn.execute("SELECT role, COUNT(*) as count FROM messages GROUP BY role")
for row in cur.fetchall():
    print(f"{row['role']}: {row['count']} 条")

print(f"\n=== 最近5个会话 ===")
cur = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 5")
for row in cur.fetchall():
    print(f"ID: {row['id']}, 标题: {row['title']}, 创建时间: {row['created_at']}")

print(f"\n=== 数据库大小 ===")
import os
db_size = os.path.getsize(db_path)
print(f"conversations.db 文件大小: {db_size:,} 字节 ({db_size/1024:.1f} KB)")

conn.close()