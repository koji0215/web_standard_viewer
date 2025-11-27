# NEOWISE 生データ取得・SQLite出力スクリプト

## 概要

このドキュメントでは、NEOWISEの生データを取得し、フラグによるフィルタリングを後から行えるようにSQLiteデータベースに保存する方法を説明します。

## 修正版コード

以下のコードは、元の`get_w1_w2_timeseries_2`関数を修正し、以下の機能を追加しています：

1. **生データの保存**: フィルタリング前の全観測データを保存
2. **フラグ情報の保持**: `cc_flags`, `ph_qual`, `moon_masked`などのフラグを保存
3. **SQLite出力**: 大量データに対応するためSQLite形式で出力
4. **動的フィルタリング対応**: ビューワー側でフラグによるフィルタリングが可能

```python
import pandas as pd
import numpy as np
import sqlite3
from pathlib import Path
from astroquery.ipac.irsa import Irsa
import astropy.coordinates as coord
import astropy.units as u
from tqdm import tqdm

# zp_stbの読み込み
zp_stb = pd.read_csv('/Users/yukikojima/Downloads/NEOWISE_zp_stb.csv', skiprows=12).rename(columns={'scan': 'scan_id'})


def create_neowise_database(db_path: str):
    """
    NEOWISE生データ用のSQLiteデータベースを作成
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
            
            -- 補正後の等級（オプション）
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
            mjd_mean REAL NOT NULL,
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


def get_neowise_raw_data(ra: float, dec: float, source_id: str, conn: sqlite3.Connection, 
                         zp_stb_df: pd.DataFrame = zp_stb, save_raw: bool = True):
    """
    NEOWISEの生データを取得し、SQLiteに保存する関数。
    
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
    zp_stb_df : pd.DataFrame
        ゼロポイント補正テーブル
    save_raw : bool
        生データを保存するかどうか（デフォルト: True）
    
    Returns:
    --------
    tuple
        (W1のDataFrame, W2のDataFrame) - エポック集約データ
    """
    
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


def _save_raw_observations(raw_df: pd.DataFrame, source_id: str, 
                           zp_stb_df: pd.DataFrame, cursor):
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
        cc_flag_idx = 0 if band == 'W1' else 1
        
        # バンドのデータを抽出
        band_df = raw_df.dropna(subset=[mag_col]).copy()
        
        if band_df.empty:
            continue
        
        # ゼロポイント補正値をマージ
        if zp_stb_df is not None:
            band_df = band_df.merge(
                zp_stb_df[['scan_id', dmag_col]], 
                on='scan_id', 
                how='left'
            )
            band_df['mpro_corrected'] = band_df[mag_col] - band_df[dmag_col].fillna(0)
        else:
            band_df['mpro_corrected'] = band_df[mag_col]
        
        # SQLiteに挿入
        for _, row in band_df.iterrows():
            cursor.execute('''
                INSERT INTO neowise_raw_observations 
                (source_id, mjd, band, mpro, sigmpro, cc_flags, ph_qual, moon_masked,
                 sso_flg, qi_fact, saa_sep, sat, rchi2, qual_frame, sky, scan_id, mpro_corrected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                source_id,
                row['mjd'],
                band,
                row[mag_col],
                row[unc_col],
                row['cc_flags'],
                row['ph_qual'],
                row['moon_masked'],
                int(row['sso_flg']),
                row['qi_fact'],
                row['saa_sep'],
                row[sat_col],
                row[rchi2_col],
                row['qual_frame'],
                row[sky_col] if pd.notna(row[sky_col]) else None,
                row['scan_id'],
                row['mpro_corrected']
            ))


def _process_band_with_default_filter(table_df: pd.DataFrame, band: str, 
                                       source_id: str, zp_stb_df: pd.DataFrame,
                                       cursor) -> pd.DataFrame:
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
    
    if table_filtered.empty:
        return pd.DataFrame()
    
    # ゼロポイント補正
    if zp_stb_df is not None:
        table_filtered = table_filtered.merge(
            zp_stb_df[['scan_id', dmag_col]], 
            on='scan_id', 
            how='left'
        )
        table_filtered[mag_col] -= table_filtered[dmag_col].fillna(0)
    
    # 3σクリッピング
    mean_mag = table_filtered[mag_col].mean()
    std_mag = table_filtered[mag_col].std()
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
    
    # SQLiteに保存
    for _, row in result.iterrows():
        cursor.execute('''
            INSERT INTO neowise_epoch_summary 
            (source_id, band, epoch_id, mjd_mean, mag_mean, mag_se, mag_lim, n_points, snr, filter_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            source_id,
            band,
            int(row['epoch_id']),
            row['mjd'],
            row['mag_mean'],
            row['mag_se'],
            row['mag_lim'],
            int(row['n_points']),
            row['snr'],
            'default'  # フィルタ設定の識別子
        ))
    
    result['Source'] = source_id
    result['band'] = band
    
    print(f"Found {len(result)} good epochs for {band} band, source_id={source_id}")
    return result


def batch_process_sources(source_list: list, db_path: str, zp_stb_df: pd.DataFrame = zp_stb):
    """
    複数の天体を一括処理してSQLiteに保存
    
    Parameters:
    -----------
    source_list : list
        [(source_id, ra, dec), ...] のリスト
    db_path : str
        出力するSQLiteファイルのパス
    zp_stb_df : pd.DataFrame
        ゼロポイント補正テーブル
    """
    
    # データベース作成
    conn = create_neowise_database(db_path)
    
    print(f"Processing {len(source_list)} sources...")
    
    for source_id, ra, dec in tqdm(source_list):
        try:
            get_neowise_raw_data(ra, dec, source_id, conn, zp_stb_df, save_raw=True)
        except Exception as e:
            print(f"Error processing source_id={source_id}: {e}")
            continue
    
    conn.close()
    print(f"Database saved to: {db_path}")


# 使用例
if __name__ == "__main__":
    # 例: 複数の天体を処理
    sources = [
        ("4515624509348164608", 292.181969, 19.522439),
        ("5972956420926034944", 251.354, -46.196),
        # ... 他の天体
    ]
    
    batch_process_sources(sources, "neowise_lightcurves.db")
```

