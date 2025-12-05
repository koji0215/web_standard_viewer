# MIMIZUKU Dual Field 機能改善 実現可能性調査報告

## 概要

本報告書は、MIMIZUKU Dual FieldのPNG View機能において、離れた天体を同時に観測する際に表示画像が小さく・粗くなる問題に対する改善案の実現可能性を調査したものです。

## 現在の実装の問題点

### 問題の原因分析

現在の実装では、以下の処理フローでPNG画像を生成しています：

1. **単一のAladin Liteビューの生成** (`initMimizukuSingleField`)
   - ターゲットとガイド星の中点を中心として、1つのAladinビューを作成
   - 視野角（FoV）は `Math.max(0.15, sep * 1.5)` で計算（sepは天体間の角距離）
   - つまり、**天体間の距離が大きいほど、広い視野が必要**となる

2. **html2canvasによるキャプチャ** (`convertToPNGView`)
   - `scale: 3` で3倍の解像度でキャプチャ
   - 固定の画素数でキャプチャされるため、**広い視野ほど1角分あたりの画素数が減少**

3. **各天体領域の切り出しと結合** (`extractAndConcatenateFields`)
   - 1'×2'の固定サイズでTarget/Guide両方を切り出し
   - 切り出しサイズは視野角から計算されるため、**広い視野では切り出しサイズ（ピクセル数）が小さくなる**

### 数値例

| 天体間距離 | FoV | 1分角あたりのピクセル数（概算） | 1'×2'切り出しサイズ |
|-----------|-----|-------------------------------|-------------------|
| 5分角 | 0.15度 | 約200px | 約200×400px |
| 20分角 | 0.5度 | 約60px | 約60×120px |
| 50分角 | 1.25度 | 約24px | 約24×48px |

このように、天体間距離が大きくなると、切り出される画像のピクセル数が大幅に減少し、画像が小さく・粗くなります。

---

## 改善案1: 合成画像サイズの固定化と高解像度化

### 概要

現在の単一Aladinビューアプローチを維持しつつ、以下の改善を行う：
- 切り出した画像を固定サイズにスケールアップ
- html2canvasのscaleパラメータをさらに上げて高解像度化

### 実装方法

```javascript
// extractAndConcatenateFields関数内での変更案
async extractAndConcatenateFields(sourceCanvas) {
    // ... 既存の切り出し処理 ...
    
    // 固定の出力サイズを定義（例: 各フィールド200×400px）
    const FIXED_WIDTH = 200;  // 1分角に相当
    const FIXED_HEIGHT = 400; // 2分角に相当
    
    // 切り出した画像を固定サイズにスケールアップ
    const scaledLeft = this.scaleCanvas(leftCanvas, FIXED_WIDTH, FIXED_HEIGHT);
    const scaledRight = this.scaleCanvas(rightCanvas, FIXED_WIDTH, FIXED_HEIGHT);
    
    // 結合処理
    // ...
}

scaleCanvas(canvas, targetWidth, targetHeight) {
    const scaled = document.createElement('canvas');
    scaled.width = targetWidth;
    scaled.height = targetHeight;
    scaled.getContext('2d').drawImage(canvas, 0, 0, targetWidth, targetHeight);
    return scaled;
}
```

また、html2canvasのscale値を増加：
```javascript
// convertToPNGView関数内
const canvas = await html2canvas(div, { 
    useCORS: true, 
    allowTaint: true, 
    backgroundColor: '#000', 
    scale: 6  // 3から6に増加
});
```

### 実現可能性: ✅ 高

**メリット:**
- 実装が比較的簡単（既存コードの小規模な変更で済む）
- 出力画像サイズが一定になり、ユーザーが見やすい
- 既存のUIを変更する必要がない

**デメリット:**
- 元画像の解像度が低い場合、スケールアップしても画質は改善されない
- html2canvasのscale値を上げすぎると、メモリ使用量とレンダリング時間が増加
- 根本的な解像度不足の問題は解決できない

