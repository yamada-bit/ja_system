/*
 * 共通JS。HTML確定版(index.html)のpopup-select/popup-detail/overlay-modal関連の実装を、
 * 実データAPI(core.api.BaseOptionListAPIView等)に接続する形で移植したもの。
 * 原本は`popupPopupMasterData`というハードコード配列を参照するモックだったが、
 * 実装ではfetch()で実データ(JSON)を取得する。値(value=DBの主キー)と表示ラベルを分離して
 * 扱う必要があるため、対象inputは「表示用(readonly text)」「送信用(hidden)」の2つを
 * 1組として扱う（hidden側の`data-display`属性で表示用inputのidを紐付ける）。
 */

function getCsrfToken() {
  const match = document.cookie.match(/csrftoken=([^;]+)/);
  return match ? match[1] : "";
}

/*
 * 検索・閲覧画面の「一括選択」ボタン。原本index.htmlのtoggleAllCheckboxes()と同じロジック
 * （バックエンド不要な純クライアント処理のため、一括ダウンロード/一括編集と違いdisabledにしない）。
 */
let allCheckedState = false;
function toggleAllCheckboxes() {
  const btn = document.getElementById("btn-toggle-all");
  const checkboxes = document.querySelectorAll(".row-checkbox");
  allCheckedState = !allCheckedState;
  checkboxes.forEach((cb) => (cb.checked = allCheckedState));
  if (btn) btn.textContent = allCheckedState ? "一括解除" : "一括選択";
}

/*
 * 検索・閲覧画面の「一括編集」ボタン。原本index.htmlのstartBulkEdit()の「1件も選択されて
 * いなければalertして中断」する部分だけを再現する。原本は続けて選択行をJSでスクレイプし
 * 遷移まで行うが、本実装は選択pksを通常のPOST送信でサーバー（BulkEditStartView）へ渡すため、
 * ここが担うのはクライアント側の未選択ガードのみ（サーバー側にも同じ検証を残してある。
 * 文言はalert()自体が原本の最終仕様として機能している箇所のため踏襲する）。
 */
function startBulkEdit() {
  const checked = document.querySelectorAll(".row-checkbox:checked");
  if (checked.length === 0) {
    alert("編集するデータが選択されていません。");
    return false;
  }
  return true;
}

/*
 * 文書/契約書 検索・閲覧画面の列見出しソートリンク用（簡易設計指示書Rev1_1 検索・閲覧・変更
 * シートB244,245「検索結果が1万件を超えている場合はソートに時間が掛かる旨、アラート表示する」）。
 * 件数はテンプレート側で`.result-table`の`data-result-count`属性に埋め込み済み
 * （page_obj.paginator.count）。この属性が無い一覧画面（職員マスタ等）は元々1万件規模を
 * 想定していないため対象外とし、クリックイベントの委譲先を属性の有無で判定する。
 */
document.addEventListener("click", (e) => {
  const link = e.target.closest(".sort-link");
  if (!link) return;
  const table = link.closest("[data-result-count]");
  if (!table) return;
  const count = parseInt(table.dataset.resultCount, 10);
  if (count > 10000 && !confirm("ソートに時間が掛かる可能性があります。よろしいですか？")) {
    e.preventDefault();
  }
});

/*
 * 検索・閲覧画面「文書イメージ」欄。原本index.htmlには実データ連携が無く、行クリックで
 * タイトルの固定シミュレーション文言を表示するだけだったが（openDetailPopup()と同名の
 * search-preview-title要素）、ユーザー要望で実ファイルのプレビュー表示に対応する。
 * previewUrlはダウンロード権限（can_download）が無い場合はテンプレート側で空文字列にして
 * 渡される。2026-08-13ユーザー報告対応：その場合は権限不足が理由だと分かる文言を表示する
 * （documents/edit.html等のpreview_kind分岐と同じ考え方）。
 *
 * previewKindは"image"/"pdf"/""（core.file_type_services.get_preview_kind、テンプレート側の
 * preview_kindフィルタ経由）。2026-08-17ユーザー報告対応：以前はcan_downloadのみでgatingし
 * 拡張子を見ていなかったため、Excel等ブラウザがinline表示できない形式でもiframe.srcに
 * そのまま流し込んでいた。行クリックはダブルクリック（詳細ポップアップを開く操作）の前段
 * としても発火するため、Content-Disposition:inlineで返してもブラウザが自動的にダウンロード
 * を開始してしまい、「詳細ポップアップを開いた瞬間にダウンロードが実行される」という
 * 意図しない副作用になっていた。image/pdf以外はiframeへ読み込ませず、非対応の案内を出す。
 *
 * isDeletedは"1"/""（テンプレート側のtruthy判定用に文字列で渡す）。品質レビューで発見：
 * PreviewView/DetailAPIViewをis_deleted=Falseでのみ取得するよう修正した際、この行クリック
 * プレビューだけpreviewUrlをcan_downloadのみでgatingしたままだったため、メイン画面お知らせ
 * 「直近Xヵ月以内で削除された文書/契約書」一覧から行をクリックすると404相当（iframeが空）に
 * なっていた。previewUrl自体はテンプレート側で既にnot is_deletedをgatingに加えたが、
 * 権限不足の文言のまま表示すると理由が伝わらないため、削除済みの場合は専用の文言を出す
 * （2026-08-25修正）。
 */
