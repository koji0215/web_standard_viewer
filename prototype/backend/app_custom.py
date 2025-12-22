"""
カスタムSQLiteデータベース用バックエンドAPI

作成したSQLiteデータベース（neowise_target_region.db）からデータを提供する
フロントエンド（index.html）と互換性のあるAPI形式
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import sqlite3
import pandas as pd
import numpy as np
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
    raw: bool = False,
    # Filter parameters for raw mode
    apply_cc_flags: bool = Query(True, description="cc_flags='0' フィルタを適用"),
    apply_sso_flg: bool = Query(True, description="sso_flg=0 フィルタを適用"),
    apply_qi_fact: bool = Query(True, description="qi_fact=1.0 フィルタを適用"),
    apply_saa_sep: bool = Query(True, description="saa_sep>=5.0 フィルタを適用"),
    apply_ph_qual: bool = Query(True, description="ph_qual='A' フィルタを適用"),
    apply_moon_masked: bool = Query(True, description="moon_masked='0' フィルタを適用"),
    apply_sat: bool = Query(True, description="sat<=0.05 フィルタを適用"),
    apply_rchi2: bool = Query(True, description="rchi2<=50 フィルタを適用"),
    apply_qual_frame: bool = Query(True, description="qual_frame>0.0 フィルタを適用"),
    apply_sky: bool = Query(True, description="sky not null フィルタを適用"),
    apply_zp_correction: bool = Query(True, description="ゼロポイント補正を適用"),
    apply_sigma_clipping: bool = Query(True, description="3σクリッピングを適用")
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
            raw_data = pd.read_sql_query("""
                SELECT mjd, band, mpro, sigmpro, mpro_corrected,
                       cc_flags, ph_qual, moon_masked, sso_flg,
                       qi_fact, saa_sep, sat, rchi2, qual_frame, sky
                FROM neowise_raw_observations
                WHERE source_id = ?
                ORDER BY mjd
            """, conn, params=[actual_source_id])
            
            # Apply filters for each band
            data_list = []
            for band in ['W1', 'W2']:
                band_data = raw_data[raw_data['band'] == band].copy()
                if band_data.empty:
                    continue
                
                band_idx = 0 if band == 'W1' else 1
                mask = pd.Series([True] * len(band_data), index=band_data.index)
                
                if apply_cc_flags:
                    mask &= (band_data['cc_flags'].str.len() > band_idx) & (band_data['cc_flags'].str[band_idx] == '0')
                if apply_sso_flg:
                    mask &= band_data['sso_flg'] == 0
                if apply_qi_fact:
                    mask &= band_data['qi_fact'] == 1.0
                if apply_saa_sep:
                    mask &= band_data['saa_sep'] >= 5.0
                if apply_ph_qual:
                    mask &= (band_data['ph_qual'].str.len() > band_idx) & (band_data['ph_qual'].str[band_idx] == 'A')
                if apply_moon_masked:
                    mask &= (band_data['moon_masked'].str.len() > band_idx) & (band_data['moon_masked'].str[band_idx] == '0')
                if apply_sat:
                    mask &= band_data['sat'] <= 0.05
                if apply_rchi2:
                    mask &= band_data['rchi2'] <= 50
                if apply_qual_frame:
                    mask &= band_data['qual_frame'] > 0.0
                if apply_sky:
                    mask &= band_data['sky'].notna()
                
                filtered_band = band_data[mask].copy()
                
                if filtered_band.empty:
                    continue
                
                # Apply zero-point correction
                if apply_zp_correction:
                    filtered_band['mag'] = filtered_band['mpro_corrected']
                else:
                    filtered_band['mag'] = filtered_band['mpro']
                
                filtered_band['mag_err'] = filtered_band['sigmpro']
                
                # Apply 3-sigma clipping
                if apply_sigma_clipping:
                    mean_mag = filtered_band['mag'].mean()
                    std_mag = filtered_band['mag'].std()
                    
                    if std_mag > 0 and not np.isnan(std_mag):
                        sigma_mask = (
                            (filtered_band['mag'] >= (mean_mag - 3 * std_mag)) &
                            (filtered_band['mag'] <= (mean_mag + 3 * std_mag))
                        )
                        filtered_band = filtered_band[sigma_mask].copy()
                
                data_list.append(filtered_band[['mjd', 'band', 'mag', 'mag_err']])
            
            data = pd.concat(data_list, ignore_index=True) if data_list else pd.DataFrame()
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
                   qi_fact, saa_sep, sat, rchi2, qual_frame, sky
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


@app.get("/api/neowise/filtered/{source_id}")
def get_neowise_filtered_data(
    source_id: str,
    band: str = Query("W1", description="バンド (W1 or W2)"),
    apply_cc_flags: bool = Query(True, description="cc_flags='0' フィルタを適用"),
    apply_sso_flg: bool = Query(True, description="sso_flg=0 フィルタを適用"),
    apply_qi_fact: bool = Query(True, description="qi_fact=1.0 フィルタを適用"),
    apply_saa_sep: bool = Query(True, description="saa_sep>=5.0 フィルタを適用"),
    apply_ph_qual: bool = Query(True, description="ph_qual='A' フィルタを適用"),
    apply_moon_masked: bool = Query(True, description="moon_masked='0' フィルタを適用"),
    apply_sat: bool = Query(True, description="sat<=0.05 フィルタを適用"),
    apply_rchi2: bool = Query(True, description="rchi2<=50 フィルタを適用"),
    apply_qual_frame: bool = Query(True, description="qual_frame>0.0 フィルタを適用"),
    apply_sky: bool = Query(True, description="sky not null フィルタを適用"),
    apply_zp_correction: bool = Query(True, description="ゼロポイント補正を適用"),
    apply_sigma_clipping: bool = Query(True, description="3σクリッピングを適用")
):
    """
    NEOWISEフィルタ済みデータを取得
    
    Parameters:
    - source_id: 天体識別子
    - band: バンド (W1 or W2)
    - apply_*: 各フィルタの適用有無
    - apply_zp_correction: ゼロポイント補正の適用有無
    - apply_sigma_clipping: 3σクリッピングの適用有無
    
    Returns:
    - フィルタ適用後のデータ（MJD, 等級, 誤差）
    """
    if band not in ['W1', 'W2']:
        raise HTTPException(status_code=400, detail="バンドはW1またはW2を指定してください")
    
    conn = get_db_connection()
    
    try:
        # 生データを取得
        data = pd.read_sql_query("""
            SELECT mjd, band, mpro, sigmpro, mpro_corrected,
                   cc_flags, ph_qual, moon_masked, sso_flg,
                   qi_fact, saa_sep, sat, rchi2, qual_frame, sky
            FROM neowise_raw_observations
            WHERE source_id = ? AND band = ?
            ORDER BY mjd
        """, conn, params=[source_id, band])
        
        if data.empty:
            raise HTTPException(
                status_code=404, 
                detail=f"生データが見つかりません: {source_id}, {band}"
            )
        
        original_count = len(data)
        
        # バンドインデックス（cc_flags, ph_qual, moon_maskedは2文字）
        band_idx = 0 if band == 'W1' else 1
        
        # フィルタリング
        mask = pd.Series([True] * len(data), index=data.index)
        
        if apply_cc_flags:
            mask &= (data['cc_flags'].str.len() > band_idx) & (data['cc_flags'].str[band_idx] == '0')
        
        if apply_sso_flg:
            mask &= data['sso_flg'] == 0
        
        if apply_qi_fact:
            mask &= data['qi_fact'] == 1.0
        
        if apply_saa_sep:
            mask &= data['saa_sep'] >= 5.0
        
        if apply_ph_qual:
            mask &= (data['ph_qual'].str.len() > band_idx) & (data['ph_qual'].str[band_idx] == 'A')
        
        if apply_moon_masked:
            mask &= (data['moon_masked'].str.len() > band_idx) & (data['moon_masked'].str[band_idx] == '0')
        
        if apply_sat:
            mask &= data['sat'] <= 0.05
        
        if apply_rchi2:
            mask &= data['rchi2'] <= 50
        
        if apply_qual_frame:
            mask &= data['qual_frame'] > 0.0
        
        if apply_sky:
            mask &= data['sky'].notna()
        
        filtered_data = data[mask].copy()
        
        if filtered_data.empty:
            return {
                "source_id": source_id,
                "band": band,
                "original_count": original_count,
                "filtered_count": 0,
                "data": []
            }
        
        # ゼロポイント補正の選択
        if apply_zp_correction:
            filtered_data['mag'] = filtered_data['mpro_corrected']
        else:
            filtered_data['mag'] = filtered_data['mpro']
        
        filtered_data['mag_err'] = filtered_data['sigmpro']
        
        # 3σクリッピング
        if apply_sigma_clipping:
            mean_mag = filtered_data['mag'].mean()
            std_mag = filtered_data['mag'].std()
            
            if std_mag > 0 and not np.isnan(std_mag):
                sigma_mask = (
                    (filtered_data['mag'] >= (mean_mag - 3 * std_mag)) &
                    (filtered_data['mag'] <= (mean_mag + 3 * std_mag))
                )
                filtered_data = filtered_data[sigma_mask].copy()
        
        result = filtered_data[['mjd', 'mag', 'mag_err']].to_dict(orient='records')
        
        return {
            "source_id": source_id,
            "band": band,
            "original_count": original_count,
            "filtered_count": len(filtered_data),
            "filters_applied": {
                "cc_flags": apply_cc_flags,
                "sso_flg": apply_sso_flg,
                "qi_fact": apply_qi_fact,
                "saa_sep": apply_saa_sep,
                "ph_qual": apply_ph_qual,
                "moon_masked": apply_moon_masked,
                "sat": apply_sat,
                "rchi2": apply_rchi2,
                "qual_frame": apply_qual_frame,
                "sky": apply_sky,
                "zp_correction": apply_zp_correction,
                "sigma_clipping": apply_sigma_clipping
            },
            "data": result
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
