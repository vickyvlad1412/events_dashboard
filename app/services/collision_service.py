from collections import defaultdict


def find_collisions(weekend_events: list[dict]) -> dict:
    by_day = defaultdict(list)
    for event in weekend_events:
        day_key = event["local_datetime"].strftime("%Y-%m-%d")
        by_day[day_key].append(event)

    result = {}
    for day_key, events in by_day.items():
        high_priority = [e for e in events if e["priority_tier"] in ("A", "B")]
        result[day_key] = {
            "events": sorted(events, key=lambda e: e["local_datetime"]),
            "high_priority_count": len(high_priority),
            "is_collision": len(high_priority) >= 2,
        }
    return result