## データベース構造

### 1. sourcesテーブル
天体のメタデータを保存。

| カラム | 型 | 説明 |
|--------|-----|------|
| `source_id` | TEXT | 天体識別子（Gaia SOURCE_ID） |
| `ra` | REAL | 赤経（度） |
| `dec` | REAL | 赤緯（度） |
| `allwise_cntr` | INTEGER | AllWISE カウンター |

### 2. neowise_raw_observationsテーブル
**生の観測データ**（フィルタリング前）を保存。ビューワーでの動的フィルタリングに使用。

| カラム | 型 | 説明 |
|--------|-----|------|
| `source_id` | TEXT | 天体識別子 |
| `mjd` | REAL | 修正ユリウス日 |
| `band` | TEXT | バンド（W1/W2） |
| `mpro` | REAL | 生の等級 |
| `sigmpro` | REAL | 等級誤差 |
| `cc_flags` | TEXT | 汚染フラグ（4文字） |
| `ph_qual` | TEXT | 測光品質フラグ |
| `moon_masked` | TEXT | 月マスクフラグ |
| `sso_flg` | INTEGER | 太陽系天体フラグ |
| `qi_fact` | REAL | 品質指標 |
| `saa_sep` | REAL | SAA離角 |
| `sat` | REAL | 飽和度 |
| `rchi2` | REAL | 縮小カイ二乗 |
| `qual_frame` | REAL | フレーム品質 |
| `sky` | REAL | 空の背景値 |
| `scan_id` | TEXT | スキャンID |
| `mpro_corrected` | REAL | ゼロポイント補正後の等級 |

### 3. neowise_epoch_summaryテーブル
デフォルトフィルタ適用後の**エポック集約データ**を保存。

