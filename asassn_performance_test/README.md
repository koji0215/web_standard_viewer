# ASASSN パフォーマンステスト

pyasassnを使用してASASSN時系列データの取得時間を計測するツール

## 概要

このツールは、pyasassn（ASASSN Sky Patrolクライアント）を使用してASASSNライトカーブデータの取得パフォーマンスを測定するための独立したWebアプリケーションです。

### 目的

- ASASSNデータの取得時間を計測
- リアルタイムアクセスの実用性を評価
- Gaia ID検索と座標検索の性能比較

## ファイル構成

```
asassn_performance_test/
├── index.html              # フロントエンドUI
├── backend/
│   ├── app.py              # FastAPI バックエンド
│   └── requirements.txt    # Python依存パッケージ
└── README.md               # このファイル
```

## セットアップ

### 1. Python環境の準備

```bash
# このディレクトリに移動
cd asassn_performance_test/backend

# 仮想環境を作成（推奨）
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# または
venv\Scripts\activate  # Windows
```

### 依存パッケージのインストール

**重要**: pyasassnは内部でpyarrow 4.0.1の`deserialize()`メソッドを使用しています。
新しいpyarrow (>=14.0.0)ではこのメソッドが削除されているため、pyarrow 4.0.1を使用する必要があります。

**推奨方法（3ステップインストール）**:

```bash
# ステップ1: コア依存関係をインストール（pyarrow 4.0.1を含む）
pip install -r requirements-step1.txt

# ステップ2: Webフレームワークをインストール
pip install -r requirements-step2.txt

# ステップ3: pyasassnをインストール（依存関係は既に解決済み）
pip install --no-deps pyasassn
```

**代替方法（手動インストール）**:

```bash
# 1. setuptools と基本パッケージ
pip install 'setuptools<71' wheel

# 2. データ処理ライブラリ（pyarrow 4.0.1が重要）
pip install numpy pandas pyarrow==4.0.1

# 3. 天文学ライブラリ
pip install 'astropy>=6.0.0' 'astroquery>=0.4.7'

# 4. Webフレームワーク
pip install fastapi 'uvicorn[standard]' pydantic

# 5. pyasassn（依存関係は既に解決済み）
pip install --no-deps pyasassn
```

**簡単な方法（競合の可能性あり）**:

```bash
pip install -r requirements.txt
```

注: 一部の環境では依存関係の競合が発生する場合があります。
エラーが出た場合は上記の推奨方法または代替方法をお試しください。

### 2. バックエンドサーバーの起動

```bash
# backend/ ディレクトリで実行
python app.py

# または uvicorn で直接起動
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

サーバーが起動したら、以下のURLで確認できます:
- API: http://localhost:8000
- API ドキュメント: http://localhost:8000/docs

### 3. フロントエンドの起動

別のターミナルで、プロジェクトのルートディレクトリに戻ります:

```bash
cd ..  # asassn_performance_test/ に戻る

# 簡易HTTPサーバーを起動
python3 -m http.server 8080
```

ブラウザで以下のURLを開きます:
```
http://localhost:8080/index.html
```

## 使い方

### 1. カタログの準備

- カタログファイル（CSV形式）をアップロード
- テストするサンプル数を指定（推奨: 3-5個から開始）

### 2. カラムマッピング

CSVのカラムをデータ項目に対応付けます:
- **Source ID** (必須): 天体の識別子
- **RA / 赤経** (必須): 赤経（度）
- **DEC / 赤緯** (必須): 赤緯（度）
- **Gaia ID** (オプション): Gaia DR3 source ID（推奨）

### 3. テスト実行

「パフォーマンステストを開始」ボタンをクリック

### 4. 結果の確認

以下の情報が表示されます:
- 合計時間、平均時間/天体
- 最短・最長時間
- 成功・失敗数
- 各天体の詳細結果（ライトカーブ数、データポイント数）

## 取得方法

### Gaia ID検索（推奨）

```python
from pyasassn.client import SkyPatrolClient

client = SkyPatrolClient()
query = f"""
SELECT * 
FROM stellar_main 
WHERE gaia_id = {gaia_id}
"""
lcs = client.adql_query(query, download=True, threads=1)
```

**特徴**:
- Gaia IDで直接検索
- より高速で効率的
- 推奨される方法

### 座標検索

```python
from pyasassn.client import SkyPatrolClient

client = SkyPatrolClient()
lcs = client.cone_search(
    ra_deg=ra,
    dec_deg=dec,
    radius=3.0/3600.0,  # 3秒角を度に変換
    download=True,
    threads=1
)
```

**特徴**:
- 座標ベースの円錐検索
- Gaia IDがない場合の代替手段
- 検索範囲内の複数天体が返される可能性

## 判断基準

テスト結果をもとに、以下の基準で実装方式を決定します:

### リアルタイム取得を選択する条件

- **平均取得時間が許容範囲内**（例: 1-2秒以下）
- **Gaia IDがカタログに含まれている**
- **データの最新性が重要**
- **ストレージコストを抑えたい**

### 事前保存を選択する条件

- **平均取得時間が遅い**（例: 5秒以上）
- **大量の天体を頻繁にアクセスする**
- **応答速度が最重要**
- **オフライン利用が必要**

## トラブルシューティング

### よくある問題と解決方法

#### 1. pip install でエラーが発生する（Python 3.12+）

**症状**: `ModuleNotFoundError: No module named 'distutils'` または pyarrow関連のエラー

**原因**: pyasassnが古いpyarrow==4.0.1を要求するが、Python 3.12+では正しくビルドされない

**解決方法**:
```bash
# setuptools と wheel を先にインストール
pip install 'setuptools<71' wheel

