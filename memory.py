"""用户记忆：SQLite 存每人简短画像（称呼、喜好、注意事项），对话时注入 prompt"""
import sqlite3
import threading
import datetime
import os
import config

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.db")
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

MAX_PER_USER = 20  # 每人最多保留条数，超出淘汰最旧的


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                fact TEXT,
                ts TEXT
            )"""
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id)")
        _conn.commit()
    return _conn


def add(user_id: str, fact: str) -> bool:
    """为某用户添加一条记忆；同一用户重复内容不重复存"""
    fact = (fact or "").strip()[:200]
    if not fact:
        return False
    try:
        with _lock:
            conn = _get_conn()
            dup = conn.execute(
                "SELECT 1 FROM memories WHERE user_id=? AND fact=? LIMIT 1",
                (str(user_id), fact),
            ).fetchone()
            if dup:
                return False
            conn.execute(
                "INSERT INTO memories (user_id, fact, ts) VALUES (?,?,?)",
                (str(user_id), fact,
                 datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            # 超出上限时删除最旧的
            conn.execute(
                "DELETE FROM memories WHERE user_id=? AND id NOT IN "
                "(SELECT id FROM memories WHERE user_id=? ORDER BY id DESC LIMIT ?)",
                (str(user_id), str(user_id), MAX_PER_USER),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"[error] 记忆写入失败: {e}")
        return False


def get(user_id: str) -> list[str]:
    """取某用户的记忆列表（新→旧）"""
    try:
        with _lock:
            rows = _get_conn().execute(
                "SELECT fact FROM memories WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (str(user_id), MAX_PER_USER),
            ).fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[error] 记忆查询失败: {e}")
        return []


def clear(user_id: str | None = None) -> int:
    """清空某用户（或全部）记忆，返回删除条数"""
    try:
        with _lock:
            conn = _get_conn()
            if user_id:
                cur = conn.execute("DELETE FROM memories WHERE user_id=?", (str(user_id),))
            else:
                cur = conn.execute("DELETE FROM memories")
            conn.commit()
            return cur.rowcount
    except Exception as e:
        print(f"[error] 记忆清除失败: {e}")
        return 0


def inject(user_id: str) -> str:
    """把用户记忆整理成注入 system_prompt 的文本段，无记忆时返回空串"""
    facts = get(user_id)
    if not facts:
        return ""
    return "\n以下是你对这位用户的长期记忆（称呼、偏好等，自然使用，不要罗列）：" \
           + "".join(f"\n- {f}" for f in facts)
