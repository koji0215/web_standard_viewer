# neowise_threadsafe.py
import logging
import sqlite3
import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# astro imports
import astropy.coordinates as coord
import astropy.units as u
from astroquery.irsa import Irsa
import pyvo
from pyvo.dal import exceptions as pyvo_exceptions

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# DB ロック（sqlite はスレッドセーフでないので必要）
db_lock = threading.Lock()

# セマフォで「同時に発行する IRSA クエリ数」を制限（executor の workers とは別）
MAX_CONCURRENT_QUERIES = 4
query_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_QUERIES)

# requests セッションを作って Irsa に流用（コネクションプールと retry 設定）
def prepare_irsa_session(pool_maxsize=50, max_retries=3, backoff_factor=1.0):
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
    Irsa._session = session
    logging.info("Prepared Irsa._session with pool_maxsize=%s", pool_maxsize)
    return session

# 実際のワーカー
def get_neowise_threadsafe(ra, dec, source_id, db_path, zp_stb_df, max_attempts=4):
    logging.info(f"START source {source_id}")
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    cursor = conn.cursor()

    # query_region を semaphore で保護して同時実行数を制限
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            with query_semaphore:
                table = Irsa.query_region(
                    coord.SkyCoord(ra, dec, unit=(u.deg, u.deg)),
                    catalog='neowiser_p1bs_psd',
                    radius='0d0m5s',
                    columns="ra,dec,allwise_cntr,w1mpro,w1sigmpro,w1rchi2,w1sat,w1sky,w2mpro,w2sigmpro,w2rchi2,w2sat,w2sky,cc_flags,sso_flg,qi_fact,ph_qual,qual_frame,moon_masked,saa_sep,mjd,scan_id"
                )
            # 成功すればループを抜ける
            break
        except (pyvo_exceptions.DALFormatError, requests.exceptions.RequestException, ConnectionError, Exception) as e:
            logging.warning("source %s attempt %d/%d failed: %s", source_id, attempt, max_attempts, e)
            if attempt >= max_attempts:
                conn.close()
                logging.exception("source %s - query/extract failed", source_id)
                return (source_id, False, str(e))
            # 指数バックオフ（jitter を入れるとより安全）
            sleep_time = (2 ** (attempt - 1)) + (0.1 * (attempt))
            logging.info("sleeping %.1f s before retry", sleep_time)
            time.sleep(sleep_time)

    # 以降は元の処理（例: table.sort, to_pandas など）
    try:
        table.sort('mjd')
        table['allwise_cntr'] = table['allwise_cntr'].astype(str)
        raw_df = table.to_pandas()
    except Exception as e:
        conn.close()
        return (source_id, False, f"parse failed: {e}")

    if raw_df.empty:
        conn.close()
        return (source_id, False, "No valid data")

    try:
        if len(set(raw_df['allwise_cntr'])) != 1:
            mf = raw_df['allwise_cntr'].value_counts().idxmax()
            raw_df = raw_df[raw_df['allwise_cntr'] == mf].reset_index(drop=True)
        allwise_cntr = raw_df['allwise_cntr'].iloc[0]

        with db_lock:
            cursor.execute('INSERT OR IGNORE INTO sources (source_id, ra, dec, allwise_cntr) VALUES (?, ?, ?, ?)',
                           (source_id, ra, dec, int(allwise_cntr)))
            conn.commit()

        if zp_stb_df is not None and not zp_stb_df.empty:
            raw_df = raw_df[raw_df['mjd'] > zp_stb_df['mjd'].min()].reset_index(drop=True)

        if raw_df.empty:
            conn.close()
            return (source_id, False, "No data after MJD filtering")

        with db_lock:
            save_raw_observations(raw_df, source_id, zp_stb_df, cursor)
            process_band_and_save_epochs(raw_df.copy(), 'W1', source_id, zp_stb_df, cursor)
            process_band_and_save_epochs(raw_df.copy(), 'W2', source_id, zp_stb_df, cursor)
            conn.commit()
    except Exception as e:
        logging.exception("source %s - processing failed", source_id)
        conn.close()
        return (source_id, False, str(e))

    conn.close()
    logging.info(f"END source {source_id}")
    return (source_id, True, "Success")


# 実行時の準備例
if __name__ == "__main__":
    db_path = "neowise_target_region_2.db"
    conn = create_neowise_database(db_path)
    conn.close()

    # セッション準備（pool を必要に応じて増やす）
    prepare_irsa_session(pool_maxsize=50, max_retries=3, backoff_factor=1.0)

    num_workers = 4  # 必要なら 2 に落とすと成功率が上がることが多い
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(get_neowise_threadsafe, ra, dec, source_id, db_path, zp_stb): source_id
            for source_id, ra, dec in sources
        }
        for future in as_completed(list(futures.keys())):
            try:
                sid, success, msg = future.result()
            except Exception as e:
                logging.exception("Worker exception")
                sid = futures.get(future)
                print(sid, "EXCEPTION", e)
                continue
            if not success:
                print(sid, "FAILED:", msg)
    logging.info("完了!")
