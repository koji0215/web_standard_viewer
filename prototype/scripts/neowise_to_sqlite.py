#!/usr/bin/env python3
"""
NEOWISE 生データ取得・SQLite出力スクリプト

このスクリプトは、NEOWISEの生データを取得し、フラグによる動的フィルタリングを
可能にするためにSQLiteデータベースに保存します。

使用方法:
    # 座標検索（従来方式）
    python neowise_to_sqlite.py --sources sources.csv --output neowise_lightcurves.db
    
    # AllWISE ID検索（TAP、高速）
    python neowise_to_sqlite.py --sources sources.csv --output neowise_lightcurves.db --use-tap
    
    # 並列処理（高速）
    python neowise_to_sqlite.py --sources sources.csv --output neowise_lightcurves.db --parallel --workers 4
    
    # データベースをクリア（再実行前に）
    python neowise_to_sqlite.py --clear --output neowise_lightcurves.db

sources.csvの形式:
    source_id,ra,dec,AllWISE_ID
    4515624509348164608,292.181969,19.522439,J192843.67+193120.8
    5972956420926034944,251.354,-46.196,J164524.96-461145.6
"""

import pandas as pd
import numpy as np
import sqlite3
import argparse
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# astroqueryは実行環境で利用可能な場合のみインポート
try:
    from astroquery.ipac.irsa import Irsa
    import astropy.coordinates as coord
    import astropy.units as u
    ASTROQUERY_AVAILABLE = True
except ImportError:
    ASTROQUERY_AVAILABLE = False
    logging.warning("astroquery not available. Using mock data for testing.")

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, **kwargs):
        return x

# スレッドセーフなデータベース書き込み用ロック
db_lock = threading.Lock()

# セマフォで「同時に発行する IRSA クエリ数」を制限（executor の workers とは別）
MAX_CONCURRENT_QUERIES = 4
query_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_QUERIES)


