# Solution 1: MIMIZUKU Dual Field Viewer

## 概要 / Overview

このフォルダは、MIMIZUKU（ミミズク）デュアルフィールドビューワーの実装例です。
ターゲット天体とガイド星の両方の視野を1つの画面に表示します。

## 特徴 / Features

### MIMIZUKU表示方式: 単一統合ビュー (Single Combined View)

- ターゲットとガイド星の両方を含む統合されたアラディン画像を表示
- 両方の1'×2'フィールドを同時に可視化
- ターゲット（黄色）とガイド星（シアン）を色分けして表示
- 中点を中心とした視野で両方のフィールドを確認可能

### 主な機能

1. **天体検索**: 座標入力による天体検索
2. **カタログ読み込み**: CSV形式の星カタログ読み込み
3. **位置角（P.A.）制御**: 観測装置の位置角設定
4. **MIMIZUKU表示**: 統合ビューでのデュアルフィールド可視化
5. **観測可能性チェック**: TAO等の観測所での観測可能性確認

## 使い方 / Usage

1. `index.html`をWebブラウザで開く
2. ターゲット座標を入力して検索
3. カタログを読み込み
4. ガイド星を選択
5. "Show MIMIZUKU Dual Field View"をクリック

## ファイル構成 / File Structure

```
solution1/
├── index.html          - メインページ
├── viewer.html         - 詳細ビューページ
├── app.js             - JavaScript実装
└── backend/           - バックエンドAPI
    ├── app.py
    ├── app_custom.py
    ├── neowise_target_region.db
    └── requirements.txt
```

## 技術仕様 / Technical Specifications

- **フロントエンド**: 純粋なJavaScript
- **天体画像**: Aladin Lite v3
- **バックエンド**: Python Flask (ライトカーブデータ用)
- **データベース**: SQLite (NEOWISE データ)

## MIMIZUKU表示の実装 / MIMIZUKU Implementation

### Solution1の特徴

- **単一Aladinインスタンス**: 1つのアラディン画像に両方のフィールドを表示
- **統合ビュー**: ターゲットとガイド星の中点を中心に配置
- **色分け**: ターゲット（黄色）、ガイド星（シアン）で区別
- **視野サイズ**: 自動調整（分離距離の1.5倍）

### 利点

✓ 両方のフィールドの相対位置が直感的に理解できる  
✓ 実装がシンプル  
✓ メモリ使用量が少ない

### 用途

- 分離距離が小さい場合に最適
- 全体的な配置を確認したい場合
- 初期確認や計画段階での使用

---

**バージョン**: 1.0  
**最終更新**: 2026年1月13日
