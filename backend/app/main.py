from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.etl import scripts_loader  # noqa: F401  导入即完成 scripts/ 复用层装载


def create_app() -> FastAPI:
    app = FastAPI(title="中医经方 RAG · M1")

    from app.api import acupoints as acupoints_api
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

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # ⚠️ 一期无鉴权：§10 E2（管理端权限）尚未定稿。
    # 这两个端点能被匿名访问是**已知的未决项**，不是遗漏——E2 落地时 test_admin_api 的
    # 「匿名可访问」断言必须被改，好让这件事在测试里留痕。
    @app.get("/api/admin/quality-report")
    def quality_report(session: Session = Depends(get_session)):
        from app.admin.quality import build_quality_report

        return build_quality_report(session).to_dict()

    @app.post("/api/admin/reindex")
    def reindex_now(session: Session = Depends(get_session)):
        from dataclasses import asdict

        from app.admin.reindex import run_reindex

        report = run_reindex(session)
        session.commit()
        return asdict(report)

    return app
