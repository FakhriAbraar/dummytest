from __future__ import annotations
from typing import Any
from app.db.mongo import get_mongo_db

# Memasukkan SATU data
async def insert_one_data(*, collection_name: str, data: dict[str, Any]) -> dict[str, Any]:
    db = get_mongo_db()
    result = await db[collection_name].insert_one(data)
    return {
        "status": "success",
        "id": str(result.inserted_id)
    }

# Memasukkan BANYAK data (Array of Dictionary)
async def insert_many_data(*, collection_name: str, data_list: list[dict[str, Any]]) -> dict[str, Any]:
    db = get_mongo_db()
    result = await db[collection_name].insert_many(data_list)
    return {
        "status": "success",
        "ids": [str(i) for i in result.inserted_ids],
        "count": len(result.inserted_ids)
    }
