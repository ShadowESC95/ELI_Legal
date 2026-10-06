from fastapi import FastAPI

from eli_legal import __version__
from eli_legal.settings import settings

from .schemas import HealthResponse

app = FastAPI(title="ELI Legal", version=__version__)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", mode=settings.mode, network_default=settings.network_default)


@app.get("/boundaries")
def boundaries() -> dict:
    return {
        "decision_support_only": True,
        "human_release_required": True,
        "personal_assistant_capabilities": False,
        "general_shell": False,
    }