**技術的制約:**
- `scale: 6`以上に設定すると、一部のブラウザでメモリ不足やレンダリング遅延が発生する可能性あり
- 特に大きな天体間距離の場合、ソース画像自体の解像度が不足しているため、スケールアップしても「ぼやけた大きな画像」になる

### 高解像度切り出しについて

Aladin Liteのタイル画像はサーバーから取得されるHiPSデータに依存します。より高解像度の画像を得るには：

1. **より高解像度のサーベイを使用する**（例: PanSTARRS、DECaLS）
2. **FoVを小さくしてズームインする**（ただし、これは天体間距離が大きい場合に矛盾）

結論として、**ソース画像の解像度を上げることは、Aladin Liteが提供するHiPSサーベイの解像度に依存**するため、アプリケーション側での制御には限界があります。

---

## 改善案2: 一定距離以上での分離表示方式

### 概要

天体間の距離が一定値（例: 10分角）を超える場合、現在の単一Aladinビューではなく、各天体を中心とした2つの独立したAladinビューを使用する方式。

### 実装方法

```javascript
// showMimizukuDualField関数の改修案
showMimizukuDualField() {
    if (!this.selectedStar || !this.targetCoord) return;

    document.getElementById('mimizuku-modal').style.display = 'block';
    const t = this.targetCoord, g = this.selectedStar;
    const sep = this.calculateSeparation(t.ra, t.dec, g.ra, g.dec);
    
    // 距離閾値（例: 10分角 = 1/6度 ≈ 0.167度）
    const SEPARATION_THRESHOLD = 10 / 60;  // 10 arcmin
    
    if (sep > SEPARATION_THRESHOLD) {
        // 分離モード: 2つの独立したAladinビューを使用
        this.initMimizukuSeparatedFields(t, g);
    } else {
        // 通常モード: 従来の単一ビュー
        this.initMimizukuSingleField();
    }
}

// 新規関数: 分離フィールドモード
initMimizukuSeparatedFields(target, guide) {
    const container = document.getElementById('mimizuku-view-container');
    container.innerHTML = `
        <div style="display: flex; flex: 1; gap: 10px;">
            <div id="mimizuku-field-target" style="flex: 1; background: #000; position: relative;"></div>
            <div id="mimizuku-field-guide" style="flex: 1; background: #000; position: relative;"></div>
        </div>
    `;

    // 各天体中心のAladinビューを作成（固定の狭いFoV）
    const fovForField = 0.05;  // 3分角（1'×2'のフィールドに十分な余裕）
    
    this.mimizukuAladins = {
        target: A.aladin('#mimizuku-field-target', {
            survey: this.getCurrentSurvey(),
            fov: fovForField,
            target: `${target.ra} ${target.dec}`,
            showReticle: false,
            // ... 他のオプション
        }),
        guide: A.aladin('#mimizuku-field-guide', {
            survey: this.getCurrentSurvey(),
            fov: fovForField,
            target: `${guide.ra} ${guide.dec}`,
            showReticle: false,
            // ... 他のオプション
        })
    };
    
    // 各ビューにフィールド枠を描画
    setTimeout(() => {
        this.drawMimizukuFieldBox(this.mimizukuAladins.target, target, 'Target', '#ff0');
        this.drawMimizukuFieldBox(this.mimizukuAladins.guide, guide, 'Guide', '#0ff');
    }, 500);
}

// PNG変換も分離モードに対応
async convertToPNGViewSeparated() {
    // 各Aladinビューを個別にキャプチャ
    const targetDiv = document.getElementById('mimizuku-field-target');
    const guideDiv = document.getElementById('mimizuku-field-guide');
    
    const [targetCanvas, guideCanvas] = await Promise.all([
        html2canvas(targetDiv, { useCORS: true, allowTaint: true, backgroundColor: '#000', scale: 4 }),
        html2canvas(guideDiv, { useCORS: true, allowTaint: true, backgroundColor: '#000', scale: 4 })
    ]);
    
    // 両方のキャンバスから固定サイズで切り出して結合
    // ...
}
```