def prepare_irsa_session(pool_maxsize=50, max_retries=3, backoff_factor=1.0):
    """
    requests セッションを作って Irsa に流用（コネクションプールと retry 設定）
    
    Parameters:
    -----------
    pool_maxsize : int
        コネクションプールの最大サイズ
    max_retries : int
        最大リトライ回数
    backoff_factor : float
        リトライ間隔の係数
    
    Returns:
    --------
    requests.Session
        設定済みのセッション
    """
    session = requests.Session()
    retries = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(['GET', 'POST'])
    )
    adapter = HTTPAdapter(pool_connections=pool_maxsize, pool_maxsize=pool_maxsize, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # astroquery uses Irsa._session internally; set it so all queries reuse this session
    if ASTROQUERY_AVAILABLE:
        Irsa._session = session
    logging.info("Prepared Irsa._session with pool_maxsize=%s", pool_maxsize)
    return session


def create_neowise_database(db_path: str) -> sqlite3.Connection:
    """
    NEOWISE生データ用のSQLiteデータベースを作成
    
    Parameters:
    -----------
    db_path : str
        データベースファイルのパス
    
    Returns:
    --------
    sqlite3.Connection
        データベース接続
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # sourcesテーブル: 天体のメタデータ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT UNIQUE NOT NULL,
            ra REAL NOT NULL,
            dec REAL NOT NULL,
            allwise_cntr INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # neowise_raw_observationsテーブル: 生の観測データ（フラグ情報含む）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS neowise_raw_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            mjd REAL NOT NULL,
            band TEXT NOT NULL,
            
            -- 等級データ
            mpro REAL,
            sigmpro REAL,
            
            -- フラグ情報（動的フィルタリング用）
            cc_flags TEXT,
            ph_qual TEXT,
            moon_masked TEXT,
            sso_flg INTEGER,
            qi_fact REAL,
            saa_sep REAL,
            sat REAL,
            rchi2 REAL,
            qual_frame REAL,
            sky REAL,
            
            -- スキャン情報（ゼロポイント補正用）
            scan_id TEXT,
            
            -- 補正後の等級
            mpro_corrected REAL,
            
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        )
    ''')
    
    # neowise_epoch_summaryテーブル: エポックごとの集約データ
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS neowise_epoch_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            band TEXT NOT NULL,
            epoch_id INTEGER NOT NULL,
            mjd_mean INTEGER NOT NULL,
            mag_mean REAL,
            mag_se REAL,
            mag_lim REAL,
            n_points INTEGER,
            snr REAL,
            
            -- フィルタ設定（どのフィルタで集約したか）
            filter_applied TEXT,
            
            FOREIGN KEY (source_id) REFERENCES sources(source_id)
        )
    ''')
    
    # インデックス作成
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_source_id ON sources(source_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_source ON neowise_raw_observations(source_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_band ON neowise_raw_observations(band)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_raw_mjd ON neowise_raw_observations(mjd)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_epoch_source ON neowise_epoch_summary(source_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_epoch_band ON neowise_epoch_summary(band)')
    
    conn.commit()
    return conn


def clear_database(db_path: str) -> bool:
    """
    SQLiteデータベースの全データをクリア（テーブル構造は維持）
    
    Parameters:
    -----------
    db_path : str
        データベースファイルのパス
    
    Returns:
    --------
    bool
        成功した場合True
    """
    if not Path(db_path).exists():
        logging.warning(f"Database file not found: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 各テーブルのデータを削除
        tables = ['neowise_epoch_summary', 'neowise_raw_observations', 'sources']
        for table in tables:
            cursor.execute(f'DELETE FROM {table}')
            logging.info(f"Cleared table: {table}")
        
        # VACUUM で空き容量を回収
        conn.execute('VACUUM')
        conn.commit()
        conn.close()
        
        logging.info(f"Database cleared successfully: {db_path}")
        return True
    except Exception as e:
        logging.error(f"Error clearing database: {e}")
        return False


def drop_database(db_path: str) -> bool:
    """
    SQLiteデータベースファイルを削除
    
    Parameters:
    -----------
    db_path : str
        データベースファイルのパス
    
    Returns:
    --------
    bool
        成功した場合True
    """
    import os
    if Path(db_path).exists():
        os.remove(db_path)
        logging.info(f"Database file deleted: {db_path}")
        return True
    else:
        logging.warning(f"Database file not found: {db_path}")
        return False


def load_zp_stb(zp_stb_path: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    ゼロポイント補正テーブルを読み込む
    
    Parameters:
    -----------
    zp_stb_path : str, optional
        NEOWISE_zp_stb.csvのパス
    
    Returns:
    --------
    pd.DataFrame or None
        ゼロポイント補正テーブル
    """
    if zp_stb_path is None or not Path(zp_stb_path).exists():
        print("Warning: zp_stb file not found. Zero-point correction will be skipped.")
        return None
    
    try:
        zp_stb = pd.read_csv(zp_stb_path, skiprows=12).rename(columns={'scan': 'scan_id'})
        print(f"Loaded zp_stb with {len(zp_stb)} entries")
        return zp_stb
    except Exception as e:
        print(f"Error loading zp_stb: {e}")
        return None


def get_neowise_raw_data(
    ra: float, 
    dec: float, 
    source_id: str, 
    conn: sqlite3.Connection, 
    zp_stb_df: Optional[pd.DataFrame] = None,
    save_raw: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    NEOWISEの生データを取得し、SQLiteに保存する関数
    
    Parameters:
    -----------
    ra : float
        赤経（度）
    dec : float
        赤緯（度）
    source_id : str
        天体の識別子（Gaia SOURCE_ID推奨）
    conn : sqlite3.Connection
        SQLiteデータベース接続
    zp_stb_df : pd.DataFrame, optional
        ゼロポイント補正テーブル
    save_raw : bool
        生データを保存するかどうか（デフォルト: True）
    
    Returns:
    --------
    tuple
        (W1のDataFrame, W2のDataFrame) - エポック集約データ
    """
    
    if not ASTROQUERY_AVAILABLE:
        print(f"Skipping {source_id}: astroquery not available")
        return pd.DataFrame(), pd.DataFrame()
    
    cursor = conn.cursor()
    
    # 1. IRSAからデータを取得
    try:
        table = Irsa.query_region(
            coord.SkyCoord(ra, dec, unit=(u.deg, u.deg)), 
            catalog='neowiser_p1bs_psd', 
            radius='0d0m5s'
        )
        table.sort('mjd')
        raw_df = table.to_pandas()
    except Exception as e:
        print(f"Error querying IRSA for RA={ra}, DEC={dec}: {e}")
        return pd.DataFrame(), pd.DataFrame()

    if raw_df.empty:
        print(f"No data found for RA={ra}, DEC={dec}")
        return pd.DataFrame(), pd.DataFrame()
    
    # 複数オブジェクトのチェック
    if len(set(raw_df['allwise_cntr'])) != 1:
        print(f"Warning: Multiple objects found for RA={ra}, DEC={dec}")
        return pd.DataFrame(), pd.DataFrame()
    
    allwise_cntr = raw_df['allwise_cntr'].iloc[0]
    
    # 2. sourcesテーブルに登録
    cursor.execute('''
        INSERT OR IGNORE INTO sources (source_id, ra, dec, allwise_cntr)
        VALUES (?, ?, ?, ?)
    ''', (source_id, ra, dec, int(allwise_cntr)))
    
    # 3. mjdフィルタリング（zp_stb適用範囲のみ）
    if zp_stb_df is not None and not zp_stb_df.empty:
        raw_df = raw_df[raw_df['mjd'] > zp_stb_df['mjd'].min()].reset_index(drop=True)
    
    if raw_df.empty:
        print(f"No data after MJD filtering for source_id={source_id}")
        return pd.DataFrame(), pd.DataFrame()
    
    # 4. 生データをSQLiteに保存
    if save_raw:
        _save_raw_observations(raw_df, source_id, zp_stb_df, cursor)
    
    conn.commit()
    
    # 5. デフォルトフィルタでエポック集約データを計算・保存
    w1_result = _process_band_with_default_filter(raw_df.copy(), 'W1', source_id, zp_stb_df, cursor)
    w2_result = _process_band_with_default_filter(raw_df.copy(), 'W2', source_id, zp_stb_df, cursor)
    
    conn.commit()
    
    return w1_result, w2_result


def _save_raw_observations(
    raw_df: pd.DataFrame, 
    source_id: str, 
    zp_stb_df: Optional[pd.DataFrame], 
    cursor
):
    """
    生の観測データをSQLiteに保存
    """
    
    for band in ['W1', 'W2']:
        band_lower = band.lower()
        mag_col = f'{band_lower}mpro'
        unc_col = f'{band_lower}sigmpro'
        sat_col = f'{band_lower}sat'
        rchi2_col = f'{band_lower}rchi2'
        sky_col = f'{band_lower}sky'
        dmag_col = f'{band_lower}dmag'
        
        # バンドのデータを抽出
        band_df = raw_df.dropna(subset=[mag_col]).copy()
        
        if band_df.empty:
            continue
        
        # ゼロポイント補正値をマージ
        if zp_stb_df is not None and dmag_col in zp_stb_df.columns:
            band_df = band_df.merge(
                zp_stb_df[['scan_id', dmag_col]], 
                on='scan_id', 
                how='left'
            )
            band_df['mpro_corrected'] = band_df[mag_col] - band_df[dmag_col].fillna(0)
        else:
            band_df['mpro_corrected'] = band_df[mag_col]
        
        # SQLiteに挿入（等級データは小数点以下4桁に丸める）
        for _, row in band_df.iterrows():
            # mpro, sigmpro, mpro_corrected を小数点以下4桁に丸める
            mpro_rounded = round(row[mag_col], 4) if pd.notna(row[mag_col]) else None
            sigmpro_rounded = round(row[unc_col], 4) if pd.notna(row[unc_col]) else None
            mpro_corrected_rounded = round(row['mpro_corrected'], 4) if pd.notna(row['mpro_corrected']) else None
            
            cursor.execute('''
                INSERT INTO neowise_raw_observations 
                (source_id, mjd, band, mpro, sigmpro, cc_flags, ph_qual, moon_masked,
                 sso_flg, qi_fact, saa_sep, sat, rchi2, qual_frame, sky, scan_id, mpro_corrected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                source_id,
                row['mjd'],
                band,
                mpro_rounded,
                sigmpro_rounded,
                row.get('cc_flags', ''),
                row.get('ph_qual', ''),
                row.get('moon_masked', ''),
                int(row.get('sso_flg', 0)),
                row.get('qi_fact', 1.0),
                row.get('saa_sep', 0.0),
                row.get(sat_col, 0.0),
                row.get(rchi2_col, 0.0),
                row.get('qual_frame', 0.0),
                row.get(sky_col) if pd.notna(row.get(sky_col)) else None,
                row.get('scan_id', ''),
                mpro_corrected_rounded
            ))


def _process_band_with_default_filter(
    table_df: pd.DataFrame, 
    band: str, 
    source_id: str, 
    zp_stb_df: Optional[pd.DataFrame],
    cursor
) -> pd.DataFrame:
    """
    デフォルトフィルタを適用してエポック集約データを計算・保存
    """
    band_lower = band.lower()
    mag_col = f'{band_lower}mpro'
    unc_col = f'{band_lower}sigmpro'
    sat_col = f'{band_lower}sat'
    rchi2_col = f'{band_lower}rchi2'
    sky_col = f'{band_lower}sky'
    dmag_col = f'{band_lower}dmag'
    cc_flag_idx = 0 if band == 'W1' else 1
    ph_qual_idx = 0 if band == 'W1' else 1
    moon_mask_idx = 0 if band == 'W1' else 1
    
    table_band = table_df.dropna(subset=[mag_col]).copy()
    if table_band.empty:
        return pd.DataFrame()
    
    # デフォルトフィルタ適用
    try:
        table_filtered = table_band[
            (table_band['cc_flags'].str[cc_flag_idx] == '0') &
            (table_band['sso_flg'] == 0) &
            (table_band['qi_fact'] == 1.0) &
            (table_band['saa_sep'] >= 5.0) &
            (table_band['ph_qual'].str[ph_qual_idx] == 'A') &
            (table_band['moon_masked'].str[moon_mask_idx] == '0') &
            (table_band[sat_col] <= 0.05) &
            (table_band[rchi2_col] <= 50) &
            (table_band['qual_frame'] > 0.0) &
            (table_band[sky_col].notna())
        ].reset_index(drop=True).copy()
    except (KeyError, TypeError) as e:
        print(f"Warning: Filter error for {source_id} {band}: {e}")
        return pd.DataFrame()
    
    if table_filtered.empty:
        return pd.DataFrame()
    
    # ゼロポイント補正
    if zp_stb_df is not None and dmag_col in zp_stb_df.columns:
        table_filtered = table_filtered.merge(
            zp_stb_df[['scan_id', dmag_col]], 
            on='scan_id', 
            how='left'
        )
        table_filtered[mag_col] -= table_filtered[dmag_col].fillna(0)
    
    # 3σクリッピング
    mean_mag = table_filtered[mag_col].mean()
    std_mag = table_filtered[mag_col].std()
    if std_mag == 0 or np.isnan(std_mag):
        table_3sigma = table_filtered.copy()
    else:
        table_3sigma = table_filtered[
            (table_filtered[mag_col] >= (mean_mag - 3*std_mag)) &
            (table_filtered[mag_col] <= (mean_mag + 3*std_mag))
        ].copy()
    
    if table_3sigma.empty:
        return pd.DataFrame()
    
    # フラックス計算
    table_3sigma['flux'] = 10**(-0.4 * table_3sigma[mag_col])
    table_3sigma['flux_error'] = table_3sigma['flux'] * (10**(0.4 * table_3sigma[unc_col]) - 1)
    
    # エポックID付与
    table_3sigma['epoch_id'] = (table_3sigma['mjd'].diff() >= 100).cumsum()
    
    # S/N > 300 のエポックを抽出
    epoch_stats = table_3sigma.groupby('epoch_id').agg(
        flux_sum=('flux', 'sum'),
        flux_error_sq_sum=('flux_error', lambda x: (x**2).sum())
    )
    
    with np.errstate(divide='ignore', invalid='ignore'):
        epoch_stats['snr'] = epoch_stats['flux_sum'] / np.sqrt(epoch_stats['flux_error_sq_sum'])
    
    good_epoch_ids = epoch_stats[epoch_stats['snr'] >= 300].index
    if good_epoch_ids.empty:
        # SNR条件を緩和
        good_epoch_ids = epoch_stats[epoch_stats['snr'] >= 10].index
        if good_epoch_ids.empty:
            return pd.DataFrame()
    
    good_data = table_3sigma[table_3sigma['epoch_id'].isin(good_epoch_ids)].copy()
    
    # エポック集約
    def std_error(x):
        return np.std(x, ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0
    
    good_data = good_data.rename(columns={mag_col: 'magnitude', unc_col: 'magnitude_error'})
    
    result = good_data.groupby('epoch_id').agg(
        mjd=('mjd', 'mean'),
        mag_mean=('magnitude', 'mean'),
        mag_se=('magnitude', std_error),
        n_points=('mjd', 'size'),
        flux_mean=('flux', 'mean'),
        flux_error_sq_sum=('flux_error', lambda x: (x**2).sum()),
        flux_count=('flux', 'size')
    ).reset_index()
    
    # mag_lim計算
    with np.errstate(divide='ignore', invalid='ignore'):
        flux_mean = result['flux_mean']
        flux_error_sum = np.sqrt(result['flux_error_sq_sum'])
        n = result['flux_count']
        ratio = (flux_mean - flux_error_sum / n) / flux_mean
        result['mag_lim'] = -2.5 * np.log10(ratio)
    
    # SNRを追加
    result['snr'] = epoch_stats.loc[result['epoch_id'], 'snr'].values
    
    # 不要なカラムを削除
    result = result.drop(columns=['flux_mean', 'flux_error_sq_sum', 'flux_count'])
    result = result.sort_values('mjd').reset_index(drop=True)
    
    # SQLiteに保存（mjd_meanは整数、等級データは小数点以下4桁に丸める）
    for _, row in result.iterrows():
        # mjd_meanを整数に丸める
        mjd_mean_rounded = int(round(row['mjd']))
        # mag_mean, mag_se, mag_limを小数点以下4桁に丸める
        mag_mean_rounded = round(row['mag_mean'], 4) if pd.notna(row['mag_mean']) else None
        mag_se_rounded = round(row['mag_se'], 4) if pd.notna(row['mag_se']) else None
        mag_lim_rounded = round(row['mag_lim'], 4) if pd.notna(row['mag_lim']) and not np.isnan(row['mag_lim']) else None
        snr_rounded = round(row['snr'], 2) if pd.notna(row['snr']) and not np.isnan(row['snr']) else None
        
        cursor.execute('''
            INSERT INTO neowise_epoch_summary 
            (source_id, band, epoch_id, mjd_mean, mag_mean, mag_se, mag_lim, n_points, snr, filter_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            source_id,
            band,
            int(row['epoch_id']),
            mjd_mean_rounded,
            mag_mean_rounded,
            mag_se_rounded,
            mag_lim_rounded,
            int(row['n_points']),
            snr_rounded,
            'default'
        ))
    
    result['Source'] = source_id
    result['band'] = band
    
    print(f"Found {len(result)} good epochs for {band} band, source_id={source_id}")
    return result


def get_neowise_by_allwise_tap(
    allwise_id: str, 
    source_id: str, 
    ra: float,
    dec: float,
    conn: sqlite3.Connection, 
    zp_stb_df: Optional[pd.DataFrame] = None,
    save_raw: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    TAP（Table Access Protocol）を使用してAllWISE IDでNEOWISEデータを取得
    座標検索より高速（約2-5倍）
    
    Parameters:
    -----------
    allwise_id : str
        AllWISE ID（例: "J192843.67+193120.8"）
    source_id : str
        天体の識別子（Gaia SOURCE_ID推奨）
    ra : float
        赤経（度）- メタデータ用
    dec : float
        赤緯（度）- メタデータ用
    conn : sqlite3.Connection
        SQLiteデータベース接続
    zp_stb_df : pd.DataFrame, optional
        ゼロポイント補正テーブル
    save_raw : bool
        生データを保存するかどうか
    
    Returns:
    --------
    tuple
        (W1のDataFrame, W2のDataFrame) - エポック集約データ
    """
    
    if not ASTROQUERY_AVAILABLE:
        print(f"Skipping {source_id}: astroquery not available")
        return pd.DataFrame(), pd.DataFrame()
    
    cursor = conn.cursor()
    
    # TAP queryでAllWISE IDで直接検索
    try:
        # AllWISE IDから allwise_cntr を取得する方法
        # 注: AllWISE IDは "Jhhmmss.ss+ddmmss.s" 形式
        # neowiser_p1bs_psd テーブルの designation カラムで検索
        
        query = f"""
        SELECT * FROM neowiser_p1bs_psd 
        WHERE designation = '{allwise_id}'
        ORDER BY mjd
        """
        
        result = Irsa.query_tap(query)
        raw_df = result.to_pandas()
    except Exception as e:
        print(f"Error querying TAP for AllWISE_ID={allwise_id}: {e}")
        # フォールバック: 座標検索
        print(f"  Falling back to coordinate search...")
        return get_neowise_raw_data(ra, dec, source_id, conn, zp_stb_df, save_raw)

    if raw_df.empty:
        print(f"No data found for AllWISE_ID={allwise_id}")
        return pd.DataFrame(), pd.DataFrame()
    
    allwise_cntr = raw_df['allwise_cntr'].iloc[0] if 'allwise_cntr' in raw_df.columns else None
    
    # sourcesテーブルに登録
    with db_lock:
        cursor.execute('''
            INSERT OR IGNORE INTO sources (source_id, ra, dec, allwise_cntr)
            VALUES (?, ?, ?, ?)
        ''', (source_id, ra, dec, int(allwise_cntr) if allwise_cntr else None))
    
    # mjdフィルタリング
    if zp_stb_df is not None and not zp_stb_df.empty:
        raw_df = raw_df[raw_df['mjd'] > zp_stb_df['mjd'].min()].reset_index(drop=True)
    
    if raw_df.empty:
        print(f"No data after MJD filtering for source_id={source_id}")
        return pd.DataFrame(), pd.DataFrame()
    
    # 生データをSQLiteに保存
    if save_raw:
        with db_lock:
            _save_raw_observations(raw_df, source_id, zp_stb_df, cursor)
            conn.commit()
    
    # エポック集約データを計算・保存
    with db_lock:
        w1_result = _process_band_with_default_filter(raw_df.copy(), 'W1', source_id, zp_stb_df, cursor)
        w2_result = _process_band_with_default_filter(raw_df.copy(), 'W2', source_id, zp_stb_df, cursor)
        conn.commit()
    
    return w1_result, w2_result


def _process_single_source(
    args: tuple,
    zp_stb_df: Optional[pd.DataFrame],
    db_path: str,
    use_tap: bool = False,
    max_attempts: int = 4
) -> Tuple[str, bool, str]:
    """
    単一の天体を処理（並列処理用）
    セマフォによるクエリ数制限とリトライロジック付き
    
    Parameters:
    -----------
    args : tuple
        (source_id, ra, dec, [allwise_id]) のタプル
    zp_stb_df : pd.DataFrame
        ゼロポイント補正テーブル
    db_path : str
        データベースパス
    use_tap : bool
        TAPクエリを使用するか
    max_attempts : int
        最大リトライ回数
    
    Returns:
    --------
    tuple
        (source_id, success, message)
    """
    source_id = args[0]
    ra = args[1]
    dec = args[2]
    allwise_id = args[3] if len(args) > 3 else None
    
    logging.info(f"START source {source_id}")
    
    # 各スレッドで独自の接続を作成
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    
    for attempt in range(max_attempts):
        try:
            # セマフォでIRSAクエリ数を制限
            with query_semaphore:
                if use_tap and allwise_id:
                    w1_result, w2_result = get_neowise_by_allwise_tap(
                        allwise_id, source_id, ra, dec, conn, zp_stb_df, save_raw=True
                    )
                else:
                    w1_result, w2_result = get_neowise_raw_data(
                        ra, dec, source_id, conn, zp_stb_df, save_raw=True
                    )
            
            conn.close()
            
            if not w1_result.empty or not w2_result.empty:
                logging.info(f"SUCCESS source {source_id}")
                return (source_id, True, "Success")
            else:
                logging.warning(f"No valid data for source {source_id}")
                return (source_id, False, "No valid data")
                
        except Exception as e:
            if attempt < max_attempts - 1:
                wait_time = 2 ** attempt  # exponential backoff
                logging.warning(f"Attempt {attempt+1} failed for {source_id}: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                conn.close()
                logging.error(f"FAILED source {source_id} after {max_attempts} attempts: {e}")
                return (source_id, False, str(e))
    
    conn.close()
    return (source_id, False, "Max attempts exceeded")


def batch_process_sources_parallel(
    source_list: List[tuple], 
    db_path: str, 
    zp_stb_df: Optional[pd.DataFrame] = None,
    num_workers: int = 4,
    use_tap: bool = False
):
    """
    複数の天体を並列処理してSQLiteに保存
    
    Parameters:
    -----------
    source_list : list
        [(source_id, ra, dec, [allwise_id]), ...] のリスト
    db_path : str
        出力するSQLiteファイルのパス
    zp_stb_df : pd.DataFrame, optional
        ゼロポイント補正テーブル
    num_workers : int
        並列ワーカー数（デフォルト: 4）
    use_tap : bool
        TAPクエリを使用するか（AllWISE_IDが必要）
    """
    
    # データベース作成（メインスレッドで）
    conn = create_neowise_database(db_path)
    conn.close()
    
    # IRSAセッションの準備（コネクションプールとリトライ設定）
    prepare_irsa_session(pool_maxsize=num_workers * 2, max_retries=3, backoff_factor=1.0)
    
    print(f"Processing {len(source_list)} sources with {num_workers} workers...")
    if use_tap:
        print("Using TAP query (AllWISE ID search) - faster!")
    
    start_time = time.time()
    success_count = 0
    error_count = 0
    errors = []
    
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(
                _process_single_source, 
                source, 
                zp_stb_df, 
                db_path,
                use_tap
            ): source[0]
            for source in source_list
        }
        
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing"):
            source_id = futures[future]
            try:
                sid, success, msg = future.result()
                if success:
                    success_count += 1
                else:
                    error_count += 1
                    if msg != "No valid data":
                        errors.append(f"{sid}: {msg}")
            except Exception as e:
                error_count += 1
                errors.append(f"{source_id}: {str(e)}")
    
    elapsed_time = time.time() - start_time
    
    print(f"\n=== Summary ===")
    print(f"Database saved to: {db_path}")
    print(f"Successfully processed: {success_count}")
    print(f"Errors: {error_count}")
    print(f"Total time: {elapsed_time:.1f} seconds ({elapsed_time/len(source_list):.2f} sec/source)")
    
    if errors:
        print(f"\nFirst 10 errors:")
        for err in errors[:10]:
            print(f"  {err}")


def batch_process_sources(
    source_list: List[Tuple[str, float, float]], 
    db_path: str, 
    zp_stb_df: Optional[pd.DataFrame] = None
):
    """
    複数の天体を一括処理してSQLiteに保存（シーケンシャル処理）
    
    Parameters:
    -----------
    source_list : list
        [(source_id, ra, dec), ...] のリスト
    db_path : str
        出力するSQLiteファイルのパス
    zp_stb_df : pd.DataFrame, optional
        ゼロポイント補正テーブル
    """
    
    # データベース作成
    conn = create_neowise_database(db_path)
    
    print(f"Processing {len(source_list)} sources (sequential)...")
    
    start_time = time.time()
    success_count = 0
    error_count = 0
    
    for source_id, ra, dec in tqdm(source_list, desc="Processing sources"):
        try:
            w1_result, w2_result = get_neowise_raw_data(
                ra, dec, source_id, conn, zp_stb_df, save_raw=True
            )
            if not w1_result.empty or not w2_result.empty:
                success_count += 1
        except Exception as e:
            print(f"Error processing source_id={source_id}: {e}")
            error_count += 1
            continue
    
    conn.close()
    
    elapsed_time = time.time() - start_time
    
    print(f"\n=== Summary ===")
    print(f"Database saved to: {db_path}")
    print(f"Successfully processed: {success_count}")
    print(f"Errors: {error_count}")
    print(f"Total time: {elapsed_time:.1f} seconds ({elapsed_time/len(source_list):.2f} sec/source)")


def main():
    parser = argparse.ArgumentParser(
        description='NEOWISE生データを取得してSQLiteに保存'
    )
    parser.add_argument(
        '--sources', '-s',
        type=str,
        required=False,
        help='天体リストのCSVファイル (source_id,ra,dec[,AllWISE_ID])'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='neowise_lightcurves.db',
        help='出力するSQLiteファイルのパス'
    )
    parser.add_argument(
        '--zp-stb', '-z',
        type=str,
        default=None,
        help='NEOWISE_zp_stb.csvのパス'
    )
    parser.add_argument(
        '--parallel', '-p',
        action='store_true',
        help='並列処理を有効にする（大幅な高速化）'
    )
    parser.add_argument(
        '--workers', '-w',
        type=int,
        default=4,
        help='並列ワーカー数（デフォルト: 4）'
    )
    parser.add_argument(
        '--use-tap',
        action='store_true',
        help='TAP検索を使用（AllWISE_IDカラムが必要、高速）'
    )
    parser.add_argument(
        '--clear',
        action='store_true',
        help='データベースの全データをクリア（再実行前に使用）'
    )
    parser.add_argument(
        '--drop',
        action='store_true',
        help='データベースファイルを削除'
    )
    
    args = parser.parse_args()
    
    # データベースクリア処理
    if args.clear:
        clear_database(args.output)
        if not args.sources:
            return
    
    # データベース削除処理
    if args.drop:
        drop_database(args.output)
        if not args.sources:
            return
    
    # sources引数が必要
    if not args.sources:
        print("Error: --sources is required for data processing")
        print("       Use --clear or --drop alone to manage the database")
        return
    
    # 天体リストを読み込み
    sources_df = pd.read_csv(args.sources)
    required_cols = ['source_id', 'ra', 'dec']
    
    for col in required_cols:
        if col not in sources_df.columns:
            print(f"Error: '{col}' column not found in {args.sources}")
            return
    
    # AllWISE_IDカラムの有無をチェック
    has_allwise_id = 'AllWISE_ID' in sources_df.columns
    
    if args.use_tap and not has_allwise_id:
        print("Warning: --use-tap specified but 'AllWISE_ID' column not found.")
        print("         Falling back to coordinate search.")
        args.use_tap = False
    
    # ソースリスト作成
    if has_allwise_id:
        source_list = [
            (str(row['source_id']), float(row['ra']), float(row['dec']), str(row['AllWISE_ID']))
            for _, row in sources_df.iterrows()
        ]
    else:
        source_list = [
            (str(row['source_id']), float(row['ra']), float(row['dec']))
            for _, row in sources_df.iterrows()
        ]
    
    # ゼロポイント補正テーブルを読み込み
    zp_stb_df = load_zp_stb(args.zp_stb)
    
    # 処理実行
    if args.parallel:
        batch_process_sources_parallel(
            source_list, 
            args.output, 
            zp_stb_df,
            num_workers=args.workers,
            use_tap=args.use_tap
        )
    else:
        # シーケンシャル処理（従来方式）
        simple_source_list = [(s[0], s[1], s[2]) for s in source_list]
        batch_process_sources(simple_source_list, args.output, zp_stb_df)



if __name__ == "__main__":
    main()
