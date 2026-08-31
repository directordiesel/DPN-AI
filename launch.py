from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn

from app.config import settings


def open_interface() -> None:
    if os.getenv("DPN_NO_BROWSER", "").strip().lower() not in {"1", "true", "yes", "on"}:
        webbrowser.open(f"http://{settings.host}:{settings.port}")


if __name__ == "__main__":
    threading.Timer(2.0, open_interface).start()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)