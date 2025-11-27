#!/usr/bin/env python3
"""
NEOWISE 生データ取得・SQLite出力スクリプト

このスクリプトは、NEOWISEの生データを取得し、フラグによる動的フィルタリングを
可能にするためにSQLiteデータベースに保存します。

使用方法:
    python neowise_to_sqlite.py --sources sources.csv --output neowise_lightcurves.db

sources.csvの形式:
    source_id,ra,dec
    4515624509348164608,292.181969,19.522439
    5972956420926034944,251.354,-46.196
"""

import pandas as pd
import numpy as np
import sqlite3
import argparse
from pathlib import Path
from typing import Optional, Tuple, List

# astroqueryは実行環境で利用可能な場合のみインポート
try:
    from astroquery.ipac.irsa import Irsa
    import astropy.coordinates as coord
    import astropy.units as u
    ASTROQUERY_AVAILABLE = True
except ImportError:
    ASTROQUERY_AVAILABLE = False
    print("Warning: astroquery not available. Using mock data for testing.")

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, **kwargs):
        return x


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


def batch_process_sources(
    source_list: List[Tuple[str, float, float]], 
    db_path: str, 
    zp_stb_df: Optional[pd.DataFrame] = None
):
    """
    複数の天体を一括処理してSQLiteに保存
    
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
    
    print(f"Processing {len(source_list)} sources...")
    
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
    
    print(f"\n=== Summary ===")
    print(f"Database saved to: {db_path}")
    print(f"Successfully processed: {success_count}")
    print(f"Errors: {error_count}")


def main():
    parser = argparse.ArgumentParser(
        description='NEOWISE生データを取得してSQLiteに保存'
    )
    parser.add_argument(
        '--sources', '-s',
        type=str,
        required=True,
        help='天体リストのCSVファイル (source_id,ra,dec)'
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
    
    args = parser.parse_args()
    
    # 天体リストを読み込み
    sources_df = pd.read_csv(args.sources)
    required_cols = ['source_id', 'ra', 'dec']
    
    for col in required_cols:
        if col not in sources_df.columns:
            print(f"Error: '{col}' column not found in {args.sources}")
            return
    
    source_list = [
        (str(row['source_id']), float(row['ra']), float(row['dec']))
        for _, row in sources_df.iterrows()
    ]
    
    # ゼロポイント補正テーブルを読み込み
    zp_stb_df = load_zp_stb(args.zp_stb)
    
    # 一括処理
    batch_process_sources(source_list, args.output, zp_stb_df)


if __name__ == "__main__":
    main()
