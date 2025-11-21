"""
NEOWISE Performance Testing Backend
Tests query_region vs query_tap performance for NEOWISE data retrieval
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np
from astroquery.ipac.irsa import Irsa
import astropy.coordinates as coord
import astropy.units as u

app = FastAPI(
    title="NEOWISE Performance Testing API",
    description="Compare performance of different NEOWISE data retrieval methods",
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

# スレッドプール（同期的なastroqueryをバックグラウンドで実行）
executor = ThreadPoolExecutor(max_workers=4)


class CatalogEntry(BaseModel):
    """カタログエントリー"""
    source_id: str
    ra: float
    dec: float
    allwise_id: Optional[str] = None


class ProgressUpdate(BaseModel):
    """進捗更新"""
    current: int
    total: int
    current_star: str
    message: str


class TestRequest(BaseModel):
    """テストリクエスト"""
    catalog_entries: List[CatalogEntry] = Field(..., description="テスト対象の天体リスト")
    method: str = Field(..., description="テスト方法: 'query_region' or 'query_tap'")


class TestResult(BaseModel):
    """個別テスト結果"""
    source_id: str
    ra: float
    dec: float
    allwise_id: Optional[str]
    query_time: float
    num_observations: int
    success: bool
    error_message: Optional[str] = None


class PerformanceResult(BaseModel):
    """全体のパフォーマンス結果"""
    method: str
    total_time: float
    avg_time_per_star: float
    min_time: float
    max_time: float
    successful_queries: int
    failed_queries: int
    results: List[TestResult]


def query_neowise_by_region(ra: float, dec: float) -> tuple:
    """
    query_regionを使用してNEOWISEデータを取得
    
    Returns:
        (num_observations, query_time)
    """
    start_time = time.time()
    
    try:
        table = Irsa.query_region(
            coord.SkyCoord(ra, dec, unit=(u.deg, u.deg)),
            catalog='neowiser_p1bs_psd',
            radius='0d0m5s'  # 5秒角
        )
        query_time = time.time() - start_time
        
        if table is None or len(table) == 0:
            return 0, query_time
        
        return len(table), query_time
        
    except Exception as e:
        query_time = time.time() - start_time
        raise Exception(f"Query failed: {str(e)}")


def query_neowise_by_tap(ra: float, dec: float, allwise_id: Optional[str] = None) -> tuple:
    """
    query_tapを使用してNEOWISEデータを取得
    allwise_idが指定されている場合はallwise_cntrで検索
    指定されていない場合は座標で検索
    
    Returns:
        (num_observations, query_time)
    """
    start_time = time.time()
    
    try:
        if allwise_id:
            # AllWISE IDからallwise_cntrを取得（AllWISEカタログを検索）
            # 簡略化のため、AllWISE IDを直接使用
            # 実際にはAllWISEカタログでallwise_cntrを取得する必要がある
            query = f"""
            SELECT * FROM neowiser_p1bs_psd
            WHERE allwise_cntr IN (
                SELECT cntr FROM allwise_p3as_psd
                WHERE designation = '{allwise_id}'
            )
            """
        else:
            # 座標で検索（5秒角以内）
            query = f"""
            SELECT * FROM neowiser_p1bs_psd
            WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, 0.00139)) = 1
            """
        
        table = Irsa.query_tap(query)
        query_time = time.time() - start_time
        
        if table is None or len(table) == 0:
            return 0, query_time
        
        return len(table), query_time
        
    except Exception as e:
        query_time = time.time() - start_time
        raise Exception(f"Query failed: {str(e)}")


@app.get("/")
async def root():
    return {
        "message": "NEOWISE Performance Testing API",
        "version": "0.1.0",
        "endpoints": {
            "/test-performance": "POST - テストを実行",
            "/docs": "API documentation"
        }
    }


@app.post("/test-performance", response_model=PerformanceResult)
async def test_performance(request: TestRequest):
    """
    NEOWISEデータ取得のパフォーマンステスト
    """
    results = []
    total_start_time = time.time()
    total_entries = len(request.catalog_entries)
    
    for idx, entry in enumerate(request.catalog_entries, 1):
        print(f"Processing {idx}/{total_entries}: {entry.source_id}")
        
        try:
            if request.method == "query_region":
                # query_regionを使用
                num_obs, query_time = await asyncio.get_event_loop().run_in_executor(
                    executor,
                    query_neowise_by_region,
                    entry.ra,
                    entry.dec
                )
            elif request.method == "query_tap":
                # query_tapを使用
                num_obs, query_time = await asyncio.get_event_loop().run_in_executor(
                    executor,
                    query_neowise_by_tap,
                    entry.ra,
                    entry.dec,
                    entry.allwise_id
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid method. Use 'query_region' or 'query_tap'")
            
            results.append(TestResult(
                source_id=entry.source_id,
                ra=entry.ra,
                dec=entry.dec,
                allwise_id=entry.allwise_id,
                query_time=query_time,
                num_observations=num_obs,
                success=True
            ))
            print(f"  ✓ Success: {num_obs} observations in {query_time:.2f}s")
            
        except Exception as e:
            print(f"  ✗ Error: {str(e)}")
            results.append(TestResult(
                source_id=entry.source_id,
                ra=entry.ra,
                dec=entry.dec,
                allwise_id=entry.allwise_id,
                query_time=0,
                num_observations=0,
                success=False,
                error_message=str(e)
            ))
    
    total_time = time.time() - total_start_time
    
    # 統計を計算
    successful_results = [r for r in results if r.success]
    query_times = [r.query_time for r in successful_results]
    
    if query_times:
        avg_time = np.mean(query_times)
        min_time = np.min(query_times)
        max_time = np.max(query_times)
    else:
        avg_time = min_time = max_time = 0
    
    return PerformanceResult(
        method=request.method,
        total_time=total_time,
        avg_time_per_star=avg_time,
        min_time=min_time,
        max_time=max_time,
        successful_queries=len(successful_results),
        failed_queries=len(results) - len(successful_results),
        results=results
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