# requirements.txt を使用（pyarrowの新しいバージョンが先にインストールされる）
pip install -r requirements.txt
```

または手動でインストール:
```bash
# 1. 基本パッケージ
pip install 'setuptools<71' wheel numpy pandas

# 2. 新しいpyarrowをインストール
pip install 'pyarrow>=14.0.0'

# 3. pyasassnの依存関係
pip install 'astropy>=6.0.0' 'astroquery>=0.4.7' requests beautifulsoup4 html5lib keyring

# 4. pyasassnをインストール（依存関係チェックを緩和）
pip install pyasassn

# 5. Webフレームワーク
pip install fastapi 'uvicorn[standard]' pydantic
```

#### 2. pyasassnのインストールエラー（その他）

**解決方法**:
```bash
# 個別にインストール
pip install fastapi uvicorn[standard] pydantic
pip install numpy pandas
pip install pyasassn
```

#### 3. バックエンドが起動しない

```bash
# 依存パッケージが正しくインストールされているか確認
pip list | grep -E "fastapi|pyasassn"

# ポート8000が使用中でないか確認
lsof -i :8000

# 別のポートで起動
uvicorn app:app --port 8001
```

#### 4. ASASSNサーバーエラー

**症状**: "No ASASSN data found" または "Network error"

**原因**: ASASSN Sky Patrolサービスが一時的にダウンまたは過負荷

**解決方法**:
- 数分待ってから再試行
- テスト対象の星数を減らす
- ASASSN Sky Patrolのステータスを確認

#### 5. タイムアウトエラー

**原因**: クエリに時間がかかりすぎています

**解決方法**:
- テスト対象の星数を減らす
- Gaia IDを使用する（より高速）
- ネットワーク接続を確認

#### 6. "module 'pyarrow' has no attribute 'deserialize'" エラー

**症状**: クエリ実行時に `Query failed: module 'pyarrow' has no attribute 'deserialize'` エラーが発生

**原因**: pyasassnはpyarrow 4.0.1の`deserialize()`メソッドを使用していますが、
新しいpyarrow (>=14.0.0)ではこのメソッドが削除されています。

**解決方法**:
```bash
# 現在のpyarrowをアンインストール
pip uninstall pyarrow -y

# pyarrow 4.0.1をインストール
pip install pyarrow==4.0.1

# pyasassnを再インストール（依存関係チェックなし）
pip install --no-deps pyasassn

# または、仮想環境を作り直して推奨方法でインストール
deactivate
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-step1.txt
pip install -r requirements-step2.txt
pip install --no-deps pyasassn
```

**確認方法**:
```python
# Pythonで確認
import pyarrow
print(pyarrow.__version__)  # "4.0.1" が表示されるべき
print(hasattr(pyarrow, 'deserialize'))  # True が表示されるべき
```

## API仕様

### POST /test-performance

**リクエスト**:
```json
{
  "catalog_entries": [
    {
      "source_id": "Star_1",
      "ra": 188.753,
      "dec": -20.086,
      "gaia_id": "1234567890123456"
    }
  ]
}
```

**レスポンス**:
```json
{
  "total_time": 15.234,
  "avg_time_per_star": 1.523,
  "min_time": 1.234,
  "max_time": 2.345,
  "successful_queries": 10,
  "failed_queries": 0,
  "results": [
    {
      "source_id": "Star_1",
      "ra": 188.753,
      "dec": -20.086,
      "gaia_id": "1234567890123456",
      "query_time": 1.523,
      "num_lightcurves": 2,
      "total_datapoints": 1234,
      "success": true,
      "error_message": null
    }
  ]
}
```

## 注意事項

- **ASASSN Sky Patrolサービス**: 外部サービスのため、サーバー状態により一時的にエラーが発生することがあります
- **データ更新**: ASASSNは観測を継続しているため、データは随時更新されます
- **Gaia ID推奨**: Gaia IDがある場合、検索が大幅に高速化されます
- **初回アクセス**: 初回アクセス時は若干時間がかかる場合があります

## 推奨事項

1. **少数のサンプルから開始**: まず3-5個の天体でテスト
2. **Gaia IDを使用**: 可能な限りGaia IDを含むカタログを使用
3. **結果を分析**: 平均取得時間が許容範囲内かを確認
4. **スケーラビリティを考慮**: 実際の運用規模でのパフォーマンスを見積もる

## ライセンス

MIT License

## 関連リンク

- [ASASSN Sky Patrol](https://asas-sn.osu.edu/skypatrol)
- [pyasassn GitHub](https://github.com/ASASSN-Survey/pyasassn)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
