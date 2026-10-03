from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db, migrate_add_external_columns
from app.scheduler import start_scheduler
from app.routers import dashboard, events, calendar, config_routes, recommendations
from app.config import BASE_DIR

app = FastAPI(title="Personal Events Dashboard")

app.mount(
    "/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static"
)

app.include_router(dashboard.router)
app.include_router(events.router)
app.include_router(calendar.router)
app.include_router(config_routes.router)
app.include_router(recommendations.router)


@app.on_event("startup")
def on_startup():
    init_db()
    migrate_add_external_columns()
    start_scheduler()

