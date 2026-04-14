import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 加载 .env 配置文件
load_dotenv()

DB_FILE = "bot.db"

def init_db():
    """初始化数据库表结构"""
    with sqlite3.connect(DB_FILE) as conn:
        # 1. 存储 token 等全局设置
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        # 2. 存储用户基础信息（如需扩展积分系统可用）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS users "
            "(user_id TEXT PRIMARY KEY, points INTEGER DEFAULT 0)"
        )
        # 3. 核心表：存储每一张生成的图片信息及点赞数
        conn.execute(
            "CREATE TABLE IF NOT EXISTS generations "
            "(message_id TEXT PRIMARY KEY, user_id TEXT, channel TEXT, "
            "prompt TEXT, created_at TEXT, reactions INTEGER DEFAULT 0, "
            "bonus_awarded INTEGER DEFAULT 0)"
        )
    print("✅ Database initialized.")

# ── Token 管理逻辑 ──

def get_token():
    """获取百度 API Token：优先从环境变量读取，其次从数据库读取"""
    # 优先读取 .env 中的 BAIDU_TOKEN
    env_token = os.getenv("BAIDU_TOKEN")
    if env_token:
        return env_token
    
    # 备选：从数据库 settings 表读取
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='token'").fetchone()
        return row[0] if row else None

def set_token(token: str):
    """将 Token 写入数据库（作为 .env 的备选或补充）"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('token', ?)", (token,))

# ── 用户记录 ──

def ensure_user(uid: str):
    """确保用户存在于数据库中"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))

# ── 生成记录与点赞追踪 ──

def add_generation(message_id: str, uid: str, channel: str, prompt: str):
    """记录一次新的图片生成活动"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO generations (message_id, user_id, channel, prompt, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, uid, channel, prompt, datetime.utcnow().isoformat()),
        )

def get_generation(message_id: str):
    """根据消息 ID 获取生成详情（用于 Reaction 监听）"""
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute(
            "SELECT user_id, channel, bonus_awarded FROM generations WHERE message_id=?",
            (message_id,),
        ).fetchone()

def update_reactions(message_id: str, count: int):
    """更新某张图片收到的点赞数量"""
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "UPDATE generations SET reactions = ? WHERE message_id = ?", 
            (count, message_id)
        )

# ── 动态排行榜查询 (核心) ──

def get_dynamic_gallery(limit: int = 10):
    """
    动态获取 Top 10 作品：
    1. 优先尝试获取本周（周一 00:00 至今）在 #ernie-image 频道的数据。
    2. 如果本周没有数据，则返回全时段最高点赞的数据。
    """
    now = datetime.utcnow()
    # 计算本周一 00:00:00 的 ISO 时间戳
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    monday_str = monday.isoformat()

    with sqlite3.connect(DB_FILE) as conn:
        # 1. 尝试查询本周数据
        current_week = conn.execute(
            "SELECT user_id, prompt, reactions FROM generations "
            "WHERE channel='ernie-image' AND created_at >= ? "
            "ORDER BY reactions DESC LIMIT ?",
            (monday_str, limit),
        ).fetchall()
        
        if current_week and any(row[2] > 0 for row in current_week):
            return current_week, "Current Week (In Progress)"

        # 2. 兜底：查询全时段数据（Hall of Fame）
        all_time = conn.execute(
            "SELECT user_id, prompt, reactions FROM generations "
            "WHERE channel='ernie-image' "
            "ORDER BY reactions DESC LIMIT ?",
            (limit,),
        ).fetchall()
        
        if all_time:
            return all_time, "All-Time Hall of Fame"
        
        return [], "No Data"

# ── 积分/检查逻辑 (保留作为可选功能) ──

def add_points(uid: str, pts: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (pts, uid))

def has_daily_checkin(uid: str) -> bool:
    """检查用户今天是否已经在 #ernie-image 发过图"""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT 1 FROM generations WHERE user_id=? AND channel='ernie-image' "
            "AND created_at LIKE ?",
            (uid, f"{today_str}%"),
        ).fetchone()
        return row is not None