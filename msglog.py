"""消息日志：SQLite 存储收发的每条消息，供 WebUI 查询"""
import sqlite3
import threading
import datetime
import os
import config

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.db")
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                chat_type TEXT,
                chat_id TEXT,
                user_id TEXT,
                direction TEXT,
                content TEXT
            )"""
        )
        _conn.commit()
    return _conn


def _enabled() -> bool:
    return bool(config.load().get("message_log_enabled", True))


def log_message(chat_type: str, chat_id, user_id, direction: str, content: str):
    """direction: 'in' 收到 / 'out' 发出"""
    if not _enabled():
        return
    try:
        with _lock:
            _get_conn().execute(
                "INSERT INTO messages (ts, chat_type, chat_id, user_id, direction, content) "
                "VALUES (?,?,?,?,?,?)",
                (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 chat_type, str(chat_id), str(user_id), direction, content[:2000]),
            )
            _get_conn().commit()
    except Exception as e:
        print(f"[error] 消息日志写入失败: {e}")


def query(limit: int = 100, chat_id: str | None = None) -> list[dict]:
    """倒序查询最近消息，可按会话过滤"""
    try:
        with _lock:
            conn = _get_conn()
            if chat_id:
                rows = conn.execute(
                    "SELECT ts, chat_type, chat_id, user_id, direction, content "
                    "FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                    (str(chat_id), int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT ts, chat_type, chat_id, user_id, direction, content "
                    "FROM messages ORDER BY id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        return [
            {"ts": r[0], "chat_type": r[1], "chat_id": r[2],
             "user_id": r[3], "direction": r[4], "content": r[5]}
            for r in rows
        ]
    except Exception as e:
        print(f"[error] 消息日志查询失败: {e}")
        return []


def stats(days: int = 7) -> dict:
    """近 N 天统计：收发条数、活跃会话数"""
    try:
        since = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with _lock:
            conn = _get_conn()
            total_in = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE direction='in' AND ts>=?", (since,)
            ).fetchone()[0]
            total_out = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE direction='out' AND ts>=?", (since,)
            ).fetchone()[0]
            chats = conn.execute(
                "SELECT COUNT(DISTINCT chat_id) FROM messages WHERE ts>=?", (since,)
            ).fetchone()[0]
        return {"in": total_in, "out": total_out, "chats": chats, "days": days}
    except Exception:
        return {"in": 0, "out": 0, "chats": 0, "days": days}
