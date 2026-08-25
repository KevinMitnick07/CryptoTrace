"""Application entry point."""

# pyrefly: ignore [missing-import]
import uvicorn
from backend.api.routes import app

if __name__ == "__main__":
    uvicorn.run(
        "backend.api.routes:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
