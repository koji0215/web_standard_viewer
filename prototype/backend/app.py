"""
プロトタイプ用バックエンドAPI

あらかじめ取得したNEOWISE/ASASSNライトカーブデータを提供する
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
from pathlib import Path

app = FastAPI(
    title="Lightcurve Data API (Prototype)",
    description="NEOWISEとASASSNのライトカーブデータを提供するプロトタイプAPI",
    version="0.1.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# データディレクトリのパス
DATA_DIR = Path(__file__).parent.parent / "data"
NEOWISE_DIR = DATA_DIR / "neowise"
ASASSN_DIR = DATA_DIR / "asassn"


class NEOWISEObservation(BaseModel):
    """NEOWISE観測データ"""
    mjd: float
    w1_mag: float
    w1_err: float
    w2_mag: float
    w2_err: float


class NEOWISELightCurve(BaseModel):
    """NEOWISEライトカーブ"""
    source_id: str
    ra: float
    dec: float
    allwise_id: str
    num_observations: int
    observations: List[NEOWISEObservation]


class ASASSNObservation(BaseModel):
    """ASASSN観測データ"""
    mjd: float
    mag: float
    mag_err: float
    band: str


class ASASSNLightCurve(BaseModel):
    """ASASSNライトカーブ"""
    source_id: str
    ra: float
    dec: float
    gaia_id: str
    num_observations: int
    observations: List[ASASSNObservation]


def find_lightcurve_file(data_dir: Path, source_id: str = None, ra: float = None, dec: float = None) -> Optional[Path]:
    """
    ライトカーブファイルを検索
    
    source_idが指定されている場合は直接ファイルを探す
    座標が指定されている場合は、最も近い天体のファイルを返す
    """
    if source_id:
        # source_idで直接検索
        file_path = data_dir / f"{source_id}.json"
        if file_path.exists():
            return file_path
        return None
    
    if ra is not None and dec is not None:
        # 座標で検索（最近傍）
        min_distance = float('inf')
        closest_file = None
        
        for file_path in data_dir.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    file_ra = data.get('ra')
                    file_dec = data.get('dec')
                    
                    if file_ra is not None and file_dec is not None:
                        # 簡易的な距離計算（小角度近似）
                        distance = ((ra - file_ra)**2 + (dec - file_dec)**2)**0.5
                        if distance < min_distance:
                            min_distance = distance
                            closest_file = file_path
            except Exception:
                continue
        
        # 3秒角（0.00083度）以内であればマッチとみなす
        if min_distance < 0.00083:
            return closest_file
    
    return None


@app.get("/")
def root():
    """ルートエンドポイント"""
    return {
        "message": "Lightcurve Data API (Prototype)",
        "version": "0.1.0",
        "endpoints": {
            "neowise": "/api/lightcurve/neowise",
            "asassn": "/api/lightcurve/asassn",
            "list": "/api/list",
            "docs": "/docs"
        }
    }


@app.get("/api/list")
def list_available_data():
    """利用可能なデータのリスト"""
    neowise_files = list(NEOWISE_DIR.glob("*.json"))
    asassn_files = list(ASASSN_DIR.glob("*.json"))
    
    return {
        "neowise_count": len(neowise_files),
        "asassn_count": len(asassn_files),
        "neowise_sources": [f.stem for f in neowise_files[:10]],  # 最初の10個のみ
        "asassn_sources": [f.stem for f in asassn_files[:10]]
    }


@app.get("/api/lightcurve/neowise", response_model=NEOWISELightCurve)
def get_neowise_lightcurve(
    source_id: Optional[str] = None,
    ra: Optional[float] = None,
    dec: Optional[float] = None
):
    """
    NEOWISEライトカーブを取得
    
    - **source_id**: SOURCE_ID（Gaia DR3）で検索
    - **ra, dec**: 座標で検索（度単位）
    """
    if not source_id and (ra is None or dec is None):
        raise HTTPException(
            status_code=400,
            detail="source_id または (ra, dec) のいずれかを指定してください"
        )
    
    file_path = find_lightcurve_file(NEOWISE_DIR, source_id, ra, dec)
    
    if not file_path:
        raise HTTPException(
            status_code=404,
            detail="指定された条件に一致するNEOWISEライトカーブが見つかりませんでした"
        )
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"データの読み込みに失敗しました: {str(e)}"
        )


@app.get("/api/lightcurve/asassn", response_model=ASASSNLightCurve)
def get_asassn_lightcurve(
    source_id: Optional[str] = None,
    ra: Optional[float] = None,
    dec: Optional[float] = None
):
    """
    ASASSNライトカーブを取得
    
    - **source_id**: SOURCE_ID（Gaia DR3）で検索
    - **ra, dec**: 座標で検索（度単位）
    """
    if not source_id and (ra is None or dec is None):
        raise HTTPException(
            status_code=400,
            detail="source_id または (ra, dec) のいずれかを指定してください"
        )
    
    file_path = find_lightcurve_file(ASASSN_DIR, source_id, ra, dec)
    
    if not file_path:
        raise HTTPException(
            status_code=404,
            detail="指定された条件に一致するASASSNライトカーブが見つかりませんでした"
        )
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"データの読み込みに失敗しました: {str(e)}"
        )


@app.get("/health")
def health_check():
    """ヘルスチェック"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    print("Starting Lightcurve Data API server...")
    print("API documentation: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
