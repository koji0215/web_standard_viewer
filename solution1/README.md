# Solution 1: 固定サイズ表示 + 高解像度化

## 概要

MIMIZUKU Dual Field PNG View の改善案1の実装です。

## 実装内容

### 主な変更点

1. **html2canvasのscale値を増加**: `scale: 3` → `scale: 5`
   - より高解像度でキャプチャを実行
   
2. **固定サイズへのスケーリング**
   - 各フィールドを **300×600px** の固定サイズにスケールアップ
   - 天体間の距離に関係なく、常に同じサイズで表示
   
3. **画質改善**
   - `imageSmoothingEnabled = true` と `imageSmoothingQuality = 'high'` を使用
   - スケーリング時の品質を向上

## 使い方

1. ブラウザで `solution1/index.html` を開く
2. 通常通り天体とガイド星を選択
3. "Show MIMIZUKU Dual Field" をクリック
4. "Switch to PNG View" をクリック

## 効果

- ✅ 画像サイズが固定され、小さすぎる問題を解決
- ✅ scale値の増加により、元画像の解像度が向上
- ⚠️ ただし、天体間距離が大きい場合、元のソース画像の解像度に依存するため、完全な高解像度化には限界がある

## 技術詳細

- **固定出力サイズ**: 300×600px（各フィールド）
- **html2canvas scale**: 5
- **画像スムージング**: high quality
- **実装工数**: 約2-3時間
