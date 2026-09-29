from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import dashboard, events
from app.config import BASE_DIR

app = FastAPI(title="Personal Events Dashboard")

app.mount(
    "/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static"
)

app.include_router(dashboard.router)
app.include_router(events.router)


@app.on_event("startup")
def on_startup():
    init_db()