from fastapi import FastAPI

from app.etl import scripts_loader  # noqa: F401  导入即完成 scripts/ 复用层装载


def create_app() -> FastAPI:
    app = FastAPI(title="中医经方 RAG · M1")

    from app.api import acupoints as acupoints_api
    from app.api import admin as admin_api
    from app.api import cases as cases_api
    from app.api import chat as chat_api
    from app.api import evidence as evidence_api
    from app.api import formulas as formulas_api
    from app.api import herbs as herbs_api
    from app.api import search as search_api
    from app.api import tools as tools_api

    app.include_router(search_api.router)
    app.include_router(formulas_api.router)
    app.include_router(herbs_api.router)
    app.include_router(acupoints_api.router)
    app.include_router(cases_api.router)
    app.include_router(chat_api.router)
    app.include_router(evidence_api.router)
    app.include_router(tools_api.router)
    # §10 E2 落地：管理端拆到 app/api/admin.py，public_router 管登录与探针，
    # router 整体受 require_admin 登录门保护（M5-A Task 2）。
    app.include_router(admin_api.public_router)
    app.include_router(admin_api.router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
