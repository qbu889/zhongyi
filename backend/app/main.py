from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="中医经方 RAG · M1")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
