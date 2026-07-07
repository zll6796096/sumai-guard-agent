from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status

from app.models import AnalysisResponse
from app.services.orchestrator import AnalysisOrchestrator


app = FastAPI(title="SumaiGuard Agent", version="0.1.0")
orchestrator = AnalysisOrchestrator()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
    mock: bool = Form(False),
) -> AnalysisResponse:
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="画像ファイルを指定してください。")

    try:
        return await orchestrator.analyze(upload=image, room_hint=room_hint, mock=mock)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"分析中にエラーが発生しました: {exc}") from exc
