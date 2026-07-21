import base64
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel


class InferRequest(BaseModel):
    image_base64: str

    nodeCode: Optional[str] = None
    controlCode: Optional[str] = None
    streamCode: Optional[str] = None
    streamApp: Optional[str] = None
    streamName: Optional[str] = None

    algorithmCode: Optional[str] = None
    flowCode: Optional[str] = None

    modelClassNames: Optional[str] = None
    detectClassNames: Optional[str] = None

    polygonType: Optional[int] = None
    polygon: Optional[str] = None

    classThresh: Optional[float] = None
    overlapThresh: Optional[float] = None

    algorithmParams: Optional[Dict[str, Any]] = None
    extensions: Optional[Dict[str, Any]] = None


class Detect(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    class_id: int
    class_score: float
    class_name: str


class InferResult(BaseModel):
    happen: bool = False
    happenScore: float = 0.0
    detects: List[Detect] = []


class InferResponse(BaseModel):
    code: int = 1000
    msg: str = "success"
    result: InferResult


class AudioInferRequest(BaseModel):
    audio_base64: str
    algorithmCode: Optional[str] = None
    language: Optional[str] = None
    hotwords: Optional[List[str]] = None
    extensions: Optional[Dict[str, Any]] = None


class AudioSegment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class AudioInferResult(BaseModel):
    text: str = ""
    language: str = "zh-CN"
    segments: List[AudioSegment] = []


class AudioInferResponse(BaseModel):
    code: int = 1000
    msg: str = "success"
    result: AudioInferResult


app = FastAPI(title="Beacon Algorithm API Example (Protocol v2)")


@app.post("/infer")
def infer(req: InferRequest) -> Dict[str, Any]:
    t1 = time.time()

    # Validate base64 quickly (no heavy decode work here).
    try:
        raw = base64.b64decode(req.image_base64, validate=True)
    except Exception:
        return {"code": 0, "msg": "invalid base64"}

    # Demo logic: if payload looks non-empty, return a fixed box for integration testing.
    _ = len(raw)
    detects: List[Dict[str, Any]] = [
        {
            "x1": 100,
            "y1": 80,
            "x2": 420,
            "y2": 680,
            "class_id": 0,
            "class_score": 0.99,
            "class_name": "demo",
        }
    ]

    t2 = time.time()
    _latency_ms = int((t2 - t1) * 1000)

    return {
        "code": 1000,
        "msg": "success",
        "result": {
            "happen": False,
            "happenScore": 0.0,
            "detects": detects,
        },
    }


@app.post("/audio/infer")
def audio_infer(req: AudioInferRequest) -> Dict[str, Any]:
    try:
        raw = base64.b64decode(req.audio_base64, validate=True)
    except Exception:
        return {"code": 0, "msg": "invalid base64"}

    _ = len(raw)
    language = str(req.language or "zh-CN")
    text = "demo transcript"
    return {
        "code": 1000,
        "msg": "success",
        "result": {
            "text": text,
            "language": language,
            "segments": [
                {
                    "start_ms": 0,
                    "end_ms": 1200,
                    "text": text,
                }
            ],
        },
    }
