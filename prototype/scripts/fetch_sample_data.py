#!/usr/bin/env python3
"""
サンプルデータ取得スクリプト

BrightKg_WISE_unique.csvから100個の星を選び、
NEOWISEとASASSNのライトカーブデータを取得してJSONで保存する
"""

import pandas as pd
import json
import os
import time
import random
from pathlib import Path

# astroqueryとpyasassnのインポート（エラーハンドリング付き）
try:
    from astroquery.ipac.irsa import Irsa
    import astropy.coordinates as coord
    import astropy.units as u
    NEOWISE_AVAILABLE = True
except ImportError:
    print("Warning: astroquery not available. NEOWISE data will be simulated.")
    NEOWISE_AVAILABLE = False

try:
    from pyasassn.client import SkyPatrolClient
    ASASSN_AVAILABLE = True
except ImportError:
    print("Warning: pyasassn not available. ASASSN data will be simulated.")
    ASASSN_AVAILABLE = False

import numpy as np


def select_sample_stars(catalog_path, num_stars=100):
    """
    カタログから指定数の星をランダムに選択
    """
    print(f"Reading catalog from {catalog_path}...")
    df = pd.read_csv(catalog_path)
    
    # 明るい星を優先（W1magが10-14の範囲）
    if 'W1mag' in df.columns:
        df_filtered = df[(df['W1mag'] > 10) & (df['W1mag'] < 14)].copy()
        if len(df_filtered) < num_stars:
            df_filtered = df.copy()
    else:
        df_filtered = df.copy()
    
    # ランダムサンプリング
    if len(df_filtered) > num_stars:
        sample = df_filtered.sample(n=num_stars, random_state=42)
    else:
        sample = df_filtered
    
    print(f"Selected {len(sample)} stars")
    return sample


def fetch_neowise_data(ra, dec, source_id):
    """
    NEOWISEデータを取得
    """
    if not NEOWISE_AVAILABLE:
        return generate_dummy_neowise_data()
    
    try:
        print(f"  Fetching NEOWISE data for {source_id}...")
        Irsa.TIMEOUT = 60
        
        table = Irsa.query_region(
            coord.SkyCoord(ra, dec, unit=(u.deg, u.deg)),
            catalog='neowiser_p1bs_psd',
            radius=5 * u.arcsec
        )
        
        if table is None or len(table) == 0:
            print(f"    No NEOWISE data found")
            return None
        
        # データを整形
        observations = []
        for row in table:
            obs = {
                "mjd": float(row['mjd']) if 'mjd' in row.colnames else 0.0,
                "w1_mag": float(row['w1mpro']) if 'w1mpro' in row.colnames else None,
                "w1_err": float(row['w1sigmpro']) if 'w1sigmpro' in row.colnames else None,
                "w2_mag": float(row['w2mpro']) if 'w2mpro' in row.colnames else None,
                "w2_err": float(row['w2sigmpro']) if 'w2sigmpro' in row.colnames else None
            }
            # Noneや無効な値をスキップ
            if obs['w1_mag'] and obs['w2_mag'] and not np.isnan(obs['w1_mag']) and not np.isnan(obs['w2_mag']):
                observations.append(obs)
        
        print(f"    Found {len(observations)} observations")
        return observations
        
    except Exception as e:
        print(f"    Error: {e}")
        return None


def fetch_asassn_data(ra, dec, source_id, gaia_id=None):
    """
    ASASSNデータを取得
    """
    if not ASASSN_AVAILABLE:
        return generate_dummy_asassn_data()
    
    try:
        print(f"  Fetching ASASSN data for {source_id}...")
        client = SkyPatrolClient()
        
        # 座標検索（3秒角）
        radius_deg = 3.0 / 3600.0
        lcs = client.cone_search(
            ra_deg=ra,
            dec_deg=dec,
            radius=radius_deg,
            download=True,
            threads=1
        )
        
        if lcs is None or len(lcs) == 0:
            print(f"    No ASASSN data found")
            return None
        
        # ライトカーブデータを整形
        observations = []
        for lc in lcs:
            if hasattr(lc, '__len__'):
                for point in lc:
                    obs = {
                        "mjd": float(point.get('jd', 0) - 2400000.5),  # JDからMJDに変換
                        "mag": float(point.get('mag', 0)),
                        "mag_err": float(point.get('mag_err', 0)),
                        "band": str(point.get('band', 'V'))
                    }
                    if obs['mag'] > 0 and obs['mag'] < 30:  # 有効な等級のみ
                        observations.append(obs)
        
        print(f"    Found {len(observations)} observations")
        return observations
        
    except Exception as e:
        print(f"    Error: {e}")
        return None


