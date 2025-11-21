"""
ASASSN パフォーマンステストバックエンド

pyasassnを使用してASASSNデータの取得時間を計測するAPIサーバー
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import time
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ASASSN Performance Test API",
    description="ASASSNデータ取得のパフォーマンステストAPI",
    version="1.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CatalogEntry(BaseModel):
    """カタログエントリ"""
    source_id: str
    ra: float
    dec: float
    gaia_id: Optional[str] = None


class TestRequest(BaseModel):
    """テストリクエスト"""
    catalog_entries: List[CatalogEntry]


class TestResult(BaseModel):
    """個別のテスト結果"""
    source_id: str
    ra: float
    dec: float
    gaia_id: Optional[str]
    query_time: float
    num_lightcurves: int
    total_datapoints: int
    success: bool
    error_message: Optional[str] = None


class PerformanceResult(BaseModel):
    """パフォーマンステスト結果"""
    total_time: float
    avg_time_per_star: float
    min_time: float
    max_time: float
    successful_queries: int
    failed_queries: int
    results: List[TestResult]


def query_asassn_by_gaia_id(gaia_id: str) -> tuple:
    """
    pyasassnを使用してASASSNデータを取得
    
    Args:
        gaia_id: Gaia DR3 source ID
    
    Returns:
        (num_lightcurves, total_datapoints, query_time)
    """
    start_time = time.time()
    
    try:
        from pyasassn.client import SkyPatrolClient
        
        client = SkyPatrolClient()
        
        # ADQLクエリを実行
        query = f"""
        SELECT * 
        FROM stellar_main 
        WHERE gaia_id = {gaia_id}
        """
        
        # download=Trueでライトカーブデータを取得
        # save_dirは指定しない（メモリ上で処理）
        lcs = client.adql_query(query, download=True, save_dir=None, 
                                file_format='pickle', threads=1)
        
        query_time = time.time() - start_time
        
        if lcs is None or len(lcs) == 0:
            return 0, 0, query_time
        
        # ライトカーブ数とデータポイント数を計算
        num_lightcurves = len(lcs)
        total_datapoints = sum(len(lc) if hasattr(lc, '__len__') else 0 for lc in lcs)
        
        return num_lightcurves, total_datapoints, query_time
        
    except Exception as e:
        query_time = time.time() - start_time
        error_msg = str(e)
        
        # エラーメッセージを解析
        if 'No data found' in error_msg or 'empty' in error_msg.lower():
            raise Exception(f"No ASASSN data found for Gaia ID {gaia_id}")
        elif 'timeout' in error_msg.lower():
            raise Exception(f"Query timeout after {query_time:.1f}s. ASASSN server may be slow.")
        elif 'connection' in error_msg.lower() or 'network' in error_msg.lower():
            raise Exception(f"Network error: Cannot connect to ASASSN server.")
        else:
            raise Exception(f"Query failed: {error_msg}")


def query_asassn_by_coordinates(ra: float, dec: float, radius_arcsec: float = 3.0) -> tuple:
    """
    pyasassnを使用して座標からASASSNデータを取得
    
    Args:
        ra: 赤経（度）
        dec: 赤緯（度）
        radius_arcsec: 検索半径（秒角）
    
    Returns:
        (num_lightcurves, total_datapoints, query_time)
    """
    start_time = time.time()
    
    try:
        from pyasassn.client import SkyPatrolClient
        
        client = SkyPatrolClient()
        
        # 円錐検索を実行
        # radiusの単位は度
        radius_deg = radius_arcsec / 3600.0
        
        lcs = client.cone_search(
            ra_deg=ra,
            dec_deg=dec,
            radius=radius_deg,
            download=True,
            threads=1
        )
        
        query_time = time.time() - start_time
        
        if lcs is None or len(lcs) == 0:
            return 0, 0, query_time
        
        # ライトカーブ数とデータポイント数を計算
        num_lightcurves = len(lcs)
        total_datapoints = sum(len(lc) if hasattr(lc, '__len__') else 0 for lc in lcs)
        
        return num_lightcurves, total_datapoints, query_time
        
    except Exception as e:
        query_time = time.time() - start_time
        error_msg = str(e)
        
        if 'No data found' in error_msg or 'empty' in error_msg.lower():
            raise Exception(f"No ASASSN data found at RA={ra:.6f}, DEC={dec:.6f}")
        elif 'timeout' in error_msg.lower():
            raise Exception(f"Query timeout after {query_time:.1f}s. ASASSN server may be slow.")
        elif 'connection' in error_msg.lower() or 'network' in error_msg.lower():
            raise Exception(f"Network error: Cannot connect to ASASSN server.")
        else:
            raise Exception(f"Query failed: {error_msg}")


@app.get("/")
def root():
    """ルートエンドポイント"""
    return {
        "message": "ASASSN Performance Test API",
        "version": "1.0.0",
        "endpoints": {
            "test": "/test-performance",
            "docs": "/docs"
        }
    }


@app.post("/test-performance", response_model=PerformanceResult)
def test_performance(request: TestRequest):
    """
    ASASSNデータ取得のパフォーマンステスト
    
    Gaia IDがある場合はADQLクエリ、ない場合は座標検索を使用
    """
    logger.info(f"Starting performance test with {len(request.catalog_entries)} entries")
    
    results = []
    start_time = time.time()
    
    for entry in request.catalog_entries:
        logger.info(f"Processing {entry.source_id}...")
        
        try:
            # Gaia IDがあればそれを使用、なければ座標検索
            if entry.gaia_id:
                num_lcs, total_points, query_time = query_asassn_by_gaia_id(entry.gaia_id)
            else:
                num_lcs, total_points, query_time = query_asassn_by_coordinates(
                    entry.ra, entry.dec
                )
            
            results.append(TestResult(
                source_id=entry.source_id,
                ra=entry.ra,
                dec=entry.dec,
                gaia_id=entry.gaia_id,
                query_time=query_time,
                num_lightcurves=num_lcs,
                total_datapoints=total_points,
                success=True,
                error_message=None
            ))
            
            logger.info(f"✓ {entry.source_id}: {query_time:.2f}s, {num_lcs} LCs, {total_points} points")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"✗ {entry.source_id}: {error_msg}")
            
            results.append(TestResult(
                source_id=entry.source_id,
                ra=entry.ra,
                dec=entry.dec,
                gaia_id=entry.gaia_id,
                query_time=0.0,
                num_lightcurves=0,
                total_datapoints=0,
                success=False,
                error_message=error_msg
            ))
    
    total_time = time.time() - start_time
    
    # 統計を計算
    successful_results = [r for r in results if r.success]
    query_times = [r.query_time for r in successful_results]
    
    if len(query_times) > 0:
        avg_time = sum(query_times) / len(query_times)
        min_time = min(query_times)
        max_time = max(query_times)
    else:
        avg_time = 0.0
        min_time = 0.0
        max_time = 0.0
    
    result = PerformanceResult(
        total_time=total_time,
        avg_time_per_star=avg_time,
        min_time=min_time,
        max_time=max_time,
        successful_queries=len(successful_results),
        failed_queries=len(results) - len(successful_results),
        results=results
    )
    
    logger.info(f"Test completed: {total_time:.2f}s, {len(successful_results)}/{len(results)} succeeded")
    
    return result


if __name__ == "__main__":
    import uvicorn
    print("Starting ASASSN Performance Test API server...")
    print("API documentation: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
