# NEOWISE/ASASSN ライトカーブ表示プロトタイプ

このプロトタイプは、あらかじめ取得・保存したNEOWISEとASASSNのライトカーブデータを表示する機能を実装したものです。

## ディレクトリ構造

```
prototype/
├── backend/
│   ├── app.py              # FastAPI バックエンド
│   └── requirements.txt    # Python依存関係
├── data/
│   ├── neowise/           # NEOWISEデータ (100個のJSON)
│   └── asassn/            # ASASSNデータ (100個のJSON)
├── scripts/
│   └── fetch_sample_data.py  # サンプルデータ取得スクリプト
├── index.html             # フロントエンドUI
└── README.md              # このファイル
```

## データ形式

### NEOWISEデータ (JSON)
```json
{
  "source_id": "SOURCE_ID",
  "ra": 123.456,
  "dec": -12.345,
  "allwise_id": "J...",
  "num_observations": 50,
  "observations": [
    {
      "mjd": 55197.0,
      "w1_mag": 12.34,
      "w1_err": 0.05,
      "w2_mag": 12.45,
      "w2_err": 0.05
    }
  ]
}
```

### ASASSNデータ (JSON)
```json
{
  "source_id": "SOURCE_ID",
  "ra": 123.456,
  "dec": -12.345,
  "gaia_id": "GAIA_ID",
  "num_observations": 100,
  "observations": [
    {
      "mjd": 56658.0,
      "mag": 14.32,
      "mag_err": 0.08,
      "band": "V"
    }
  ]
}
```

## セットアップと実行

### 1. 依存関係のインストール

```bash
cd backend
pip install -r requirements.txt
```

### 2. バックエンドAPIサーバーの起動

```bash
cd backend
python3 app.py
```

サーバーが起動したら、以下のURLでアクセスできます：
- API ドキュメント: http://localhost:8000/docs
- ルート: http://localhost:8000/

### 3. フロントエンドの起動

別のターミナルでHTTPサーバーを起動：

```bash
cd prototype
python3 -m http.server 8080
```

ブラウザで http://localhost:8080/ を開きます。

## 使い方

1. **SOURCE IDで検索**
   - SOURCE ID入力欄に Gaia DR3 のSOURCE_IDを入力
   - 「ライトカーブを表示」ボタンをクリック

2. **座標で検索**
   - RA（赤経、度）とDec（赤緯、度）を入力
   - 「座標から表示」ボタンをクリック

3. **サンプルデータから選択**
   - ページ下部のサンプルボタンをクリック

## APIエンドポイント

### GET /api/lightcurve/neowise
NEOWISEライトカーブを取得

パラメータ:
- `source_id`: SOURCE_ID (Gaia DR3)
- `ra`, `dec`: 座標（度単位）

### GET /api/lightcurve/asassn
ASASSNライトカーブを取得

パラメータ:
- `source_id`: SOURCE_ID (Gaia DR3)
- `ra`, `dec`: 座標（度単位）

### GET /api/list
利用可能なデータのリスト

## 技術スタック

- **バックエンド**: FastAPI, Python 3
- **フロントエンド**: HTML, JavaScript, Chart.js
- **データ形式**: JSON

## サンプルデータについて

このプロトタイプには100個の星のライトカーブデータが含まれています。
データは `BrightKg_WISE_unique.csv` からランダムに選択された星について、
ダミーデータとして生成されています。

実際の実装では、astroqueryとpyasassnを使用して実際のNEOWISE/ASASSNデータを取得します。

## 次のステップ

1. 実際のNEOWISE/ASASSNデータの取得と保存
2. より多くの天体データの追加（数千〜数万個）
3. データベース（SQLite/PostgreSQL）への移行
4. より高度なフィルタリングと検索機能
5. 既存のSky Viewerへの統合