| カラム | 型 | 説明 |
|--------|-----|------|
| `source_id` | TEXT | 天体識別子 |
| `band` | TEXT | バンド（W1/W2） |
| `epoch_id` | INTEGER | エポックID |
| `mjd_mean` | REAL | 平均MJD |
| `mag_mean` | REAL | 平均等級 |
| `mag_se` | REAL | 標準誤差 |
| `mag_lim` | REAL | 等級リミット |
| `n_points` | INTEGER | データ点数 |
| `snr` | REAL | S/N比 |
| `filter_applied` | TEXT | 適用したフィルタ設定 |

## ビューワーでの動的フィルタリング

### バックエンドAPI例

```python
from fastapi import FastAPI, Query
from typing import Optional

app = FastAPI()

@app.get("/api/neowise/raw/{source_id}")
def get_raw_data(
    source_id: str,
    band: Optional[str] = None,
    cc_flags_filter: Optional[str] = "0",  # デフォルト: cc_flags[0] == '0'
    ph_qual_filter: Optional[str] = "A",   # デフォルト: ph_qual == 'A'
    sso_flg: Optional[int] = 0,            # デフォルト: sso_flg == 0
    sat_max: Optional[float] = 0.05,       # デフォルト: sat <= 0.05
    rchi2_max: Optional[float] = 50,       # デフォルト: rchi2 <= 50
):
    """
    生データを動的フィルタリングして返すAPI
    """
    conn = sqlite3.connect("neowise_lightcurves.db")
    
    query = """
        SELECT mjd, band, mpro_corrected as mag, sigmpro as mag_err,
               cc_flags, ph_qual, sso_flg, sat, rchi2
        FROM neowise_raw_observations
        WHERE source_id = ?
    """
    params = [source_id]
    
    if band:
        query += " AND band = ?"
        params.append(band)
    
    if cc_flags_filter:
        query += " AND (cc_flags LIKE ? OR cc_flags LIKE ?)"
        params.extend([f"{cc_flags_filter}%", f"_{cc_flags_filter}%"])
    
    if sso_flg is not None:
        query += " AND sso_flg = ?"
        params.append(sso_flg)
    
    if sat_max is not None:
        query += " AND sat <= ?"
        params.append(sat_max)
    
    if rchi2_max is not None:
        query += " AND rchi2 <= ?"
        params.append(rchi2_max)
    
    query += " ORDER BY mjd"
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    return df.to_dict(orient='records')
```

### フロントエンドでのフィルタ設定UI

```html
<div class="filter-controls">
    <h3>フィルタ設定</h3>
    
    <label>
        <input type="checkbox" id="cc_flags_filter" checked>
        cc_flags フィルタ (汚染なし)
    </label>
    
    <label>
        <input type="checkbox" id="ph_qual_filter" checked>
        ph_qual = 'A' (高品質)
    </label>
    
    <label>
        <input type="checkbox" id="sso_filter" checked>
        太陽系天体除外
    </label>
    
    <label>
        飽和度上限: 
        <input type="number" id="sat_max" value="0.05" step="0.01">
    </label>
    
    <label>
        rchi2上限:
        <input type="number" id="rchi2_max" value="50" step="1">
    </label>
    
    <button onclick="applyFilters()">フィルタ適用</button>
    <button onclick="resetFilters()">デフォルトに戻す</button>
</div>
```

## ファイルサイズ見積もり

| 項目 | データ量 | 推定サイズ |
|------|---------|-----------|
| 1天体あたりの生データ | 〜500観測点 | 〜50 KB |
| 10,000天体の生データ | 500万観測点 | 〜500 MB |
| エポック集約データ | 〜40エポック/天体 | 〜40 MB |
| **合計（10,000天体）** | - | **〜540 MB** |

## 次のステップ

1. **このスクリプトを実行**して、手持ちのデータをSQLiteに変換
2. **バックエンドAPI**を動的フィルタリング対応に更新
3. **フロントエンドUI**にフィルタ設定パネルを追加
4. **デフォルト表示**は生データ、ユーザーの設定に応じてフィルタリング

ご質問があればお知らせください。