function showSearchPreview(title, previewUrl, kind, previewKind, isDeleted) {
  const frame = document.getElementById("search-preview-frame");
  const placeholder = document.getElementById("search-preview-placeholder");
  const titleEl = document.getElementById("search-preview-title");
  const label = kind === "contract" ? "契約書" : "文書";
  if (previewUrl && (previewKind === "image" || previewKind === "pdf")) {
    frame.src = previewUrl;
    frame.style.display = "";
    placeholder.style.display = "none";
  } else {
    frame.style.display = "none";
    frame.removeAttribute("src");
    placeholder.style.display = "";
    if (isDeleted) {
      titleEl.innerHTML = `<strong>${title}</strong><br><br>本${label}は削除されているため、プレビューを表示できません。`;
    } else if (!previewUrl) {
      titleEl.innerHTML = `<strong>${title}</strong><br><br>プレビューを表示するには「${label}-ダウンロード」権限が必要です。権限管理画面でご確認ください。`;
    } else {
      titleEl.innerHTML = `<strong>${title}</strong><br><br>この形式のファイルはプレビュー表示に対応していません。ダウンロードしてご確認ください。`;
    }
  }
}

/*
 * 保管画面２（契約書モード）の「関連書類」欄。原本index.html:852-873の
 * handleRelatedFileChange()/removeRelatedFileRow()を移植。ファイルを選択するたびその行を
 * 「📎 ファイル名 ×」表示に切り替え、空の行を1つ追加する（複数ファイルを1つずつ添付できる）。
 * 実送信のため、原本には無い name="related_files"（一括登録時は文書ごとに
 * "related_files_{doc-index}"）を新規行のinputに付与する。コンテナ・フィールド名は
 * クリックされたinput自身から取得するため、id="storage-file-inputs-container"（編集画面、
 * 単一文書）とid="storage-file-inputs-container-N"（保管画面、複数文書の一括登録時に
 * 文書ごとの関連書類を独立して扱うためdata-doc-index方式で分離）のどちらでも動作する。
 */
function handleRelatedFileChange(input) {
  if (!input.files || input.files.length === 0) return;
  const filename = input.files[0].name;
  const fieldName = input.name;
  const row = input.closest(".related-file-row");
  const container = input.closest("[id^='storage-file-inputs-container']");

  // 表示切り替えは row.innerHTML の書き換えではなく、input自体を非表示にした上で表示用の
  // span/buttonを追加で挿入する形にする。row.innerHTMLで置き換えるとイベント発火元のinput
  // （＝ユーザーが選択したFileオブジェクトを保持している唯一の要素）自体がDOMから消えてしまい、
  // フォーム送信時にそのファイルの実データが一切送られない不具合があった（画面には
  // 「📎 ファイル名」と表示されるため、登録後に該当の関連書類が保存されていないことでしか
  // 気づけなかった）。inputを残したまま非表示にすることで、name属性が同じ複数のinputとして
  // 通常のmultipart/form-data送信に乗り、サーバー側のrequest.FILES.getlist()で全件拾える。
  input.style.display = "none";
  const nameSpan = document.createElement("span");
  nameSpan.className = "related-file-name";
  nameSpan.textContent = `\u{1F4CE} ${filename}`;
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn-delete-file";
  deleteBtn.textContent = "×";
  deleteBtn.onclick = function () {
    removeRelatedFileRow(deleteBtn);
  };
  row.appendChild(nameSpan);
  row.appendChild(deleteBtn);

  const newRow = document.createElement("div");
  newRow.className = "related-file-row";
  newRow.innerHTML = `<input type="file" name="${fieldName}" onchange="handleRelatedFileChange(this)">`;
  container.appendChild(newRow);
}

function removeRelatedFileRow(btn) {
  btn.closest(".related-file-row").remove();
}

/*
 * 編集モードで既に保存済みの関連書類を削除する場合、新規行と違いサーバー側のレコードを
 * 消す必要があるため、対象IDをhidden(id_remove_related_ids)にカンマ区切りで積んでから行を消す
 * （ContractEditView.post側でこの値を見て該当RelatedFileを削除する）。
 */
/*
 * 契約金額欄（onblur）。原本index.html:1554-1564のformatCurrency()そのまま移植。
 */
