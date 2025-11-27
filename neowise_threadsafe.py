# neowise_threadsafe.py
"""
Thread-safe NEOWISE data retrieval with robust retry logic for IRSA/astroquery TAP queries.

This module provides resilient querying of NEOWISE data from IRSA with:
- Connection pooling and automatic retry via requests.Session
- Semaphore-based concurrency limiting
- Exponential backoff on failures
- Thread-safe SQLite database operations

External dependencies (must be imported or defined before use):
- create_neowise_database: Function to create/initialize the database
- save_raw_observations: Function to save raw observation data
- process_band_and_save_epochs: Function to process band data and save epochs

Tuning guidance:
- num_workers: Number of ThreadPoolExecutor workers (default 4, reduce to 2 for higher success rate)
- MAX_CONCURRENT_QUERIES: Concurrent IRSA query limit (default 4)
- max_attempts: Retry attempts per query (default 4)
- pool_maxsize: Connection pool size (default 50)
"""
import logging
import sqlite3
import threading
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Astronomy imports
import astropy.coordinates as coord
import astropy.units as u
from astroquery.irsa import Irsa
import pyvo
from pyvo.dal import exceptions as pyvo_exceptions

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# DB lock (required because sqlite is not fully thread-safe)
db_lock = threading.Lock()

# Semaphore to limit concurrent IRSA queries (separate from executor workers)
MAX_CONCURRENT_QUERIES = 4
query_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_QUERIES)

# Create requests session for Irsa (connection pooling and retry settings)
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

# Main worker function
def get_neowise_threadsafe(ra, dec, source_id, db_path, zp_stb_df, max_attempts=4):
    logging.info(f"START source {source_id}")
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
    cursor = conn.cursor()

    # Protect query_region with semaphore to limit concurrent requests
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
            # Success - exit retry loop
            break
        except (pyvo_exceptions.DALFormatError, requests.exceptions.RequestException, ConnectionError, Exception) as e:
            logging.warning("source %s attempt %d/%d failed: %s", source_id, attempt, max_attempts, e)
            if attempt >= max_attempts:
                conn.close()
                logging.exception("source %s - query/extract failed", source_id)
                return (source_id, False, str(e))
            # Exponential backoff (add jitter for better safety)
            sleep_time = (2 ** (attempt - 1)) + (0.1 * (attempt))
            logging.info("sleeping %.1f s before retry", sleep_time)
            time.sleep(sleep_time)

    # Post-query processing (sort table, convert to pandas, etc.)
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


# Example usage (runtime preparation)
if __name__ == "__main__":
    # NOTE: The following external functions/variables must be defined before running:
    # - create_neowise_database(db_path): Function to create/initialize the database
    # - save_raw_observations(raw_df, source_id, zp_stb_df, cursor): Function to save raw observations
    # - process_band_and_save_epochs(df, band, source_id, zp_stb_df, cursor): Function to process band data
    # - sources: Iterable of (source_id, ra, dec) tuples to process
    # - zp_stb: Zero-point stability DataFrame

    db_path = "neowise_target_region_2.db"
    conn = create_neowise_database(db_path)
    conn.close()

    # Prepare session (increase pool size as needed)
    prepare_irsa_session(pool_maxsize=50, max_retries=3, backoff_factor=1.0)

    num_workers = 4  # Reduce to 2 for higher success rate if needed
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
    logging.info("Completed!")
