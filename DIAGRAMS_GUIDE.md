# アーキテクチャ図・設計図ガイド

## 概要

このドキュメントは、`ARCHITECTURE_AND_DESIGN_DIAGRAMS.md`の使用方法と、論文での活用方法をまとめたガイドです。

## ドキュメントの内容

`ARCHITECTURE_AND_DESIGN_DIAGRAMS.md`には、以下の9つのセクションがあります:

### 1. システムアーキテクチャ図
- **全体システム構成**: フロントエンド、外部サービス、データフローの全体像
- **技術スタック**: 使用している技術の一覧

📌 **論文での使用**: Methodsセクションで、システムの全体構造を説明する際に使用

### 2. コンポーネント設計図
- **主要クラス構造**: SkyViewerクラスの詳細
- **データモデル**: データ構造の定義

📌 **論文での使用**: 実装の詳細説明が必要な場合に使用

### 3. 主要な処理フロー図
- **基本的な検索・表示フロー**: ユーザー入力から表示までの流れ
- **星選択とマーカー色変更フロー**: インタラクション処理
- **ページ遷移とデータ永続化フロー**: sessionStorageの活用

📌 **論文での使用**: 技術的な実装の説明に使用

### 4. UI/UXレイアウト設計
- **index.html (検索ページ) レイアウト**: 検索インターフェース
- **viewer.html (詳細表示ページ) レイアウト**: 結果表示インターフェース
- **レイアウト比較表**: 2ページの違いを表形式でまとめ

📌 **論文での使用**: ユーザーインターフェースの説明に使用（**推奨**）

### 5. 使用手順の概念図
- **基本ワークフロー**: ユーザーの標準的な操作手順
- **機能別使用シナリオ**: 
  - P.A.制約を考慮したガイド星選択
  - 等級フィルターを使った星の絞り込み
  - MIMIZUKU デュアルフィールドビュー

📌 **論文での使用**: Usage/Methodsセクションでユーザーの操作を説明（**推奨**）

### 6. 主要アルゴリズム
- **Haversine法による天体間距離計算**: 数式と処理フロー
- **位置角(P.A.)計算**: 数式と処理フロー
- **マーカー描画ロジック**: 色分けの実装

📌 **論文での使用**: アルゴリズムの説明が必要な場合に使用

### 7. 図の生成について
- **画像生成方法**: Draw.io、Mermaid、PlantUMLの活用方法
- **各図の推奨形式**: どの図をどのツールで作成するかの推奨

📌 **論文での使用**: 画像を作成する際の参考資料

### 8. 論文への記載推奨事項
- **必須の図**: 論文に必ず含めるべき図のリスト
- **補足の図**: 必要に応じて含める図
- **記載すべきテキスト説明**: 論文に含めるべき要点

📌 **論文での使用**: 論文執筆時のチェックリスト

### 9. Mermaid記法のサンプル
- **基本ワークフロー**: Mermaid記法で記述
- **コンポーネント構造**: クラス図
- **ページ遷移フロー**: シーケンス図

📌 **論文での使用**: GitHubやVS Codeで直接レンダリング可能

---

## 論文に含めるべき図（優先順位順）

### 🥇 最優先（必ず含める）

1. **システム全体構成図** (セクション1.1)
   - 読者にアプリケーションの全体像を伝える
   - Methodsセクションの冒頭に配置

2. **UI/UXレイアウト設計** (セクション4.1, 4.2)
   - index.htmlとviewer.htmlの違いを視覚的に示す
   - Results/Implementationセクションに配置

3. **基本ワークフロー図** (セクション5.1)
   - ユーザーの使用手順を明確に示す
   - Usage/Methodsセクションに配置

### 🥈 推奨（含めることが望ましい）

4. **技術スタック** (セクション1.2)
   - 使用技術を一覧で示す
   - Methodsセクションに配置

5. **機能別使用シナリオ** (セクション5.2)
   - 主要機能の使い方を具体的に示す
   - Results/Usageセクションに配置

### 🥉 オプション（必要に応じて）

