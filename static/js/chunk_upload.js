// チャンク分割アップロード（documents/contracts保管画面１から使用する。
// core.upload_views.BaseChunkUploadAPIViewが受け口）。旧実装（static/js/chunk_upload.js）の
// 移植版。ただし本アプリのsave_pending_files/get_pending_filesは呼ばれるたびに既存のセッション
// 内容へ追記する設計のため、旧実装側にあった「結合済みファイルを一旦別の保留プールへ貯めて
// 通常アップロードPOST側で合流させる」という中間層は不要（core/upload_services.py参照）。
//
// 大容量PDFはDjangoの1リクエストボディ上限（MAX_UPLOAD_SIZE_BYTES/DATA_UPLOAD_MAX_MEMORY_SIZE）に
// 引っかかるため、ファイルを小さなチャンクに分割し、順次POSTしてサーバー側で結合する。
// storage1.html側のsubmitハンドラが、選択されたファイルをmax_upload_size_bytes基準で
// サイズ判定し、超えるファイルだけこの関数に渡す（閾値以下のファイルは従来通り
// documents/contracts.UploadStep1View.postへの一括POSTのまま）。

// チャンクサイズはsettings.CHUNK_UPLOAD_CHUNK_SIZE_BYTES（storage1.htmlのテンプレート
// コンテキスト経由）をuploadFilesInChunks()の第3引数で受け取る。以前はここに
// `5 * 1024 * 1024`をハードコードしていたが、テスト用に1MBへ書き換えたまま戻し忘れる事故が
// あったためsettingsへ集約した（HTML_REIMPL_CHECKLIST_ARCHIVE.md「チャンク分割アップロードの
// チャンクサイズ食い違いを修正」参照）。
//
// 推奨サイズ: 既定の5MBのままで問題ない。大容量ファイル主体で往復回数を減らしたい場合は
//   10MB程度まで可（500MBで100→50往復）。5MB未満にはしない（往復数・リクエスト処理
//   オーバーヘッドが増えるだけで、リトライ機構が無いため障害耐性はほぼ改善しない）。
//   上限は必ずMAX_UPLOAD_SIZE_BYTES（1リクエストボディ上限）より十分小さく、かつ本番
//   リバースプロキシのボディサイズ上限がこの値＋αを許可していること
//   （詳細はconfig/settings/base.pyのCHUNK_UPLOAD_CHUNK_SIZE_BYTES参照）。
//
// 引数未指定・不正値（0以下・NaN）の場合のフォールバック。
const CHUNK_UPLOAD_CHUNK_SIZE_FALLBACK = 5 * 1024 * 1024; // 5MB

// crypto.randomUUID()はSecure Context（HTTPS or localhost）でのみ利用可能。本番運用がTLS終端無し
// （HTTP）のままの場合、window.crypto.randomUUIDが存在せずTypeErrorになる可能性があるため
// （旧実装の同名関数と同じ理由）、使えない場合はMath.randomベースの簡易UUID風文字列に
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

// 1チャンクのPOSTに付けるタイムアウトとリトライ。fetch()は既定でタイムアウトせず、回線が
// 途中で止まると進捗バーが止まったまま待ち続ける。500MBのPDFは50〜100回のリクエストになるため、
// 一時的な通信断・IISの502/503/504で1回失敗しただけで最初からやり直しにならないよう、
// 途中のチャンクは間隔を空けて再送する（サーバー側save_upload_chunkは同じ番号のチャンクを
// 上書きするだけなので、再送は安全）。
const CHUNK_TIMEOUT_MS = 120 * 1000; // 途中のチャンク（5〜10MB）1回あたり。約0.5Mbps以上を想定。
const CHUNK_RETRY_DELAYS_MS = [1000, 3000, 8000]; // 再送の待ち時間（＝最大3回再送）

// 最終チャンクは再送しない。サーバー側で結合まで終わった後に応答だけが失われた場合、再送すると
// チャンク断片が既に削除されており「チャンクが見つかりません」の誤エラーになるうえ、結合済みの
// ファイルが保留一覧に残るため、自動再送の効果よりも混乱の方が大きい。結合（最大500MBの連結）に
// 時間がかかるため、タイムアウトはweb.configのrequestTimeout（10分）に合わせて長くとる。
const LAST_CHUNK_TIMEOUT_MS = 10 * 60 * 1000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 通信自体の失敗（ネットワーク断・タイムアウト・5xx・JSONでない応答）は retriable=true の
// エラーにして呼び出し側で再送する。サーバーがJSONで返したエラー（status==='error'）や
// 4xxは再送しても結果が変わらないため再送しない。
class ChunkRequestError extends Error {
  constructor(message, retriable) {
    super(message);
    this.retriable = retriable;
  }
}

