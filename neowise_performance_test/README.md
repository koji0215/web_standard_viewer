# NEOWISE パフォーマンステストツール

## 概要

このツールは、NEOWISEデータの取得方法（`query_region` vs `query_tap`）の性能を比較し、実装方式の決定を支援します。

**目的**:
- `query_region`（座標ベース検索）と`query_tap`（TAP検索）の応答時間を比較
- AllWISE IDを使った高速化の効果を確認
- 事前保存 vs リアルタイム取得の判断材料を提供

## ファイル構成

```
neowise_performance_test/
├── README.md              # このファイル
├── index.html             # フロントエンド（Webインターフェース）
└── backend/
    ├── app.py            # FastAPIバックエンド
    └── requirements.txt   # Python依存パッケージ
```

## セットアップ

### 1. Python環境の準備

```bash
# このディレクトリに移動
cd neowise_performance_test/backend

# 仮想環境を作成（推奨）
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# または
venv\Scripts\activate  # Windows

# Pythonバージョンを確認
python --version

# 依存パッケージをインストール
# Python 3.13以降の場合（推奨）
pip install -r requirements.txt

# Python 3.9-3.12の場合（またはエラーが発生する場合）
# pip install -r requirements-py39-312.txt
```

**注意**: Python 3.13では、古いバージョンのastropyがビルドエラーを起こす可能性があります。その場合は、`requirements.txt`を使用してください（astropy 6.0以降を使用）。Python 3.9-3.12を使用している場合は、`requirements-py39-312.txt`でも動作します。

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
cd ..  # neowise_performance_test/ に戻る
```

#### オプションA: Pythonの簡易サーバー

```bash
python3 -m http.server 8080
```

ブラウザで http://localhost:8080/index.html を開く

#### オプションB: 直接HTMLファイルを開く

`index.html` をブラウザで直接開くこともできます。ただし、CORSの制約でAPIにアクセスできない場合があります。

## 使い方

### ステップ1: カタログの準備

1. Webインターフェース（http://localhost:8080/index.html）を開く
2. 「カタログファイル」から既存の `BrightKg_WISE_unique.csv` または同形式のCSVファイルを選択
3. 「テスト対象の星数」を設定（推奨: 5-20個、多すぎると時間がかかる）
4. 「カタログを読み込む」ボタンをクリック

**必要なCSVカラム**:
- `ra`: 赤経（度）
- `dec`: 赤緯（度）
- `AllWISE_ID` または `allwise_id`: AllWISE ID（オプション、あればquery_tapで使用）
- `Source` または `source_id`: 天体の識別名（オプション）

### ステップ2: テストの実行

3つのテストオプションがあります:

1. **query_region でテスト**: 座標ベースの検索のみをテスト
2. **query_tap でテスト**: TAP検索のみをテスト
3. **両方を比較テスト**: 両方の方法を順次実行して比較（推奨）

### ステップ3: 結果の確認

テスト完了後、以下が表示されます:

1. **比較サマリー**:
   - 合計時間、平均時間/星、最小/最大時間
   - 成功/失敗数
   - 方法間の差分と改善率
   - 推奨事項

2. **詳細結果**:
   - 各天体ごとの取得時間
   - 観測データ数
   - 成功/失敗ステータス

3. **グラフ**:
   - 天体ごとの取得時間の比較（棒グラフ）

## テスト方法の詳細

### query_region（従来の方法）

```python
table = Irsa.query_region(
    coord.SkyCoord(ra, dec, unit=(u.deg, u.deg)),
    catalog='neowiser_p1bs_psd',
    radius='0d0m5s'  # 5秒角
)
```

**特徴**:
- 座標ベースで検索
- シンプルで実装しやすい
- 空間検索のオーバーヘッドがある

### query_tap（TAP検索）

```python
# AllWISE IDがある場合
query = """
SELECT * FROM neowiser_p1bs_psd
WHERE allwise_cntr IN (
    SELECT cntr FROM allwise_p3as_psd
    WHERE designation = '{allwise_id}'
)
"""

