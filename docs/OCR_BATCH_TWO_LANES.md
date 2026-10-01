# 本文抽出バッチの2系統化（通常 5分間隔／大容量 夜間）— bat・タスク登録の変更手順

2026-10-01。`extract_pending_pdf_text` コマンドにサイズ指定オプションを追加した
（リポジトリ内、実装済み）。`ja_system/bat/` 配下はgit管理外のため、以下の変更は手動で反映する。

## コマンドのオプション

| オプション | 意味 |
|---|---|
| `--max-bytes N` | N バイト**以下**のファイルだけを対象にする |
| `--larger-than-bytes N` | N バイトを**超える**ファイルだけを対象にする |
| `--time-limit SEC` | 1回の実行に使える秒数（未指定は `OCR_BATCH_TIME_LIMIT_SECONDS`＝既定1500秒） |

同じ N を両方に指定すると担当が重複も漏れもなく分かれる。N は同期抽出の閾値
`SYNC_TEXT_EXTRACTION_MAX_BYTES`（既定20MB＝20971520）に揃える。オプション未指定なら従来どおり全件対象。

## 1. 通常タスク（5分間隔）— `extract_pending_pdf_text.bat` の呼び出し行を変更

```bat
"%VENV_PYTHON%" manage.py extract_pending_pdf_text --max-bytes 20971520 --time-limit 600 >> "%LOG_FILE%" 2>&1
```

実行時間を10分で区切り、大容量に引きずられて5分間隔の起動が長時間無視されるのを防ぐ。

## 2. 大容量タスク（夜間）— `extract_pending_pdf_text_large.bat` を新規作成

`extract_pending_pdf_text.bat` を複製し、次の3点だけ変える。

- `LOG_FILE` を `...\extract_pending_pdf_text_large.log` にし、ローテーション内の
  `extract_pending_pdf_text.log.%%i` / `.log.1` の名前も `extract_pending_pdf_text_large.log...` に揃える
- 呼び出し行：

```bat
"%VENV_PYTHON%" manage.py extract_pending_pdf_text --larger-than-bytes 20971520 --time-limit 19800 >> "%LOG_FILE%" 2>&1
```

（19800秒＝5.5時間。下記タスクの実行時間制限6時間より短くする。）

## 3. `register_scheduled_tasks.ps1` の変更

パラメータ部に追加：

```powershell
$Schedule['ExtractLargePdfText'] = '22:00'      # 夜間。backup(03:00)と重ならない時間帯
$ExtractLargeTimeLimit = New-TimeSpan -Hours 6
```

`$required` に `'extract_pending_pdf_text_large.bat'` を追加し、`$extractSettings` の下に：

```powershell
$extractLargeSettings = New-ScheduledTaskSettingsSet @commonSet -ExecutionTimeLimit $ExtractLargeTimeLimit
```

5分間隔タスクの登録の後に追加：

```powershell
Register-JaTask -Name 'JaDocSys_ExtractPendingPdfTextLarge' `
    -Action (New-ScheduledTaskAction -Execute (Join-Path $BatDir 'extract_pending_pdf_text_large.bat')) `
    -Trigger (New-ScheduledTaskTrigger -Daily -At $Schedule['ExtractLargePdfText']) `
    -Settings $extractLargeSettings `
    -Description 'JAふくおか八女 文書管理システム 全文検索用PDF本文抽出（大容量・夜間）'
Write-Host "  → 毎日 $($Schedule['ExtractLargePdfText'])（大容量）"
```

## 運用上の注意

- 通常タスクと大容量タスクは担当サイズが重ならないため、同時に走ってもよい（同じ文書を二重にOCRしない）。
- 夜間の上限（5.5時間）内にも終わらない文書は、何度実行しても完了しない。実行ログに
  「OCRが1回の実行時間の上限…内に終わりません」というエラーが出るので、その場合はPDFを分割する
  （ページ単位の進捗保存による再開は未実装。そのサイズの文書が実際に出てから検討する）。
- 大容量タスクの初回実行は、`Start-ScheduledTask JaDocSys_ExtractPendingPdfTextLarge` で手動実行し、
  `storage\logs\extract_pending_pdf_text_large.log` を確認する。
