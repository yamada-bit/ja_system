/*
 * PDF プレビュー描画（PDF.js）。保管画面２・編集画面・検索結果詳細ポップアップの PDF を、
 * ブラウザ内蔵 PDF ビューアの <iframe>（狭い枠でツールバー見切れ・横長クリップの既知問題）
 * ではなく PDF.js で各ページを <canvas> に自前描画する。2026-08-31 ユーザー依頼。
 *
 * 設計方針:
 *  - 各ページを「プレビュー枠の幅ぴったり」で描画（fit-to-width）。縦長・横長どちらも枠に収まる。
 *  - 全ページ分の空プレースホルダ <div> だけ先に並べ（高さは 1 ページ目のアスペクト比で仮置き）、
 *    枠のスクロール位置に応じて「表示付近のページだけ」canvas 描画する。離れたページの canvas は
 *    破棄してプレースホルダへ戻す。これで数百ページの PDF でも同時に生きる canvas は数枚に留まる。
 *    可視判定は枠の scroll イベント（+ 初回 1 回）で行う。IntersectionObserver は
 *    タブ非表示時等に発火しないことがあるため主機構にはしない。
 *  - PDF.js 本体（static/vendor/pdfjs/pdf.min.js, ~370KB）は最初に render() が呼ばれた時だけ
 *    動的 <script> で遅延ロードする。プレビューを開かない画面には一切ロードされない。
 *  - この方式を使うかは settings.PDF_JS_PREVIEW_ENABLED。無効時はこのファイル自体 base.html
 *    から読み込まれず、テンプレートは従来の <iframe> を出す。
 *
 * 依存: base.html が window.PDFJS_LIB_URL / window.PDFJS_WORKER_URL を {% static %} で埋め込む。
 * API: window.PdfPreview.render(containerEl, pdfUrl) / .clear(containerEl) / .zoom(containerEl, factor)
 */