# 座標ベースの場合
query = """
SELECT * FROM neowiser_p1bs_psd
WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra}, {dec}, 0.00139)) = 1
"""

table = Irsa.query_tap(query)
```

**特徴**:
- TAP（Table Access Protocol）を使用
- AllWISE IDで直接検索可能（高速化が期待できる）
- SQLライクなクエリで柔軟性が高い

## 判断基準

テスト結果をもとに、以下の基準で実装方式を決定します:

### リアルタイム取得を選択する条件

- **query_tapが大幅に高速**（30%以上の改善）
- **平均取得時間が許容範囲内**（例: 1秒以下）
- **AllWISE IDがカタログに含まれている**
- **ストレージコストを抑えたい**

### 事前保存を選択する条件

- **query_tapでも時間がかかる**（例: 2秒以上）
- **同じ天体を頻繁に参照する**
- **オフライン動作が必要**
- **応答速度の予測可能性が重要**

### ハイブリッドアプローチ

- **よく使う天体は事前保存**
- **それ以外はリアルタイム取得**
- **キャッシュ機構の導入**

## トラブルシューティング

### よくある問題と解決方法

#### 1. pip install でエラーが発生する

**症状**: `astropy==5.3.4` のビルドエラー（特にPython 3.13以降）

**原因**: Python 3.13は新しいバージョンで、古いastropyにはプリビルドされたホイールがありません。

**解決方法**:

```bash
# 方法1: デフォルトのrequirements.txtを使用（推奨）
# これはastropy 6.0以降を使用し、Python 3.13に対応しています
pip install -r requirements.txt

# 方法2: Python 3.9-3.12を使用している場合
pip install -r requirements-py39-312.txt

# 方法3: 個別にインストール
pip install --upgrade pip setuptools wheel
pip install fastapi uvicorn[standard] pydantic
pip install numpy pandas
pip install astropy  # 最新版を自動選択
pip install astroquery
```

#### 2. バックエンドが起動しない

```bash
# 依存パッケージが正しくインストールされているか確認
pip list | grep -E "fastapi|astroquery"

# ポート8000が使用中でないか確認
lsof -i :8000

# 別のポートで起動
uvicorn app:app --port 8001
```

#### 3. フロントエンドからAPIにアクセスできない

1. バックエンドが起動しているか確認: http://localhost:8000
2. ブラウザのコンソールでCORSエラーを確認
3. `app.py`のCORS設定を確認

### タイムアウトエラー

```python
# app.py でタイムアウトを延長
from astroquery.ipac.irsa import Irsa
Irsa.TIMEOUT = 300  # 300秒
```

### AllWISE IDが見つからない

- カタログにAllWISE IDカラムが含まれているか確認
- カラム名が `AllWISE_ID` または `allwise_id` であることを確認

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
      "allwise_id": "J123456.78+901234.5"
    }
  ],
  "method": "query_region"  // または "query_tap"
}
```

**レスポンス**:
```json
{
  "method": "query_region",
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
      "allwise_id": "J123456.78+901234.5",
      "query_time": 1.523,
      "num_observations": 245,
      "success": true,
      "error_message": null
    }
  ]
}
```

## 次のステップ

テスト結果をもとに、以下を決定します:

1. **リアルタイム取得を採用する場合**:
   - `query_tap`を使った実装に進む
   - プロトタイプ実装手順の第2週（バックエンドAPI実装）を開始
   - キャッシュ戦略を検討

2. **事前保存を採用する場合**:
   - NEOWISEデータのダウンロードと前処理を開始
   - データベース設計を確定
   - プロトタイプ実装手順の第1週（データ準備）に注力

3. **ハイブリッドアプローチの場合**:
   - 頻繁にアクセスされる天体の基準を定義
   - キャッシュとフォールバック機構の設計
   - 段階的な実装計画を策定

## 関連ドキュメント

- `プロトタイプ実装手順.md`: 実装の詳細手順
- `時系列データ機能実装可能性調査.md`: 全体的な実装可能性の調査結果

---

**作成日**: 2025年11月21日  
**バージョン**: 1.0
