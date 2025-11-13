# エラー修正の詳細

## 概要
このドキュメントは、「詳細ビューで表示」ボタンのエラーと表中の星クリック時の表示問題の修正内容をまとめたものです。

## 問題1: QuotaExceededError

### 現象
「詳細ビューで表示」ボタンをクリックすると、以下のエラーがコンソールに表示される:
```
Uncaught QuotaExceededError: Failed to execute 'setItem' on 'Storage': 
Setting the value of 'viewerData' exceeded the quota.
```
at app.js:818

### 原因
`navigateToViewer()` 関数で、カタログデータ全体（数千から数万行のデータ）を sessionStorage に保存しようとしていた。
sessionStorage の容量制限（通常5-10MB）を超えるため、エラーが発生していた。

### 修正内容

#### app.js (lines 805-831)
**変更前:**
```javascript
const viewerData = {
    targetCoord: this.targetCoord,
    targetInput: document.getElementById('target-input')?.value || '',
    instPA: this.instPA,
    paTolerance: this.paTolerance,
    paRestrict: this.paRestrict,
    catalogs: this.catalogs  // 全カタログデータを保存（問題点）
};

sessionStorage.setItem('viewerData', JSON.stringify(viewerData));
```

**変更後:**
```javascript
const viewerData = {
    targetCoord: this.targetCoord,
    targetInput: document.getElementById('target-input')?.value || '',
    instPA: this.instPA,
    paTolerance: this.paTolerance,
    paRestrict: this.paRestrict,
    starsInFov: this.starsInFov,              // フィルター済みの星のみ（最大500個）
    allStarsInFov: this.allStarsInFov,
    availableColumns: this.availableColumns,
    magFilter: this.magFilter
};

try {
    sessionStorage.setItem('viewerData', JSON.stringify(viewerData));
    window.location.href = 'viewer.html';
} catch (e) {
    if (e.name === 'QuotaExceededError') {
        alert('データサイズが大きすぎます。等級フィルターを使用して星の数を減らしてください。');
    } else {
        alert('エラーが発生しました: ' + e.message);
    }
}
```

#### viewer.html (lines 518-542)
**変更前:**
```javascript
window.skyViewer.catalogs = data.catalogs;
window.skyViewer.findStarsInFov();  // 全カタログから再検索
```

**変更後:**
```javascript
// 保存済みのフィルター済みデータから復元
window.skyViewer.starsInFov = data.starsInFov || [];
window.skyViewer.allStarsInFov = data.allStarsInFov || [];
window.skyViewer.availableColumns = data.availableColumns || [];
window.skyViewer.magFilter = data.magFilter || { band: '', min: null, max: null };

window.skyViewer.updateMagFilterDropdown();

// 復元した星を表示・プロット
window.skyViewer.displayStars();
window.skyViewer.plotStarsOnAladin();
```

### 効果
- カタログ全体ではなく、視野内の星（最大500個）のみを保存するため、データサイズが大幅に削減
- sessionStorage の容量制限を超えることがなくなる
- エラーハンドリングにより、万が一の場合もユーザーにわかりやすいメッセージを表示

---

## 問題2: 表中の星をクリックしても画像上で変化しない

### 現象
右パネルの星リストで星をクリックしても、左側の Aladin 画像上でその星のマーカーの色やサイズが変化しない。

### 原因
`plotStarsOnAladin()` 関数で星のカタログを更新した後、Aladin Lite の描画が自動的に更新されていなかった。
Aladin Lite v3 では、カタログの変更後に明示的に再描画を要求する必要がある。

### 修正内容

#### app.js (lines 395-447)
**追加コード:**
```javascript
plotStarsOnAladin() {
    // ... (既存のコード)
    
    this.starCatalog.addSources(sources);
    
    // Aladin の再描画を強制
    try {
        this.aladin.view.requestRedraw();
    } catch (e) {
        // フォールバック: 最小限のビュー変更で再描画をトリガー
        try {
            const currentFov = this.aladin.getFov();
            this.aladin.setFoV(currentFov[0]);
        } catch (e2) {
            console.warn('Could not force Aladin redraw:', e2);
        }
    }
    
    this.attachCanvasHitTestForMainAladin();
}
```

### 効果
- 星を選択すると、画像上のマーカーがすぐに更新される
- 選択された星は赤色・大きいサイズで表示される
- 推奨ガイド星はマゼンタ色で表示される
- その他の星はスカイブルー色で表示される

---

## テスト手順

### 問題1のテスト
1. index.html を開く
2. Target に座標を入力（例: `18h09m01.4800s -20d05m08.000s`）
3. "Load Catalogs" で CSV ファイルをアップロード
4. "Search" ボタンをクリック
5. 視野内の星が表示されたら、「詳細ビューで表示 →」ボタンをクリック
6. エラーなく viewer.html に遷移し、星が正しく表示されることを確認

### 問題2のテスト
1. 上記の手順で星を検索
2. 右パネルの星リストから任意の星をクリック
3. 左側の Aladin 画像で、選択した星のマーカーが赤色・大きいサイズに変化することを確認
4. 別の星をクリックして、マーカーが正しく更新されることを確認

---

## 技術的詳細

### sessionStorage の制限
- ブラウザによって異なるが、一般的に 5-10MB の制限
- JSON 文字列として保存されるため、実際のデータサイズより大きくなる
- 大量のデータを保存する場合は IndexedDB の使用を検討すべき

### Aladin Lite v3 の描画メカニズム
- カタログの変更は即座に描画に反映されない
- `view.requestRedraw()` を呼び出すか、ビューの変更をトリガーする必要がある
- フォールバック処理により、異なるバージョンの Aladin でも動作

### データフロー
```
index.html → sessionStorage → viewer.html
  ↓                              ↓
検索・フィルター              復元・表示
  ↓                              ↓
starsInFov (max 500)        plotStarsOnAladin()
```

---

## まとめ

両方の問題は以下の修正で解決されました:

1. **QuotaExceededError**: カタログ全体ではなく、フィルター済みの星データのみを保存
2. **星クリック時の表示**: Aladin の明示的な再描画処理を追加

これらの修正により、アプリケーションは正常に動作し、ユーザーエクスペリエンスが向上します。