function formatCurrency(inputElement) {
  const value = inputElement.value.replace(/[^0-9]/g, "");
  inputElement.value = value !== "" ? Number(value).toLocaleString("ja-JP") : "";
}

function removeExistingRelatedFile(btn, relatedFileId) {
  const hidden = document.getElementById("id_remove_related_ids");
  if (hidden) {
    const ids = hidden.value ? hidden.value.split(",") : [];
    ids.push(String(relatedFileId));
    hidden.value = ids.join(",");
  }
  btn.closest(".related-file-row").remove();
}

/* ==========================================
   popup-select（部署/分類/年/カテゴリー選択ポップアップ）
   ========================================== */
// 検索キーワードの半角全角表記ゆれ吸収用。NFKC正規化により全角英数字は半角に、
// 半角カタカナは全角カタカナに統一されるため、双方をこれに通してから比較すれば
// 数字・カタカナ・アルファベットいずれの半角全角差異も同一視できる。
function normalizeSearchText(str) {
  return (str || "").normalize("NFKC").toLowerCase();
}

let popupOptionsCache = {};
let activePopupTargetInput = null;
let activePopupDisplayInput = null;
let activePopupType = "";
let activePopupMode = "storage";
let activePopupApiUrl = "";

function openPopupPopup(btn, type, mode, apiUrl) {
  // 原本index.html(html5)に合わせ previousElementSibling || nextElementSibling。ja_pjの
  // PopupSelectWidgetは「表示要素→hidden input→選択ボタン」の順で描画するため実際には
  // previousElementSiblingで確定するが、原本との差異を残さないため保険のorも移植する。
  activePopupTargetInput = btn.previousElementSibling || btn.nextElementSibling; // hidden input
  activePopupDisplayInput = document.getElementById(activePopupTargetInput.dataset.display);
  activePopupType = type;
  activePopupMode = mode;
  activePopupApiUrl = apiUrl;

  const titleSpan = document.getElementById("popup-select-title");
  if (type === "group") titleSpan.textContent = "分類選択";
  if (type === "year") titleSpan.textContent = "対象年選択";
  if (type === "category") titleSpan.textContent = "カテゴリー選択";
  if (type === "dept") titleSpan.textContent = "部署選択";

  const searchInput = document.getElementById("popup-select-search");
  searchInput.value = "";
  searchInput.style.display = type === "year" ? "none" : "block";

  const pop = document.getElementById("popup-select");
  pop.classList.remove("hidden-popup");

  // 配置は「中身を描画して実寸を確定してから」行う（原本 html5 の openPopupPopup が
  // renderPopupPopupItems() を先頭で呼ぶよう変更されたのに合わせる。Rev1.3で権限管理編集の
  // 表示欄が rows=5 の textarea になりポップアップが縦に伸びたため、下端はみ出し判定に
  // 実際の高さが要る）。ja_pjは選択肢を非同期fetchする場合があるので、renderの後に必ず
  // positionPopupPopup() を呼ぶ。
  const cacheKey = `${apiUrl}|${type}`;
  if (popupOptionsCache[cacheKey]) {
    renderPopupPopupItems();
    positionPopupPopup(btn);
  } else {
    // apiUrlが既にクエリ文字列を含む場合（permissions:api_optionsのdoc_kbn等）に備え、
    // 単純な文字列結合ではなく区切り文字を判定して連結する。
    const sep = apiUrl.includes("?") ? "&" : "?";
    fetch(`${apiUrl}${sep}type=${type}`)
      .then((r) => r.json())
      .then((data) => {
        popupOptionsCache[cacheKey] = data.items || [];
        renderPopupPopupItems();
        positionPopupPopup(btn);
      });
  }
}

/**
 * popup-select をトリガーボタン基準で配置する（原本 index.html html5 の openPopupPopup 配置ロジックの移植）。
 * 縦: 基本はボタン下(+5px)。ポップアップの実高さで下端からはみ出す場合はボタンの「上」へ反転し、
 *     上にも収まらなければ画面最上部に10pxだけ余白を取って貼り付ける。
 * 横: 基本はボタン左から-100px。描画後に再測して右端はみ出しを補正する。
 * 呼び出し側は renderPopupPopupItems() で中身を描画した「後」に呼ぶこと（実寸が要るため）。
 */
