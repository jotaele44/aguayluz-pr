"""AguaYLuz backend entrypoint with the research-only mycelial assistant."""
from server.backend.main import app
from server.backend.mycelial import router as mycelial_router

app.include_router(mycelial_router)

__all__ = ["app"]
