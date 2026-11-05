import json
import time
from pathlib import Path

import aiosqlite

DB_PATH = Path("cache.sqlite")
TTL = 24 * 3600


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL,
                   expires_at REAL NOT NULL
               )"""
        )
        await db.commit()


async def cache_get(key: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value, expires_at FROM cache WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    value, exp = row
    if time.time() > exp:
        return None
    return json.loads(value)


async def cache_set(key: str, value: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO cache(key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), time.time() + TTL),
        )
        await db.commit()