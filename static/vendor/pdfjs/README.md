# PDF.js (vendored)

- バージョン: **3.11.174**（`pdfjs-dist` npm パッケージの `legacy/build/`）
- 取得元: https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-3.11.174.tgz
- ライセンス: Apache License 2.0（同梱 `LICENSE`。ソース先頭の `@licstart` 通知も保持）

## 用途

保管画面２・編集画面・検索結果詳細ポップアップの PDF プレビューを、ブラウザ内蔵 PDF
ビューアの `<iframe>` ではなく PDF.js で各ページを `<canvas>` に自前描画する
（`static/js/pdf-preview.js`）。狭いプレビュー枠でも縦長／横長を問わず枠幅ぴったりに
フィットし、`IntersectionObserver` による遅延描画で数百ページの PDF でも軽い。

`settings.PDF_JS_PREVIEW_ENABLED`（`.env` の `PDF_JS_PREVIEW_ENABLED`、既定 `True`）を
`False` にすると従来の `<iframe>` 方式へ即座に戻せる。

## なぜ legacy ビルドか

`legacy/build/` は古いブラウザ向けに ES5 相当へトランスパイル済み。庁内利用端末の
ブラウザ世代が不明なため、最新（ESM 前提）ビルドではなく legacy(UMD, グローバル
`window.pdfjsLib`)を採用。

## 更新手順

```
curl -sSL -o /tmp/pdfjs.tgz https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-<VER>.tgz
tar -xzf /tmp/pdfjs.tgz -C /tmp
cp /tmp/package/legacy/build/pdf.min.js        static/vendor/pdfjs/pdf.min.js
cp /tmp/package/legacy/build/pdf.worker.min.js static/vendor/pdfjs/pdf.worker.min.js
cp /tmp/package/LICENSE                        static/vendor/pdfjs/LICENSE
```

`pdf.min.js` と `pdf.worker.min.js` は必ず同一バージョンで揃えること（API 不一致で
`getDocument` が失敗する）。更新後は `pdf-preview.js` の `getViewport`/`render` 引数の
API 互換を確認する。
