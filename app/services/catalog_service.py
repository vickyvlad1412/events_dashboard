import re
import unicodedata

from app.db import get_connection


def upsert_entities(category_name: str, entity_type: str, entities: list[dict], mark_active: bool = False) -> None:
    if not entities:
        return
    with get_connection() as conn:
        category = conn.execute("SELECT id FROM categories WHERE name = ?", (category_name,)).fetchone()
        conn.executemany(
            """
            INSERT INTO catalog_entities
                (category_id, entity_type, external_id, name, short_name, detail, image_url, is_active)
            VALUES (:category_id, :entity_type, :external_id, :name, :short_name, :detail, :image_url, :is_active)
            ON CONFLICT(category_id, entity_type, external_id) DO UPDATE SET
                name = excluded.name,
                short_name = COALESCE(excluded.short_name, catalog_entities.short_name),
                detail = COALESCE(excluded.detail, catalog_entities.detail),
                image_url = COALESCE(excluded.image_url, catalog_entities.image_url),
                is_active = MAX(catalog_entities.is_active, excluded.is_active),
                updated_at = datetime('now')
            """,
            [
                {
                    "category_id": category["id"],
                    "entity_type": entity_type,
                    "external_id": str(entity["external_id"]),
                    "name": entity["name"],
                    "short_name": entity.get("short_name"),
                    "detail": entity.get("detail"),
                    "image_url": entity.get("image_url"),
                    "is_active": 1 if mark_active else 0,
                }
                for entity in entities
                if entity.get("name") and entity.get("external_id") is not None
            ],
        )


def mark_active(category_name: str, entity_type: str, names: set[str]) -> None:
    if not names:
        return
    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE catalog_entities SET is_active = 1
            WHERE entity_type = ? AND (name = ? COLLATE NOCASE OR short_name = ? COLLATE NOCASE)
              AND category_id = (SELECT id FROM categories WHERE name = ?)
            """,
            [(entity_type, name, name, category_name) for name in names],
        )


def count(category_name: str, entity_type: str) -> int:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT COUNT(*) FROM catalog_entities
            JOIN categories ON categories.id = catalog_entities.category_id
            WHERE categories.name = ? AND catalog_entities.entity_type = ?
            """,
            (category_name, entity_type),
        ).fetchone()[0]


def get_entity(category_name: str, entity_type: str, external_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT catalog_entities.* FROM catalog_entities
            JOIN categories ON categories.id = catalog_entities.category_id
            WHERE categories.name = ? AND catalog_entities.entity_type = ? AND catalog_entities.external_id = ?
            """,
            (category_name, entity_type, str(external_id)),
        ).fetchone()
        return dict(row) if row else None


def search(category_name: str, entity_type: str, query: str, limit: int = 8) -> list[dict]:
    wanted = normalize(query)
    if len(wanted) < 2:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT catalog_entities.* FROM catalog_entities
            JOIN categories ON categories.id = catalog_entities.category_id
            WHERE categories.name = ? AND catalog_entities.entity_type = ?
              AND (catalog_entities.name LIKE ? OR catalog_entities.short_name LIKE ?)
            """,
            (category_name, entity_type, f"%{query.strip()}%", f"%{query.strip()}%"),
        ).fetchall()
        candidates = [dict(row) for row in rows]
        if not candidates:
            candidates = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT catalog_entities.* FROM catalog_entities
                    JOIN categories ON categories.id = catalog_entities.category_id
                    WHERE categories.name = ? AND catalog_entities.entity_type = ?
                    """,
                    (category_name, entity_type),
                ).fetchall()
            ]

    scored = [(score, entity) for entity in candidates if (score := _score(entity, wanted)) > 0]
    scored.sort(key=lambda item: (-item[0], -item[1]["is_active"], len(item[1]["name"]), item[1]["name"]))
    return [entity for _, entity in scored[:limit]]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _score(entity: dict, wanted: str) -> int:
    best = 0
    wanted_tokens = wanted.split()
    for candidate in (entity["name"], entity.get("short_name") or ""):
        normalized = normalize(candidate)
        if not normalized:
            continue
        tokens = normalized.split()
        if normalized == wanted:
            best = max(best, 100)
        elif normalized.startswith(wanted):
            best = max(best, 80)
        elif all(any(token.startswith(w) for token in tokens) for w in wanted_tokens):
            best = max(best, 60)
        elif wanted.replace(" ", "") in normalized.replace(" ", ""):
            best = max(best, 40)
    return best
