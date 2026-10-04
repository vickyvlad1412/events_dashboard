import truststore
truststore.inject_into_ssl()

from dotenv import load_dotenv
from app.config import BASE_DIR, CATALOG_SEED_PATH, ENV_PATH
load_dotenv(ENV_PATH)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import (
    init_db, migrate_add_external_columns, migrate_add_watch_history_columns, migrate_add_ui_columns,
    migrate_tier_rules, import_catalog_seed,
)
from app.scheduler import start_scheduler
from app.services import follow_service
from app.routers import api, dashboard, events, calendar, config_routes, recommendations, history, pages

app = FastAPI(title="Personal Events Dashboard")

app.mount(
    "/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static"
)

app.include_router(dashboard.router)
app.include_router(events.router)
app.include_router(calendar.router)
app.include_router(config_routes.router)
app.include_router(recommendations.router)
app.include_router(history.router)
app.include_router(api.router)
app.include_router(pages.router)


@app.on_event("startup")
def on_startup():
    init_db()
    migrate_add_external_columns()
    migrate_add_watch_history_columns()
    migrate_add_ui_columns()
    migrate_tier_rules()
    import_catalog_seed(CATALOG_SEED_PATH)
    follow_service.seed_football_follows_from_env()
    start_scheduler()