function positionPopupPopup(btn) {
  const rect = btn.getBoundingClientRect();
  const pop = document.getElementById("popup-select");
  const popRect = pop.getBoundingClientRect();
  const windowWidth = window.innerWidth;
  const windowHeight = window.innerHeight;

  let topPos = window.scrollY + rect.bottom + 5;
  if (rect.bottom + 5 + popRect.height > windowHeight) {
    topPos = window.scrollY + rect.top - popRect.height - 5;
    if (topPos < window.scrollY) {
      topPos = window.scrollY + 10;
    }
  }
  pop.style.top = topPos + "px";

  let leftPos = window.scrollX + rect.left - 100;
  pop.style.left = leftPos + "px";
  const updatedPopRect = pop.getBoundingClientRect();
  if (updatedPopRect.right > windowWidth) {
    leftPos = window.scrollX + windowWidth - updatedPopRect.width - 10;
    if (leftPos < window.scrollX) {
      leftPos = window.scrollX + 10;
    }
    pop.style.left = leftPos + "px";
  }
}

function closePopupPopup() {
  document.getElementById("popup-select").classList.add("hidden-popup");
}

function renderPopupPopupItems() {
  const container = document.getElementById("popup-select-items-container");
  container.innerHTML = "";

  const cacheKey = `${activePopupApiUrl}|${activePopupType}`;
  const master = popupOptionsCache[cacheKey] || [];
  // 数字・カタカナ・アルファベットの半角全角表記ゆれを吸収するため、NFKC正規化してから比較する
  // （全角英数字→半角、半角カタカナ→全角カタカナに揃う。簡易設計指示書の検索要件に合わせた対応）
  const filter = normalizeSearchText(document.getElementById("popup-select-search").value);

  const currentValStr = activePopupTargetInput ? activePopupTargetInput.value : "";
  const currentValues = currentValStr.split(",").map((v) => v.trim()).filter((v) => v);

  const isGroupSearch = activePopupType === "group" && activePopupMode === "search";

  if (isGroupSearch) {
    const selectAllRow = document.createElement("div");
    selectAllRow.className = "popup-select-row";
    selectAllRow.style.cssText =
      "border-bottom: 1px solid #ddd; padding-bottom: 6px; margin-bottom: 6px; font-weight: bold;";
    selectAllRow.innerHTML = `<label><input type="checkbox" id="popup-select-all-checkbox"> 全て選択</label>`;
    container.appendChild(selectAllRow);

    const selectAllCb = selectAllRow.querySelector('input[type="checkbox"]');
    selectAllCb.addEventListener("change", function () {
      container.querySelectorAll(".item-checkbox").forEach((cb) => {
        cb.checked = selectAllCb.checked;
      });
      selectAllCb.parentElement.lastChild.nodeValue = selectAllCb.checked ? " 全て解除" : " 全て選択";
    });
  }

  master.forEach((item) => {
    if (filter && !normalizeSearchText(item.label).includes(filter)) return;
    const row = document.createElement("div");
    row.className = "popup-select-row";

    // item.labelはマスタのフリーテキスト項目（部署名・分類名・カテゴリー名等）を含み、
    // HTMLエスケープ無しでinnerHTMLに埋め込むと格納型XSSになるため、DOM APIで組み立てる。
    const label = document.createElement("label");
    const input = document.createElement("input");
    if (activePopupMode === "search") {
      input.type = "checkbox";
      input.className = "item-checkbox";
      input.checked = currentValues.includes(String(item.value));
    } else {
      input.type = "radio";
      input.name = "pop-radio";
      input.checked = currentValues[0] === String(item.value);
    }
    input.value = item.value;
    input.dataset.label = item.label;
    label.appendChild(input);
    label.appendChild(document.createTextNode(" " + item.label));
    row.appendChild(label);
    container.appendChild(row);
  });

  if (isGroupSearch) {
    const itemCheckboxes = container.querySelectorAll(".item-checkbox");
    const selectAllCb = container.querySelector("#popup-select-all-checkbox");

    const syncSelectAllState = () => {
      if (!selectAllCb) return;
      const allChecked =
        itemCheckboxes.length > 0 && Array.from(itemCheckboxes).every((cb) => cb.checked);
      selectAllCb.checked = allChecked;
      selectAllCb.parentElement.lastChild.nodeValue = allChecked ? " 全て解除" : " 全て選択";
    };

    itemCheckboxes.forEach((cb) => cb.addEventListener("change", syncSelectAllState));
    syncSelectAllState();
  }
}

function filterPopupPopupItems() {
  renderPopupPopupItems();
}