async function postChunkOnce(uploadUrl, formData, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(uploadUrl, {
      method: 'POST',
      body: formData,
      headers: { 'X-CSRFToken': getCsrfToken() },
      credentials: 'include',
      signal: controller.signal,
    });
  } catch (e) {
    const reason = e && e.name === 'AbortError' ? '応答がありませんでした（タイムアウト）' : '通信に失敗しました';
    throw new ChunkRequestError(reason, true);
  } finally {
    clearTimeout(timer);
  }

  const contentType = res.headers.get('Content-Type') || '';
  if (!contentType.includes('application/json')) {
    // IIS/LBのエラーページ（502等）はHTMLで返る。5xxは一時的な障害の可能性が高いので再送する。
    // 5xx以外でJSONでない場合は、セッション切れでログイン画面へリダイレクトされた等で、
    // 再送しても直らない。
    if (res.status >= 500) {
      throw new ChunkRequestError(`サーバーが一時的に応答しませんでした（${res.status}）`, true);
    }
    throw new ChunkRequestError(
      'セッションが切れた可能性があります。ログインし直してからやり直してください。', false,
    );
  }
  return res.json();
}

async function postChunk(uploadUrl, buildFormData, isLastChunk, onRetry) {
  const timeoutMs = isLastChunk ? LAST_CHUNK_TIMEOUT_MS : CHUNK_TIMEOUT_MS;
  const delays = isLastChunk ? [] : CHUNK_RETRY_DELAYS_MS;
  for (let attempt = 0; ; attempt++) {
    try {
      // FormDataは送信ごとに作り直す（再利用すると中のBlobの読み取り状態に依存するため）。
      return await postChunkOnce(uploadUrl, buildFormData(), timeoutMs);
    } catch (e) {
      if (!(e instanceof ChunkRequestError) || !e.retriable || attempt >= delays.length) {
        if (e instanceof ChunkRequestError && e.retriable && isLastChunk) {
          throw new Error(
            `${e.message}。サーバー側で処理が完了している可能性があります。保管画面１を開き直して、最初からアップロードしてください。`,
          );
        }
        throw e;
      }
      onRetry(attempt + 1, delays.length);
      await sleep(delays[attempt]);
    }
  }
}

// files: 選択されたFileの配列。1ファイルずつ・1ファイル内はチャンク順に直列でPOSTする
// （並列化するとサーバー側のセッション保留ファイル一覧への追記が競合し得るため）。
// 結合が完了したファイルはサーバー側セッションの保留ファイル一覧に貯まるだけで、本チャンクの
// バッチへの合流・画面遷移は呼び出し元（storage1.htmlのsubmitハンドラ）が続けて行う通常
// アップロードのPOST（documents/contracts.UploadStep1View.post）が担当するため、この関数自体は
// 画面遷移しない。
async function uploadFilesInChunks(files, uploadUrl, chunkSize) {
  const chunkBytes = Number(chunkSize) > 0 ? Number(chunkSize) : CHUNK_UPLOAD_CHUNK_SIZE_FALLBACK;
  const totalChunksAll = files.reduce(
    (sum, f) => sum + Math.ceil(f.size / chunkBytes), 0,
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
      const totalChunks = Math.ceil(file.size / chunkBytes);
      if (totalChunks === 0) {
        // 空ファイル（file.size === 0）はチャンクが1つも生成されずサイレントに無視されてしまう
        // ため、他の一括アップロード経路（documents/contracts.UploadStep1View.post）と同様に
        // エラーとして扱う。
        throw new Error(`${file.name}: ファイルが空です。`);
      }
      const uploadId = generateUploadId();
      for (let i = 0; i < totalChunks; i++) {
        const chunk = file.slice(i * chunkBytes, (i + 1) * chunkBytes);
        const buildFormData = () => {
          const formData = new FormData();
          formData.append('upload_id', uploadId);
          formData.append('file_name', file.name);
          formData.append('chunk_index', i);
          formData.append('total_chunks', totalChunks);
          formData.append('file', chunk);
          return formData;
        };

        let data;
        try {
          data = await postChunk(uploadUrl, buildFormData, i === totalChunks - 1, (n, max) => {
            if (msgEl) msgEl.textContent = `通信を再試行しています（${n}/${max}）...`;
          });
        } catch (e) {
          // 通信エラーも、サーバーのエラー応答と同じく「ファイル名＋既に登録済みのファイル」付きで
          // 利用者に伝える（呼び出し元はthrowされたErrorのmessageをそのまま表示する）。
          const note = completedFileNames.length > 0
            ? `（${completedFileNames.join('、')} は登録済みです。これらは選び直さずに再実行してください）`
            : '';
          throw new Error(`${file.name}: ${e.message}${note ? ' ' + note : ''}`);
        }
        if (msgEl) msgEl.textContent = 'アップロード中...';
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