def generate_dummy_neowise_data():
    """
    ダミーのNEOWISEデータを生成（テスト用）
    """
    num_obs = random.randint(30, 100)
    mjd_start = 55197.0  # 2010-01-01
    mjd_end = 59945.0     # 2023-01-01
    mjds = sorted(np.random.uniform(mjd_start, mjd_end, num_obs))
    
    w1_mean = np.random.uniform(11.0, 13.0)
    w1_rms = np.random.uniform(0.02, 0.1)
    w2_mean = w1_mean + np.random.uniform(-0.3, 0.3)
    w2_rms = np.random.uniform(0.02, 0.1)
    
    observations = []
    for mjd in mjds:
        observations.append({
            "mjd": float(mjd),
            "w1_mag": float(w1_mean + np.random.normal(0, w1_rms)),
            "w1_err": float(np.random.uniform(0.02, 0.05)),
            "w2_mag": float(w2_mean + np.random.normal(0, w2_rms)),
            "w2_err": float(np.random.uniform(0.02, 0.05))
        })
    
    return observations


def generate_dummy_asassn_data():
    """
    ダミーのASASSNデータを生成（テスト用）
    """
    num_obs = random.randint(50, 200)
    mjd_start = 56658.0  # 2014-01-01
    mjd_end = 59945.0     # 2023-01-01
    mjds = sorted(np.random.uniform(mjd_start, mjd_end, num_obs))
    
    v_mean = np.random.uniform(12.0, 15.0)
    v_rms = np.random.uniform(0.05, 0.2)
    g_mean = v_mean + np.random.uniform(-0.5, 0.5)
    
    observations = []
    bands = ['V', 'g']
    for mjd in mjds:
        band = random.choice(bands)
        mean_mag = v_mean if band == 'V' else g_mean
        observations.append({
            "mjd": float(mjd),
            "mag": float(mean_mag + np.random.normal(0, v_rms)),
            "mag_err": float(np.random.uniform(0.05, 0.15)),
            "band": band
        })
    
    return observations


def main():
    """
    メイン処理
    """
    # パスの設定
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent.parent
    catalog_path = project_dir / "BrightKg_WISE_unique.csv"
    output_dir = script_dir.parent / "data"
    
    print("="*60)
    print("NEOWISE/ASASSN Sample Data Fetcher")
    print("="*60)
    
    # 出力ディレクトリを作成
    neowise_dir = output_dir / "neowise"
    asassn_dir = output_dir / "asassn"
    neowise_dir.mkdir(parents=True, exist_ok=True)
    asassn_dir.mkdir(parents=True, exist_ok=True)
    
    # サンプル星を選択
    sample_stars = select_sample_stars(catalog_path, num_stars=100)
    
    # 各星のデータを取得
    neowise_count = 0
    asassn_count = 0
    
    for idx, row in sample_stars.iterrows():
        source_id = row.get('SOURCE_ID', f"star_{idx}")
        ra = row['ra']
        dec = row['dec']
        allwise_id = row.get('AllWISE', '')
        gaia_id = row.get('SOURCE_ID', '')
        
        print(f"\n[{neowise_count + asassn_count + 1}/{len(sample_stars)}] Processing {source_id}")
        print(f"  RA: {ra:.6f}, Dec: {dec:.6f}")
        
        # NEOWISE データ取得
        neowise_data = fetch_neowise_data(ra, dec, source_id)
        if neowise_data and len(neowise_data) > 0:
            output_file = neowise_dir / f"{source_id}.json"
            with open(output_file, 'w') as f:
                json.dump({
                    "source_id": str(source_id),
                    "ra": float(ra),
                    "dec": float(dec),
                    "allwise_id": str(allwise_id),
                    "num_observations": len(neowise_data),
                    "observations": neowise_data
                }, f, indent=2)
            neowise_count += 1
        
        # ASASSN データ取得
        asassn_data = fetch_asassn_data(ra, dec, source_id, gaia_id)
        if asassn_data and len(asassn_data) > 0:
            output_file = asassn_dir / f"{source_id}.json"
            with open(output_file, 'w') as f:
                json.dump({
                    "source_id": str(source_id),
                    "ra": float(ra),
                    "dec": float(dec),
                    "gaia_id": str(gaia_id),
                    "num_observations": len(asassn_data),
                    "observations": asassn_data
                }, f, indent=2)
            asassn_count += 1
        
        # レート制限対策
        time.sleep(0.5)
    
    print("\n" + "="*60)
    print(f"Data fetching completed!")
    print(f"NEOWISE: {neowise_count} files saved to {neowise_dir}")
    print(f"ASASSN: {asassn_count} files saved to {asassn_dir}")
    print("="*60)


if __name__ == "__main__":
    main()