function submitPopupPopupSelection() {
  const container = document.getElementById("popup-select-items-container");

  if (activePopupMode === "search") {
    const cbs = container.querySelectorAll(".item-checkbox:checked");
    const values = [];
    const labels = [];
    cbs.forEach((cb) => {
      values.push(cb.value);
      labels.push(cb.dataset.label);
    });
    activePopupTargetInput.value = values.join(",");
    if (activePopupDisplayInput) activePopupDisplayInput.value = labels.join(", ");
  } else {
    const rad = container.querySelector('input[type="radio"]:checked');
    if (rad) {
      activePopupTargetInput.value = rad.value;
      if (activePopupDisplayInput) activePopupDisplayInput.value = rad.dataset.label;
      activePopupTargetInput.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  closePopupPopup();
}

/* popup-selectのドラッグ移動・リサイズ（原本のUXをそのまま踏襲） */
document.addEventListener("DOMContentLoaded", () => {
  const pHeader = document.querySelector(".popup-select-header");
  const pWindow = document.getElementById("popup-select");
  if (!pHeader || !pWindow) return;

  let isMoving = false;
  let moveOffsetX = 0;
  let moveOffsetY = 0;
  pHeader.addEventListener("mousedown", (e) => {
    isMoving = true;
    pHeader.style.cursor = "move";
    moveOffsetX = e.clientX - pWindow.offsetLeft;
    moveOffsetY = e.clientY - pWindow.offsetTop;
  });
  document.addEventListener("mousemove", (e) => {
    if (!isMoving) return;
    pWindow.style.left = e.clientX - moveOffsetX + "px";
    pWindow.style.top = e.clientY - moveOffsetY + "px";
  });
  document.addEventListener("mouseup", () => {
    if (isMoving) {
      isMoving = false;
      pHeader.style.cursor = "default";
    }
  });

  const rHandle = document.getElementById("popup-select-resize");
  if (!rHandle) return;
  let isResizing = false;
  let startW = 0;
  let startH = 0;
  let startMouseX = 0;
  let startMouseY = 0;
  rHandle.addEventListener("mousedown", (e) => {
    isResizing = true;
    e.preventDefault();
    startW = pWindow.offsetWidth;
    startH = pWindow.offsetHeight;
    startMouseX = e.clientX;
    startMouseY = e.clientY;
  });
  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const nextW = startW + (e.clientX - startMouseX);
    const nextH = startH + (e.clientY - startMouseY);
    if (nextW > 200) pWindow.style.width = nextW + "px";
    const itemsBox = document.getElementById("popup-select-items-container");
    if (nextH > 150 && itemsBox) itemsBox.style.maxHeight = nextH - 100 + "px";
  });
  document.addEventListener("mouseup", () => {
    isResizing = false;
  });
});

/* ==========================================
   PDFプレビューのズーム・ドラッグスクロール（原本のzoomPdf/initDragScrollをそのまま移植）
   ========================================== */
let currentPdfScale = 1.0;

// PDFプレビューはiframe（実プレビュー時）で表示しており、iframeは別ブラウジング
// コンテキストのためmousedown/mousemoveがそこで止まってbox側に伝播しない
// （ドラッグの開始点にできない・ドラッグ中カーソルがiframe上を通ると引っかかる）。
// ドラッグ操作中だけでなく、拡大してドラッグ可能な状態（cursor:grab）になっている間は
// 常にiframeをpointer-events:noneにしてイベントをboxへ素通しし、プレビュー領域全体から
// ドラッグを開始できるようにする。
function setPdfIframesInteractive(box, interactive) {
  box.querySelectorAll("iframe").forEach((frame) => {
    frame.style.pointerEvents = interactive ? "" : "none";
  });
}

// transform-origin:top centerの.pdf-mock-pageを、親.pdf-scroll-area（拡大後の
// 最大サイズ分の幅をあらかじめ確保したラッパー）の中央に揃える。box自体のscrollLeftは
// 0未満にできないため、拡大縮小のたびにこの中央位置へ戻す必要がある。
function centerPdfScroll(box) {
  const area = box.querySelector(".pdf-scroll-area");
  if (area) {
    box.scrollLeft = (area.offsetWidth - box.clientWidth) / 2;
  }
}

function zoomPdf(pageId, amount) {
  currentPdfScale += amount;
  if (currentPdfScale < 0.5) currentPdfScale = 0.5;
  if (currentPdfScale > 3.0) currentPdfScale = 3.0;

  const page = document.getElementById(pageId);
  if (page) {
    page.style.transform = `scale(${currentPdfScale})`;
    const box = page.closest(".pdf-view-box, .pdf-view-box2");
    if (box) {
      if (currentPdfScale > 1.0) {
        box.style.cursor = "grab";
        setPdfIframesInteractive(box, false);
      } else {
        box.style.cursor = "default";
        centerPdfScroll(box);
        box.scrollTop = 0;
        setPdfIframesInteractive(box, true);
      }
    }
  }
}