(function () {
  "use strict";

  var libPromise = null;

  function loadLib() {
    if (window.pdfjsLib) {
      return Promise.resolve(window.pdfjsLib);
    }
    if (libPromise) {
      return libPromise;
    }
    libPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = window.PDFJS_LIB_URL;
      s.onload = function () {
        if (!window.pdfjsLib) {
          reject(new Error("pdfjsLib が読み込まれませんでした"));
          return;
        }
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = window.PDFJS_WORKER_URL;
        resolve(window.pdfjsLib);
      };
      s.onerror = function () {
        reject(new Error("PDF.js の読み込みに失敗しました: " + window.PDFJS_LIB_URL));
      };
      document.head.appendChild(s);
    });
    return libPromise;
  }

  // コンテナ要素ごとの描画状態。pager 切替や再オープンで render() が繰り返し呼ばれるため、
  // 古い pdf ドキュメント・イベントハンドラを確実に破棄してから作り直す。
  var states = new WeakMap();

  var MIN_SCALE = 0.4;
  var MAX_SCALE = 4.0;
  // 表示枠の上下この px 以内に入ったページは描画対象、これを超えて離れたら canvas を捨てる。
  var NEAR_MARGIN = 900;

  function clear(container) {
    var st = states.get(container);
    if (st) {
      st.cancelled = true;
      if (st.onScroll) {
        container.removeEventListener("scroll", st.onScroll);
      }
      if (st.dragHandlers) {
        container.removeEventListener("mousedown", st.dragHandlers.down);
        window.removeEventListener("mousemove", st.dragHandlers.move);
        window.removeEventListener("mouseup", st.dragHandlers.up);
        container.style.cursor = "";
      }
      if (st.resizeObserver) {
        st.resizeObserver.disconnect();
      }
      if (st.pdf && st.pdf.destroy) {
        try {
          st.pdf.destroy();
        } catch (e) {
          /* 破棄済み等は無視 */
        }
      }
      states.delete(container);
    }
    container.innerHTML = "";
  }

  function render(container, url) {
    clear(container);
    container.classList.add("pdfjs-preview");
    // レイアウトの要（枠いっぱいに広げて自前スクロール）は CSS の読み込み順・キャッシュに
    // 依存しないよう inline でも当てる。style.css の .pdfjs-preview は背景色等の装飾のみ担う。
    container.style.alignSelf = "stretch";
    container.style.width = "100%";
    container.style.minWidth = "0";
    container.style.overflowY = "auto";
    container.style.overflowX = "auto";
    var loading = document.createElement("div");
    loading.className = "pdfjs-message";
    loading.textContent = "プレビューを読み込み中…";
    container.appendChild(loading);

    var st = {
      cancelled: false,
      pdf: null,
      userScale: 1,
      pageRatio: 1.414,
      onScroll: null,
      resizeObserver: null,
      scrollRaf: 0,
      relayoutTimer: 0,
      lastWidth: 0,
      dragHandlers: null,
    };
    states.set(container, st);
    attachDragPan(container, st);

    loadLib()
      .then(function (pdfjsLib) {
        if (st.cancelled) {
          return null;
        }
        // 同一オリジン・セッション Cookie は自動送出。FileResponse は Range 対応のため
        // PDF.js は必要ページのバイトだけ取得する（大きな PDF でも初回転送が軽い）。
        return pdfjsLib.getDocument({ url: url }).promise;
      })
      .then(function (pdf) {
        if (!pdf || st.cancelled) {
          return;
        }
        st.pdf = pdf;
        return pdf.getPage(1).then(function (firstPage) {
          if (st.cancelled) {
            return;
          }
          var vp = firstPage.getViewport({ scale: 1 });
          st.pageRatio = vp.height / vp.width;

          container.innerHTML = "";
          for (var n = 1; n <= pdf.numPages; n++) {
            var wrap = document.createElement("div");
            wrap.className = "pdfjs-page";
            wrap.dataset.pageNumber = String(n);
            wrap.style.width = pageCssWidth(container, st) + "px";
            wrap.style.height = estimatePageHeight(container, st) + "px";
            container.appendChild(wrap);
          }

          st.onScroll = function () {
            if (st.scrollRaf) {
              return;
            }
            st.scrollRaf = requestAnimationFrame(function () {
              st.scrollRaf = 0;
              syncVisible(container);
            });
          };
          container.addEventListener("scroll", st.onScroll);

          st.lastWidth = container.clientWidth;
          // 枠幅が変わったら（ウィンドウリサイズ、パネル幅変更、スタイルシートの遅延適用等）
          // 全ページを描き直す。ResizeObserver は初回 observe でも 1 回発火するため、幅が
          // 実際に変わった時だけ処理する。デバウンスで連続リサイズ中の再描画ラッシュを防ぐ。
          if (typeof ResizeObserver === "function") {
            st.resizeObserver = new ResizeObserver(function () {
              var w = container.clientWidth;
              // 8px 未満の変化は無視（スクロールバー出現による幅変動での再描画ループ防止）。
              if (!w || Math.abs(w - st.lastWidth) < 8) {
                return;
              }
              st.lastWidth = w;
              clearTimeout(st.relayoutTimer);
              st.relayoutTimer = setTimeout(function () {
                relayout(container);
              }, 150);
            });
            st.resizeObserver.observe(container);
          }

          syncVisible(container);
        });
      })
      .catch(function (err) {
        if (st.cancelled) {
          return;
        }
        container.innerHTML = "";
        var msg = document.createElement("div");
        msg.className = "pdfjs-message pdfjs-message--error";
        msg.textContent = "プレビューを表示できませんでした。ダウンロードしてご確認ください。";
        container.appendChild(msg);
        if (window.console) {
          console.error("PdfPreview.render:", err);
        }
      });
  }

  // 1 ページの CSS 表示幅。枠幅から余白＋縦スクロールバー分（20px）を引いた基準幅 × ズーム倍率。
  // 20px 引くのは、複数ページで縦スクロールバーが出た瞬間に枠幅が狭まっても横スクロールバーを
  // 出さないため。userScale > 1 では枠より広くなり .pdfjs-preview の横スクロールで全体を見る。
  function pageCssWidth(container, st) {
    var base = Math.max(80, (container.clientWidth || 320) - 20);
    return Math.round(base * st.userScale);
  }

  function estimatePageHeight(container, st) {
    return Math.round(pageCssWidth(container, st) * st.pageRatio);
  }

  // スクロールバーだけでなくマウスのドラッグでもページを動かせるようにする（原本の
  // .pdf-view-box の initDragScroll と同じ操作感）。中身が枠に収まっている軸は動かさない。
  // 縦（複数ページ）・横（＋ズームで枠より広い時）どちらもドラッグでパンできる。
  function attachDragPan(container, st) {
    var dragging = false;
    var startX = 0;
    var startY = 0;
    var startLeft = 0;
    var startTop = 0;

    function down(e) {
      if (e.button !== 0) {
        return;
      }
      // ネイティブのスクロールバー上でのドラッグはブラウザに任せる（clientWidth/Height は
      // スクロールバーを除いた内寸なので、その外側なら scrollbar 上のクリック）。
      var rect = container.getBoundingClientRect();
      if (
        e.clientX > rect.left + container.clientWidth ||
        e.clientY > rect.top + container.clientHeight
      ) {
        return;
      }
      var canX = container.scrollWidth - container.clientWidth > 1;
      var canY = container.scrollHeight - container.clientHeight > 1;
      if (!canX && !canY) {
        return;
      }
      dragging = true;
      startX = e.clientX;
      startY = e.clientY;
      startLeft = container.scrollLeft;
      startTop = container.scrollTop;
      container.style.cursor = "grabbing";
      e.preventDefault();
    }
    function move(e) {
      if (!dragging) {
        return;
      }
      container.scrollLeft = startLeft - (e.clientX - startX);
      container.scrollTop = startTop - (e.clientY - startY);
    }
    function up() {
      if (!dragging) {
        return;
      }
      dragging = false;
      updatePanCursor(container);
    }

    container.addEventListener("mousedown", down);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    st.dragHandlers = { down: down, move: move, up: up };
  }

  // 中身が枠からはみ出していれば「掴めます」のカーソルにする。
  function updatePanCursor(container) {
    var pannable =
      container.scrollWidth - container.clientWidth > 1 ||
      container.scrollHeight - container.clientHeight > 1;
    container.style.cursor = pannable ? "grab" : "";
  }

  // 枠のスクロール位置に応じて、表示付近のページを描画し、離れたページの canvas を解放する。
  function syncVisible(container) {
    var st = states.get(container);
    if (!st || !st.pdf || st.cancelled) {
      return;
    }
    var cr = container.getBoundingClientRect();
    container.querySelectorAll(".pdfjs-page").forEach(function (wrap) {
      var r = wrap.getBoundingClientRect();
      var near = r.bottom > cr.top - NEAR_MARGIN && r.top < cr.bottom + NEAR_MARGIN;
      if (near) {
        renderPage(container, wrap);
      } else {
        releasePage(container, wrap);
      }
    });
    updatePanCursor(container);
  }

  function renderPage(container, wrap) {
    var st = states.get(container);
    if (!st || !st.pdf || st.cancelled) {
      return;
    }
    if (wrap.dataset.rendered === "1" || wrap.dataset.rendering === "1") {
      return;
    }
    wrap.dataset.rendering = "1";
    var pageNumber = parseInt(wrap.dataset.pageNumber, 10);

    st.pdf
      .getPage(pageNumber)
      .then(function (page) {
        if (st.cancelled || !wrap.isConnected) {
          wrap.dataset.rendering = "";
          return;
        }
        var cssWidth = pageCssWidth(container, st);
        var base = page.getViewport({ scale: 1 });
        // 高 DPI 端末で滲まないよう実描画は devicePixelRatio 倍。CSS 側で等倍に戻す。
        var dpr = window.devicePixelRatio || 1;
        var viewport = page.getViewport({ scale: (cssWidth / base.width) * dpr });

        var canvas = document.createElement("canvas");
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = "100%";
        canvas.style.height = "auto";

        wrap.style.height = "";
        wrap.style.width = cssWidth + "px"; // ズームで枠より広くなり得る
        wrap.innerHTML = "";
        wrap.appendChild(canvas);

        return page.render({ canvasContext: canvas.getContext("2d"), viewport: viewport }).promise.then(
          function () {
            wrap.dataset.rendered = "1";
            wrap.dataset.rendering = "";
          },
          function (err) {
            wrap.dataset.rendering = "";
            if (window.console && err && err.name !== "RenderingCancelledException") {
              console.error("PdfPreview.renderPage", pageNumber, err);
            }
          }
        );
      })
      .catch(function (err) {
        wrap.dataset.rendering = "";
        if (window.console) {
          console.error("PdfPreview.getPage", pageNumber, err);
        }
      });
  }

  function releasePage(container, wrap) {
    if (wrap.dataset.rendered !== "1") {
      return;
    }
    var st = states.get(container);
    wrap.innerHTML = "";
    wrap.dataset.rendered = "";
    if (st) {
      wrap.style.width = pageCssWidth(container, st) + "px";
      wrap.style.height = estimatePageHeight(container, st) + "px";
    }
  }

  // 全ページを一旦プレースホルダ（現在の幅・高さの目安）へ戻す。canvas は捨てる。
  function resizePlaceholders(container, st) {
    container.querySelectorAll(".pdfjs-page").forEach(function (wrap) {
      wrap.dataset.rendered = "";
      wrap.dataset.rendering = "";
      wrap.innerHTML = "";
      wrap.style.width = pageCssWidth(container, st) + "px";
      wrap.style.height = estimatePageHeight(container, st) + "px";
    });
  }

  // 枠幅の変化・ズームで再レイアウトする。ズームの起点は「今表示している中央」。
  // 変更前に中央にあった文書上の点（縦横それぞれ scrollWidth/Height に対する割合）を覚え、
  // プレースホルダをリサイズした後で同じ点が中央に来るよう scroll 位置を復元する。
  // 原本 zoomPdf は transform-origin:top center（＝上端中央）固定だったが、拡大した箇所を
  // 見続けられるよう「表示中の中央」を起点にする。
  function relayout(container) {
    var st = states.get(container);
    if (!st || st.cancelled) {
      return;
    }
    var prevW = container.scrollWidth;
    var prevH = container.scrollHeight;
    var hadX = prevW > container.clientWidth + 1;
    var hadY = prevH > container.clientHeight + 1;
    var fracX = hadX ? (container.scrollLeft + container.clientWidth / 2) / prevW : 0;
    var fracY = hadY ? (container.scrollTop + container.clientHeight / 2) / prevH : 0;

    resizePlaceholders(container, st);

    if (hadX) {
      container.scrollLeft = fracX * container.scrollWidth - container.clientWidth / 2;
    }
    if (hadY) {
      container.scrollTop = fracY * container.scrollHeight - container.clientHeight / 2;
    }

    syncVisible(container);
  }

  // ＋/− 用。倍率を掛けて表示中ページを描き直す。common.js の zoomPdf から委譲される。
  function zoom(container, factor) {
    var st = states.get(container);
    if (!st) {
      return;
    }
    var next = Math.max(MIN_SCALE, Math.min(MAX_SCALE, st.userScale * factor));
    if (next === st.userScale) {
      return;
    }
    st.userScale = next;
    relayout(container);
  }

  window.PdfPreview = { render: render, clear: clear, zoom: zoom };

  // 編集画面（サーバー側 {% if %} で PDF.js 枠を直接レンダリング）向けの自動初期化。
  // 保管画面２・詳細ポップアップは JS 側（setupActiveDoc / renderDetailPopup）が明示的に呼ぶ。
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".pdfjs-preview[data-pdf-url]").forEach(function (el) {
      render(el, el.dataset.pdfUrl);
    });
  });
})();
