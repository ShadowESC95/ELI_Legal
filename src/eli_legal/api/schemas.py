from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    mode: str
    network_default: str
