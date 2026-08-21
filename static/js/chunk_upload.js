// チャンク分割アップロード（documents/contracts保管画面１から使用する。
// core.upload_views.BaseChunkUploadAPIViewが受け口）。ja_pj_old（static/js/chunk_upload.js）の
// 移植版。ただし本アプリのsave_pending_files/get_pending_filesは呼ばれるたびに既存のセッション
// 内容へ追記する設計のため、ja_pj_old側にあった「結合済みファイルを一旦別の保留プールへ貯めて
// 通常アップロードPOST側で合流させる」という中間層は不要（core/upload_services.py参照）。
//
// 大容量PDFはDjangoの1リクエストボディ上限（MAX_UPLOAD_SIZE_BYTES/DATA_UPLOAD_MAX_MEMORY_SIZE）に
// 引っかかるため、ファイルを小さなチャンクに分割し、順次POSTしてサーバー側で結合する。
// storage1.html側のsubmitハンドラが、選択されたファイルをmax_upload_size_bytes基準で
// サイズ判定し、超えるファイルだけこの関数に渡す（閾値以下のファイルは従来通り
// documents/contracts.UploadStep1View.postへの一括POSTのまま）。

// ja_pj_oldと同じチャンクサイズ。
const CHUNK_UPLOAD_CHUNK_SIZE = 5 * 1024 * 1024; // 5MB

// crypto.randomUUID()はSecure Context（HTTPS or localhost）でのみ利用可能。本番運用がTLS終端無し
// （HTTP）のままの場合、window.crypto.randomUUIDが存在せずTypeErrorになる可能性があるため
// （ja_pj_oldの同名関数と同じ理由）、使えない場合はMath.randomベースの簡易UUID風文字列に
// フォールバックする。upload_idはチャンクを一時的にグルーピングするためだけのキーで
// 暗号学的な強度は不要。
function generateUploadId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// 単体では閾値（settings.MAX_UPLOAD_SIZE_BYTES）以下と判定されたファイル群でも、まとめて
// 1回のPOSTで送ると合計サイズがDjangoの1リクエストボディ上限（settings.DATA_UPLOAD_MAX_MEMORY_SIZE、
// MAX_UPLOAD_SIZE_BYTESと同値）を超えてしまうことがある（例: 15MBのファイルを4つ選ぶと合計60MBになる）。
// 累積サイズがthresholdを超えない範囲で先頭から詰め込めるだけ詰め込み（withinBudget）、
// それであふれた分（overBudget）は、単体では閾値以下でもチャンク分割アップロードAPI経由
// （1ファイル1チャンクで完結）に回すことで、一括POST自体が失敗するリスクを避ける。
function splitFilesBySizeBudget(files, threshold) {
  const withinBudget = [];
  const overBudget = [];
  let runningTotal = 0;
  for (const f of files) {
    if (runningTotal + f.size > threshold) {
      overBudget.push(f);
    } else {
      withinBudget.push(f);
      runningTotal += f.size;
    }
  }
  return { withinBudget, overBudget };
}

// files: 選択されたFileの配列。1ファイルずつ・1ファイル内はチャンク順に直列でPOSTする
// （並列化するとサーバー側のセッション保留ファイル一覧への追記が競合し得るため）。
// 結合が完了したファイルはサーバー側セッションの保留ファイル一覧に貯まるだけで、本チャンクの
// バッチへの合流・画面遷移は呼び出し元（storage1.htmlのsubmitハンドラ）が続けて行う通常
// アップロードのPOST（documents/contracts.UploadStep1View.post）が担当するため、この関数自体は
// 画面遷移しない。
async function uploadFilesInChunks(files, uploadUrl) {
  const totalChunksAll = files.reduce(
    (sum, f) => sum + Math.ceil(f.size / CHUNK_UPLOAD_CHUNK_SIZE), 0,
  );
  let sentChunks = 0;
  // エラー発生時、それより前に完了したファイルは既にサーバー側のセッションへ格納済み
  // （このあと続けて送る通常アップロードのPOSTでバッチに合流する）のため、その旨を
  // エラーメッセージに含めてユーザーに伝える（同じファイルを選び直して再送信すると
  // 保管画面２で重複登録につながるため）。
  const completedFileNames = [];

  const overlay = document.getElementById('overlay-progress');
  const msgEl = document.getElementById('progress-msg');
  const fillEl = document.getElementById('progress-fill');
  const percentEl = document.getElementById('progress-percent');
  if (msgEl) msgEl.textContent = 'アップロード中...';
  if (overlay) overlay.style.display = 'flex';

  try {
    for (const file of files) {
      const totalChunks = Math.ceil(file.size / CHUNK_UPLOAD_CHUNK_SIZE);
      if (totalChunks === 0) {
        // 空ファイル（file.size === 0）はチャンクが1つも生成されずサイレントに無視されてしまう
        // ため、他の一括アップロード経路（documents/contracts.UploadStep1View.post）と同様に
        // エラーとして扱う。
        throw new Error(`${file.name}: ファイルが空です。`);
      }
      const uploadId = generateUploadId();
      for (let i = 0; i < totalChunks; i++) {
        const chunk = file.slice(i * CHUNK_UPLOAD_CHUNK_SIZE, (i + 1) * CHUNK_UPLOAD_CHUNK_SIZE);
        const formData = new FormData();
        formData.append('upload_id', uploadId);
        formData.append('file_name', file.name);
        formData.append('chunk_index', i);
        formData.append('total_chunks', totalChunks);
        formData.append('file', chunk);

        const res = await fetch(uploadUrl, {
          method: 'POST',
          body: formData,
          headers: { 'X-CSRFToken': getCsrfToken() },
          credentials: 'include',
        });
        const data = await res.json();
        if (data.status === 'error') {
          const note = completedFileNames.length > 0
            ? `（${completedFileNames.join('、')} は登録済みです。これらは選び直さずに再実行してください）`
            : '';
          throw new Error(`${file.name}: ${data.message}${note ? ' ' + note : ''}`);
        }

        sentChunks++;
        // 実際の送信済みチャンク数に基づく進捗（common.jsのshowProgressは疑似アニメーションで
        // 実進捗と連動しないため、ここではoverlay-progressのDOM要素を直接更新する）。
        const percent = Math.floor((sentChunks / totalChunksAll) * 100);
        if (fillEl) fillEl.style.width = percent + '%';
        if (percentEl) percentEl.textContent = percent + '%';
      }
      completedFileNames.push(file.name);
    }
  } finally {
    if (overlay) overlay.style.display = 'none';
  }
}