6. **クラス構造図** (セクション2.1)
   - 実装の詳細説明が必要な場合
   
7. **データフロー図** (セクション3)
   - 技術的な詳細説明が必要な場合

8. **主要アルゴリズム** (セクション6)
   - 座標計算の詳細が重要な場合

---

## 画像化の方法

### 方法1: Draw.io（推奨）

1. [Draw.io](https://app.diagrams.net/)を開く
2. テキスト図を参考に手動で作成
3. PNG/SVG形式でエクスポート

**メリット**:
- 高品質な図が作成できる
- 編集が容易
- 論文用の図として最適

### 方法2: Mermaid Live Editor

1. [Mermaid Live Editor](https://mermaid.live/)を開く
2. セクション9のMermaid記法をコピー＆ペースト
3. PNG/SVG形式でダウンロード

**メリット**:
- コードから自動生成
- 素早く作成できる
- GitHubでも直接レンダリング可能

### 方法3: スクリーンショット

1. Markdown viewerでドキュメントを開く
2. ASCII図をスクリーンショット
3. 画像編集ソフトで不要部分をトリミング

**メリット**:
- 最も簡単
- そのまま使用できる

---

## 論文での記載例

### Methodsセクションの例

```
## Methods

### Web Application Architecture

We developed a web-based sky viewer application to assist 
astronomers in selecting guide stars for observations. 
Figure 1 shows the overall system architecture.

[図1: システム全体構成図を挿入]

The application consists of two main pages: a search interface
(index.html) and a detailed results view (viewer.html). 
Figure 2 illustrates the layout comparison between these pages.

[図2: UI/UXレイアウト設計を挿入]

### User Workflow

Users follow a standard workflow to select guide stars:
(1) Enter target coordinates
(2) Load star catalogs
(3) Review candidate guide stars
(4) Select optimal guide star based on P.A. constraints

Figure 3 shows the complete user workflow.

[図3: 基本ワークフローを挿入]

### Implementation

The application is implemented using pure JavaScript (ES6+) 
without frameworks, utilizing Aladin Lite v3 for astronomical 
image display. Key features include:

- Coordinate-based target search
- CSV catalog loading
- P.A. constraint-aware guide star recommendation
- Observability checking for major observatories
- MIMIZUKU dual-field view

Technical details are provided in the class structure diagram
in the supplementary materials.
```

---

## よくある質問

### Q1: すべての図を論文に含める必要がありますか？

A: いいえ。セクション8に記載された「必須の図」（システム構成図、UI/UXレイアウト、基本ワークフロー）の3つを優先してください。他の図は必要に応じて supplementary materials として提供できます。

### Q2: テキスト図をそのまま論文に使えますか？

A: 可能ですが、論文の質を高めるために Draw.io や Mermaid で画像化することを推奨します。テキスト図は画像作成の参考資料として活用してください。

### Q3: 図の説明文も必要ですか？

A: はい。セクション8.3に記載された「記載すべきテキスト説明」を参考に、各図に対する説明文を論文に含めてください。

### Q4: 英語の図が必要ですか？

A: 日本語の論文の場合は日本語の図で問題ありませんが、英語の論文の場合は図中のテキストを英語に翻訳してください。構造は同じなので、ラベルのみ変更すれば対応できます。

---

## ファイル構成

```
web_standard_viewer/
├── ARCHITECTURE_AND_DESIGN_DIAGRAMS.md  # 本体（754行）
├── DIAGRAMS_GUIDE.md                    # 本ガイド
├── README.md                            # アプリケーションの説明
├── 完成報告.md                           # 実装完了報告
├── IMPLEMENTATION_SUMMARY.md            # 実装まとめ
└── ...
```

---

## まとめ

- `ARCHITECTURE_AND_DESIGN_DIAGRAMS.md` は論文用の包括的な図集です
- 最優先で含めるべき図: システム構成図、UI/UXレイアウト、基本ワークフロー
- Draw.io または Mermaid を使って画像化することを推奨
- セクション8の「論文への記載推奨事項」を参考に論文を執筆

ご質問や追加の図が必要な場合は、お知らせください。