function initDragScroll(boxId) {
  const box = document.getElementById(boxId);
  if (!box) return;

  let isDown = false;
  let startX, startY, scrollLeft, scrollTop;

  box.addEventListener("mousedown", (e) => {
    if (box.style.cursor !== "grab") return;
    isDown = true;
    box.style.cursor = "grabbing";
    startX = e.pageX - box.offsetLeft;
    startY = e.pageY - box.offsetTop;
    scrollLeft = box.scrollLeft;
    scrollTop = box.scrollTop;
  });
  box.addEventListener("mouseleave", () => {
    if (!isDown) return;
    isDown = false;
    box.style.cursor = "grab";
  });
  box.addEventListener("mouseup", () => {
    if (!isDown) return;
    isDown = false;
    box.style.cursor = "grab";
  });
  box.addEventListener("mousemove", (e) => {
    if (!isDown) return;
    e.preventDefault();
    const x = e.pageX - box.offsetLeft;
    const y = e.pageY - box.offsetTop;
    const walkX = (x - startX) * 1.5;
    const walkY = (y - startY) * 1.5;
    box.scrollLeft = scrollLeft - walkX;
    box.scrollTop = scrollTop - walkY;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initDragScroll("detail-pdf-view-box");
  initDragScroll("storage-pdf-view-box");
  // detail-pdf-view-boxはpopup-detailがdisplay:noneの間はoffsetWidthが0のため、
  // ここでは初期表示時から見えているstorage-pdf-view-boxのみ中央寄せする
  // （detail側はrenderDetailPopup()でポップアップ表示直後に呼ぶ）。
  const storageBox = document.getElementById("storage-pdf-view-box");
  if (storageBox) centerPdfScroll(storageBox);
});

/* ==========================================
   popup-detail（検索結果詳細ポップアップ、AJAX）
   ========================================== */
function openDetailPopup(apiUrl, kind) {
  fetch(apiUrl)
    .then((r) => r.json())
    .then((data) => renderDetailPopup(data, kind));
}

function closeDetailPopup() {
  document.getElementById("popup-detail").style.display = "none";
}

function renderDetailPopup(data, kind) {
  const label = kind === "document" ? "文書" : "契約書";
  const banner = document.getElementById("detail-alert-banner");
  // バナーの配色は原本index.html:1195-1203のclickNoticeLink()に対応（赤=期限切れ/まもなく期限、
  // 紫=削除済み）。「まもなく更新月」（原本index.html:1146）は、原本モックでは静的演出
  // だったため実データ上の判定基準（core.notice_services.is_expiring_soon）を新設して対応した。
  // 削除済みの文言はxlsx 検索・閲覧・変更!B348,B675(Rev1.2)「本文書/本契約書は削除されています」
  // に合わせた（2026-08-24、完全削除機能廃止に伴い「ゴミ箱保管中」表記もやめた）。
  if (data.is_deleted) {
    banner.textContent = `本${label}は削除されています`;
    banner.style.backgroundColor = "#efe5fd";
    banner.style.borderColor = "#b388ff";
    banner.style.color = "#4a148c";
    banner.style.display = "block";
  } else if (data.is_expired) {
    banner.textContent = `この${label}は有効期限切れです`;
    banner.style.backgroundColor = "";
    banner.style.borderColor = "";
    banner.style.color = "";
    banner.style.display = "block";
  } else if (data.is_expiring_soon) {
    banner.textContent = `この${label}はまもなく有効期限（更新月）を迎えます`;
    banner.style.backgroundColor = "";
    banner.style.borderColor = "";
    banner.style.color = "";
    banner.style.display = "block";
  } else {
    banner.style.display = "none";
  }
  document.getElementById("detail-view-title").textContent = data.title;
  // 原本index.html:986のopenDetailPopup()はバナーの状態に関わらず常に「[有効データ]」固定
  // （PDFモック見出しの装飾文言であり、実データ状態の表示はバナー側が担う）。
  document.getElementById("detail-mock-title").textContent = "[有効データ] " + data.title;

  // 実プレビュー（ユーザー依頼2026-08-12で追加）。documents/edit.htmlのpreview_kind分岐と
  // 同じ考え方で、data.preview_kind（"image"/"pdf"/null、can_download権限が無ければnull）と
  // data.preview_urlの両方が揃った時だけモック文言の代わりに実データを表示する。
  const previewImg = document.getElementById("detail-preview-image");
  const previewFrame = document.getElementById("detail-preview-frame");
  const previewDenied = document.getElementById("detail-preview-denied");
  const mockBody = document.getElementById("detail-mock-body");
  previewImg.style.display = "none";
  previewImg.removeAttribute("src");
  previewFrame.style.display = "none";
  previewFrame.removeAttribute("src");
  previewDenied.style.display = "none";
  mockBody.style.display = "";
  if (data.preview_kind === "image" && data.preview_url) {
    previewImg.src = data.preview_url;
    previewImg.style.display = "block";
    mockBody.style.display = "none";
  } else if (data.preview_kind === "pdf" && data.preview_url) {
    previewFrame.src = data.preview_url;
    previewFrame.style.display = "block";
    mockBody.style.display = "none";
  } else if (data.preview_kind === "image" || data.preview_kind === "pdf") {
    // 画像／PDFだが権限不足でpreview_urlが渡っていない（documents/contracts.api.DetailAPIView
    // 参照）。documents/edit.html・storage2.htmlと同じ理由（2026-08-13ユーザー報告対応）。
    const permissionLabel = kind === "contract" ? "契約書-ダウンロード" : "文書-ダウンロード";
    previewDenied.textContent = `プレビューを表示するには「${permissionLabel}」権限が必要です。権限管理画面でご確認ください。`;
    previewDenied.style.display = "block";
    mockBody.style.display = "none";
  }

  // 原本のopenDetailPopup()（index.html 984-1023行目）と同じ項目構成・順序・ラベルにする。
  // Rev1.1で「保存者」「保存日時」の行が追加された（旧仕様のモックには無かった）。
  let rows;
  if (kind === "document") {
    rows = [
      ["文書タイトル", data.title],
      ["部署", data.department],
      ["分類", data.group],
      ["年", `${data.year}年`],
      ["カテゴリー", data.category],
      ["保存期間", data.retention_period],
      ["有効期限", data.expiry_date],
      ["個人情報", data.privacy_flag ? "含まれる" : "含まれない"],
      ["保存者", data.uploader],
      ["保存日時", data.save_date],
      ["メモ欄", data.memo],
    ];
  } else {
    rows = [
      ["契約書タイトル", data.title],
      ["部署", data.department],
      ["分類", data.group],
      ["年", `${data.year}年`],
      ["カテゴリー", data.category],
      ["契約日", data.contract_date],
      ["契約期間", `${data.contract_period_start} ～ ${data.contract_period_end}`],
      ["契約更新日", data.renewal_date],
      ["契約金額", data.contract_amount ? `${Number(data.contract_amount).toLocaleString("ja-JP")} 円` : ""],
      ["契約先名", data.contract_partner],
      ["保存者", data.uploader],
      ["保存日時", data.save_date],
      ["関連書類", data.related_files && data.related_files.length ? data.related_files.map((f) => `📎 ${f}`).join("<br>") : "なし"],
      ["メモ欄", data.memo],
    ];
  }

  const view = document.getElementById("detail-properties-view");
  view.innerHTML =
    '<table class="search-condition-table" style="width:100%;">' +
    rows.map(([label, value]) => `<tr><td class="label">${label}</td><td>${value != null ? value : ""}</td></tr>`).join("") +
    "</table>";

  // ダウンロードボタン（xlsx 検索・閲覧・変更!B329-330「権限が無いログインユーザはボタンを
  // 非表示とする」、Rev1.1で「押下不可(disabled)」から仕様変更）。deleteBtnと同じ
  // style.display パターンで非表示にする。
  const dlBtn = document.getElementById("detail-download-btn");
  if (data.can_download && data.download_url) {
    dlBtn.style.display = "";
    dlBtn.onclick = () => {
      window.location.href = data.download_url;
    };
  } else {
    dlBtn.style.display = "none";
    dlBtn.onclick = null;
  }
  // 変更ボタン（xlsx 検索・閲覧・変更!B337,B663(Rev1.2)「削除されている(削除フラグがTrue)
  // 文書/契約書は、ボタンを非表示とする」）。以前は「disabled+title」パターン（削除済みでも
  // ボタン自体は表示したままグレーアウトする実装）だったが、これはdlBtn/deleteBtnがRev1.1で
  // 「押下不可(disabled)」から明示的に変更した「非表示(style.display)」パターンと矛盾していた
  // （2026-08-24再監査で発見：ダウンロードボタンの見落とし修正時に変更ボタン側の見直しが
  // 漏れていた）。edit_urlはis_deletedだけでなく契約書側は`can_edit_contract`（xlsx
  // 権限管理!B198「編集不可…「編集」「削除」ボタンを非表示にする」）でもNoneになるため、
  // dlBtn/deleteBtnと同じ「data.edit_urlの有無だけを見て表示/非表示を切り替える」に統一する
  // （「削除済みだから」と決め打ちしたtitle文言は、契約書の権限不足ケースでは誤りになるため
  // 廃止）。
  const editBtn = document.getElementById("detail-change-btn");
  if (data.edit_url) {
    editBtn.style.display = "";
    editBtn.onclick = () => {
      window.location.href = data.edit_url;
    };
  } else {
    editBtn.style.display = "none";
    editBtn.onclick = null;
  }
  // 削除ボタン。data.delete_urlがNoneになるのは、既に削除済み、または保存から1週間以上
  // 経過した文書・契約書（documents/contracts.services.can_delete）の場合
  // （xlsx 検索・閲覧・変更!B331,B337,B659,B663,B339-340,B664-665「削除済み、または初回登録から
  // 1週間以上経過しているものは削除不可。ボタンを非表示にする」、Rev1.2で削除済みの条件が追加され、
  // 2026-08-24に完全削除機能〈ユーザー依頼2026-08-12〉は廃止した）。
  const deleteBtn = document.getElementById("detail-delete-btn");
  if (data.delete_url) {
    deleteBtn.style.display = "";
    deleteBtn.onclick = () => triggerDeleteFromDetail(data.delete_url, kind);
  } else {
    deleteBtn.style.display = "none";
    deleteBtn.onclick = null;
  }

  document.getElementById("popup-detail").style.display = "block";
  // 表示直後（display:blockになった後）でないとoffsetWidthが0のまま計算されるため、ここで呼ぶ。
  const detailBox = document.getElementById("detail-pdf-view-box");
  if (detailBox) centerPdfScroll(detailBox);
}

function triggerDeleteFromDetail(deleteUrl, kind) {
  // documents/contracts.views.DeleteViewは論理削除のみを行う（Rev1.2で完全削除機能
  // 〈ユーザー依頼2026-08-12〉は廃止した。上記renderDetailPopup()のコメント参照）。
  const label = kind === "document" ? "文書" : "契約書";
  if (!confirm(`この${label}データを削除してもよろしいですか？`)) return;
  // documents/contracts双方のDeleteViewは`X-Requested-With`ヘッダーを見てJsonResponseを
  // 返すよう対応済み（原本フィデリティ監査で発見：以前はredirect()のHTMLをr.json()で
  // パースしようとして例外になり、削除自体は成功してもポップアップを閉じる・完了通知・
  // 一覧再描画のいずれも動かなかった）。r.okを確認してからjson()を呼ぶ。
  fetch(deleteUrl, {
    method: "POST",
    headers: { "X-CSRFToken": getCsrfToken(), "X-Requested-With": "XMLHttpRequest" },
  })
    .then((r) => {
      if (!r.ok) throw new Error("delete failed: " + r.status);
      return r.json();
    })
    .then((data) => {
      closeDetailPopup();
      alert(data.message || "削除しました。");
      window.location.reload();
    })
    .catch((err) => {
      console.error(err);
      alert("削除に失敗しました。もう一度お試しください。");
    });
}

/* ==========================================
   進捗オーバーレイ・登録/更新完了モーダル
   ========================================== */
function showProgress(msg, callback) {
  document.getElementById("progress-msg").textContent = msg;
  const fill = document.getElementById("progress-fill");
  const percent = document.getElementById("progress-percent");
  const overlay = document.getElementById("overlay-progress");
  fill.style.width = "0%";
  percent.textContent = "0%";
  overlay.style.display = "flex";
  let w = 0;
  const timer = setInterval(() => {
    w += 10;
    fill.style.width = w + "%";
    percent.textContent = w + "%";
    if (w >= 100) {
      clearInterval(timer);
      setTimeout(() => {
        overlay.style.display = "none";
        if (callback) callback();
      }, 200);
    }
  }, 50);
}

function closeRegisterModal() {
  document.getElementById("overlay-modal").style.display = "none";
}

// screen-authority-list（権限管理一覧）の固定列（職員番号/部署/氏名/役職/権限/操作）。
// style.css側の.col-1〜.col-6/.col-td-1〜.col-td-6は原本CSSそのまま（60px/102px/78px/100px幅を
// 前提にしたleft固定値のハードコード）だが、これは原本モックの固定文言（「本　店|ＤＸ推進課」等）
// を前提にした値で、実データ（部署名の長さ等）が変わると列幅がずれ、position:stickyの
// left値が実際の列幅と食い違って隣接列が重なったり隙間が空いたりする（横スクロール時に
// 「権限」列の手前で不自然な空白ができ、スクロールが終わらないように見える不具合の原因）。
// 実際に描画された列幅からleftを都度計算し直すことで、データに依存せず正しく重なるようにする。
// col-6（操作）は簡易設計指示書 Rev1.3（権限管理!AI10「画面変更」）でhtml5に追加された固定列。
// これをループ範囲に含めないと、CSSの固定値（.col-6 left:382px）のまま実際の1〜5列合計幅とズレ、
// 「操作」列が権限付与（文書管理）の列に重なる。
function fixAuthorityStickyOffsets() {
  const table = document.querySelector(".data-table-auth");
  if (!table) return;
  let cumulative = 0;
  for (let i = 1; i <= 6; i++) {
    const th = table.querySelector("thead th.col-" + i);
    if (!th) continue;
    th.style.left = cumulative + "px";
    table.querySelectorAll("tbody td.col-td-" + i).forEach((td) => {
      td.style.left = cumulative + "px";
    });
    cumulative += th.getBoundingClientRect().width;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  fixAuthorityStickyOffsets();
  window.addEventListener("resize", fixAuthorityStickyOffsets);
});