### 実現可能性: ✅ 高

**メリット:**
- **各天体を中心にした狭いFoVで表示されるため、高解像度の画像が得られる**
- 距離に関係なく、常に同じ解像度・サイズの画像を出力可能
- より「実際の観測イメージ」に近い表示が可能

**デメリット:**
- 実装がより複雑になる
- UIの変更が必要（分離モード時は2つのビューを表示）
- 2つのAladinインスタンスを管理する必要がある（メモリ使用量増加）
- 2つの天体間の相対位置関係が直感的にわかりにくくなる可能性

**技術的考慮事項:**
- Aladin Lite v3は複数インスタンスの同時使用をサポートしている
- html2canvasは各divを独立してキャプチャ可能
- PNG変換時に2つのキャンバスを結合する処理が追加で必要

---

## 推奨実装案

### フェーズ1: 案1の実装（即効性のある改善）

まず、比較的簡単に実装できる案1を先に実装し、ユーザーエクスペリエンスの即座の改善を図る：

1. **出力画像サイズの固定化**
   - 切り出した画像を固定サイズ（例: 各200×400px）にスケールアップ
   - これにより、少なくとも「画像が小さい」という問題は解決

2. **html2canvasのscale値の調整**
   - `scale: 3` から `scale: 5` に増加（6以上はパフォーマンス考慮）

### フェーズ2: 案2の実装（根本的な改善）

ユーザーフィードバックを得た後、案2を実装：

1. **距離閾値の設定**
   - 例: 10分角以上で分離モードに切り替え
   - 設定可能なオプションとして提供も検討

2. **分離モードのUI実装**
   - 2つのAladinビューを横並びで表示
   - モード表示のインジケーター追加

3. **分離モードでのPNG変換対応**
   - 各ビューを個別にキャプチャして結合

---

## 実装工数の見積もり

| 項目 | 案1 | 案2 |
|-----|-----|-----|
| コード変更量 | 小（30-50行程度） | 中（150-200行程度） |
| 実装時間 | 2-4時間 | 1-2日 |
| テスト範囲 | 既存機能の動作確認 | 新旧両モードの動作確認 |
| リスク | 低 | 中（新しいUIロジック追加） |

---

## 結論

両案とも**技術的に実現可能**です。

- **短期的な改善**としては**案1**を推奨します。実装が簡単で、即座に「画像が小さい」という問題を軽減できます。

- **根本的な解決**としては**案2**を推奨します。各天体を個別のビューで高解像度表示することで、天体間距離に関係なく、常に高品質な画像を提供できます。

最適なアプローチは、**両案を段階的に実装**することです。まず案1で即効性のある改善を行い、その後案2で完全な解決を図ることで、ユーザーへの価値提供を早めつつ、最終的には高品質な機能を実現できます。

---

## 参考：技術詳細

### Aladin Lite v3のHiPSタイル解像度

Aladin Liteは、HiPS（Hierarchical Progressive Survey）形式のタイル画像を使用しています。タイル解像度は以下の要因で決まります：

- **HiPSオーダー**: 高いオーダーほど高解像度（通常order 3-13）
- **サーベイの元画像解像度**: サーベイによって異なる
  - 2MASS: ~2"/pixel
  - PanSTARRS: ~0.25"/pixel
  - DECaLS: ~0.26"/pixel

### html2canvasの制限

- scale値を上げすぎると、キャンバスサイズが大きくなりメモリ不足の可能性
- CORSポリシーによりクロスオリジン画像がtaintedになる場合あり
- WebGL要素のキャプチャには制限がある場合あり

### ブラウザのキャンバスサイズ制限

- Chrome: 最大268,435,456ピクセル（約16,384×16,384）
- Firefox: 最大32,767×32,767ピクセル
- Safari: 最大16,777,216ピクセル

これらの制限を考慮し、scale値は5-6程度を上限とすることを推奨します。
