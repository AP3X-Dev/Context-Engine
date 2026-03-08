"""ONI Cortex Gateway — production entrypoint."""

from contextlib import asynccontextmanager
from scripts.cortex.api import create_app
from scripts.cortex.database import init_db


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield

app = create_app()
app.router.lifespan_context = lifespan
