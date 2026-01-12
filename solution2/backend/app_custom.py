"""
カスタムSQLiteデータベース用バックエンドAPI

作成したSQLiteデータベース（neowise_target_region.db）からデータを提供する
フロントエンド（index.html）と互換性のあるAPI形式
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import sqlite3
import pandas as pd
from pathlib import Path

app = FastAPI(
    title="NEOWISE Lightcurve API (Custom SQLite)",
    description="カスタムSQLiteデータベースからライトカーブデータを提供するAPI",
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

# SQLiteファイルパス（作成したファイルのパスに変更してください）
# デフォルト: カレントディレクトリまたはbackendディレクトリの親に配置
DB_PATH = None

def find_database():
    """データベースファイルを探す"""
    global DB_PATH
    
    # 検索パスの優先順位
    search_paths = [
        Path("neowise_target_region.db"),  # カレントディレクトリ
        Path("../neowise_target_region.db"),  # 親ディレクトリ
        Path(__file__).parent / "neowise_target_region.db",  # backendディレクトリ
        Path(__file__).parent.parent / "neowise_target_region.db",  # prototypeディレクトリ
        Path.home() / "neowise_target_region.db",  # ホームディレクトリ
    ]
    
    for path in search_paths:
        if path.exists():
            DB_PATH = str(path.resolve())
            print(f"✅ データベースを発見: {DB_PATH}")
            return DB_PATH
    
    print("⚠️ データベースファイルが見つかりません")
    print("以下のいずれかの場所にneowise_target_region.dbを配置してください:")
    for path in search_paths:
        print(f"  - {path.resolve()}")
    
    return None

# 起動時にデータベースを探す
find_database()


def get_db_connection():
    """データベース接続を取得"""
    if DB_PATH is None:
        raise HTTPException(
            status_code=500,
            detail="データベースファイルが設定されていません。neowise_target_region.dbをbackendディレクトリに配置してください。"
        )
    
    if not Path(DB_PATH).exists():
        raise HTTPException(
            status_code=500,
            detail=f"データベースファイルが見つかりません: {DB_PATH}"
        )
    
    return sqlite3.connect(DB_PATH)


@app.get("/")
def root():
    """ルートエンドポイント"""
    return {
        "message": "NEOWISE Lightcurve API (Custom SQLite)",
        "version": "1.0.0",
        "database": DB_PATH,
        "endpoints": {
            "neowise": "/api/lightcurve/neowise",
            "asassn": "/api/lightcurve/asassn",
            "list": "/api/list",
            "docs": "/docs"
        }
    }


@app.get("/api/list")
def list_sources():
    """登録された天体一覧を取得"""
    conn = get_db_connection()
    
    try:
        # sourcesテーブルからデータを取得
        sources_df = pd.read_sql_query("SELECT * FROM sources", conn)
        
        # 各ソースのエポックデータ数を取得
        epoch_counts = pd.read_sql_query("""
            SELECT source_id, COUNT(*) as count 
            FROM neowise_epoch_summary 
            GROUP BY source_id
        """, conn)
        
        return {
            "neowise_count": len(sources_df),
            "asassn_count": 0,  # ASASSNデータはこのDBにはない
            "neowise_sources": sources_df['source_id'].tolist()[:20],
            "asassn_sources": []
        }
    finally:
        conn.close()


@app.get("/api/lightcurve/neowise")
def get_neowise_lightcurve(
    source_id: Optional[str] = None,
    ra: Optional[float] = None,
    dec: Optional[float] = None,
    raw: bool = False
):
    """
    NEOWISEライトカーブを取得
    
    フロントエンド（index.html）と互換性のある形式で返す
    
    Parameters:
    - source_id: 天体識別子（Gaia DR3 SOURCE_ID）
    - ra, dec: 座標で検索（度単位）
    - raw: True=生データ, False=エポック集約データ（デフォルト）
    """
    if not source_id and (ra is None or dec is None):
        raise HTTPException(
            status_code=400,
            detail="source_id または (ra, dec) のいずれかを指定してください"
        )
    
    conn = get_db_connection()
    
    try:
        # 座標で検索する場合、最も近い天体を探す
        if not source_id and ra is not None and dec is not None:
            sources = pd.read_sql_query("SELECT * FROM sources", conn)
            if sources.empty:
                raise HTTPException(status_code=404, detail="データベースに天体が登録されていません")
            
            # 簡易的な距離計算（小角度近似）
            sources['distance'] = ((sources['ra'] - ra)**2 + (sources['dec'] - dec)**2)**0.5
            closest = sources.loc[sources['distance'].idxmin()]
            
            # 3秒角（0.00083度）以内であればマッチとみなす
            if closest['distance'] > 0.00083:
                raise HTTPException(
                    status_code=404,
                    detail=f"指定された座標(RA={ra}, Dec={dec})の近くに天体が見つかりませんでした"
                )
            
            source_id = closest['source_id']
        
        # 天体情報を取得（source_idを文字列と整数の両方で検索）
        source = pd.read_sql_query(
            "SELECT * FROM sources WHERE source_id = ? OR CAST(source_id AS TEXT) = ?", 
            conn, params=[source_id, str(source_id)]
        )
        
        if source.empty:
            raise HTTPException(
                status_code=404, 
                detail=f"指定されたsource_idの天体が見つかりません: {source_id}"
            )
        
        source_info = source.iloc[0]
        
        if raw:
            # 生データを取得（source_idを文字列と整数の両方で検索）
            actual_source_id = source.iloc[0]['source_id']
            data = pd.read_sql_query("""
                SELECT mjd, band, mpro_corrected as mag, sigmpro as mag_err
                FROM neowise_raw_observations
                WHERE source_id = ?
                ORDER BY mjd
            """, conn, params=[actual_source_id])
        else:
            # エポック集約データを取得
            actual_source_id = source.iloc[0]['source_id']
            data = pd.read_sql_query("""
                SELECT mjd_mean as mjd, band, mag_mean as mag, mag_se as mag_err
                FROM neowise_epoch_summary
                WHERE source_id = ?
                ORDER BY mjd_mean
            """, conn, params=[actual_source_id])
        
        # フロントエンド互換形式に変換
        # W1とW2のデータを統合してobservations配列を作成
        observations = []
        
        # W1データを取得
        w1_data = data[data['band'] == 'W1'].reset_index(drop=True)
        # W2データを取得
        w2_data = data[data['band'] == 'W2'].reset_index(drop=True)
        
        # MJDでマージ（または個別に追加）
        all_mjds = sorted(set(w1_data['mjd'].tolist() + w2_data['mjd'].tolist()))
        
        for mjd in all_mjds:
            w1_row = w1_data[w1_data['mjd'] == mjd]
            w2_row = w2_data[w2_data['mjd'] == mjd]
            
            obs = {"mjd": mjd}
            
            if not w1_row.empty:
                obs["w1_mag"] = float(w1_row['mag'].iloc[0]) if pd.notna(w1_row['mag'].iloc[0]) else None
                obs["w1_err"] = float(w1_row['mag_err'].iloc[0]) if pd.notna(w1_row['mag_err'].iloc[0]) else None
            else:
                obs["w1_mag"] = None
                obs["w1_err"] = None
            
            if not w2_row.empty:
                obs["w2_mag"] = float(w2_row['mag'].iloc[0]) if pd.notna(w2_row['mag'].iloc[0]) else None
                obs["w2_err"] = float(w2_row['mag_err'].iloc[0]) if pd.notna(w2_row['mag_err'].iloc[0]) else None
            else:
                obs["w2_mag"] = None
                obs["w2_err"] = None
            
            # W1またはW2のいずれかにデータがある場合のみ追加
            if obs["w1_mag"] is not None or obs["w2_mag"] is not None:
                observations.append(obs)
        
        # allwise_cntrを取得
        allwise_id = str(source_info.get('allwise_cntr', '')) if pd.notna(source_info.get('allwise_cntr', None)) else ''
        
        return {
            "source_id": str(source_id),
            "ra": float(source_info['ra']),
            "dec": float(source_info['dec']),
            "allwise_id": allwise_id,
            "num_observations": len(observations),
            "observations": observations
        }
        
    finally:
        conn.close()


@app.get("/api/lightcurve/asassn")
def get_asassn_lightcurve(
    source_id: Optional[str] = None,
    ra: Optional[float] = None,
    dec: Optional[float] = None
):
    """
    ASASSNライトカーブを取得
    
    ※現在このデータベースにはASASSNデータは含まれていません
    """
    # ASASSNデータはこのDBにはないので、空のデータを返す
    # エラーではなく、空のデータとして返す（フロントエンドの並行取得に対応）
    
    conn = get_db_connection()
    
    try:
        # source_idが指定されている場合、その天体情報を取得
        if source_id:
            source = pd.read_sql_query(
                "SELECT * FROM sources WHERE source_id = ? OR CAST(source_id AS TEXT) = ?", 
                conn, params=[source_id, str(source_id)]
            )
            
            if not source.empty:
                source_info = source.iloc[0]
                return {
                    "source_id": str(source_id),
                    "ra": float(source_info['ra']),
                    "dec": float(source_info['dec']),
                    "gaia_id": str(source_id),
                    "num_observations": 0,
                    "observations": []
                }
        
        # 座標検索の場合
        if ra is not None and dec is not None:
            sources = pd.read_sql_query("SELECT * FROM sources", conn)
            if not sources.empty:
                sources['distance'] = ((sources['ra'] - ra)**2 + (sources['dec'] - dec)**2)**0.5
                closest = sources.loc[sources['distance'].idxmin()]
                
                if closest['distance'] <= 0.00083:
                    return {
                        "source_id": str(closest['source_id']),
                        "ra": float(closest['ra']),
                        "dec": float(closest['dec']),
                        "gaia_id": str(closest['source_id']),
                        "num_observations": 0,
                        "observations": []
                    }
        
        raise HTTPException(
            status_code=404,
            detail="ASASSNデータはこのデータベースには含まれていません"
        )
        
    finally:
        conn.close()


@app.get("/api/neowise/raw/{source_id}")
def get_neowise_raw_data(source_id: str):
    """
    NEOWISE生データを取得（フィルタリング用）
    
    Parameters:
    - source_id: 天体識別子
    """
    conn = get_db_connection()
    
    try:
        data = pd.read_sql_query("""
            SELECT mjd, band, mpro, sigmpro, mpro_corrected,
                   cc_flags, ph_qual, moon_masked, sso_flg,
                   qi_fact, saa_sep, sat, rchi2, qual_frame
            FROM neowise_raw_observations
            WHERE source_id = ?
            ORDER BY mjd
        """, conn, params=[source_id])
        
        if data.empty:
            raise HTTPException(
                status_code=404, 
                detail=f"生データが見つかりません: {source_id}"
            )
        
        return {
            "source_id": source_id,
            "count": len(data),
            "data": data.to_dict(orient='records')
        }
        
    finally:
        conn.close()


@app.get("/health")
def health_check():
    """ヘルスチェック"""
    return {
        "status": "ok",
        "database": DB_PATH,
        "database_exists": Path(DB_PATH).exists() if DB_PATH else False
    }


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("NEOWISE Lightcurve API (Custom SQLite) を起動します")
    print("=" * 60)
    
    if DB_PATH:
        print(f"✅ データベース: {DB_PATH}")
    else:
        print("⚠️ データベースファイルが見つかりません")
        print("以下のいずれかの場所にneowise_target_region.dbを配置してください:")
        print("  - カレントディレクトリ")
        print("  - prototypeディレクトリ")
        print("  - prototype/backendディレクトリ")
    
    print()
    print("API documentation: http://localhost:8000/docs")
    print("フロントエンド: http://localhost:8080/")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
