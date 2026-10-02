# waitress 標準出力ログ（stdout_*.log）の定期削除手順

## 背景

`web.config` の `httpPlatform` に `stdoutLogEnabled="true"` /
`stdoutLogFile="C:\ja_system\storage\logs\stdout"` を指定しているため、IIS（HttpPlatformHandler）は
waitress プロセスを起動するたびに `C:\ja_system\storage\logs\stdout_<日時>_<PID>.log` を
**新規作成**する。HttpPlatformHandler にはローテーションも保持期間による自動削除も無く、
放置すると次の契機でファイルが増え続ける（稼働中のファイルは肥大化もする）。

- IIS再起動・アプリケーションプールのリサイクル・`web.config` 更新（デプロイ）
- アイドルタイムアウト後の再起動
- クラッシュ・起動失敗（`startupRetryCount="3"` により最大3回分）

DBの操作履歴ログ（`purge_expired_audit_logs`）とは別物で、そちらの保存期間設定は影響しない。
既存の定期バッチ（`ja_system/bat/`）と同じく、Windows タスクスケジューラで日次実行する。

## 1. 削除スクリプトを配置する

`C:\ja_system\bat\purge_stdout_logs.ps1` として以下を保存する（`ja_system/bat/` の他の
バッチと同じ場所。`ja_pj` の git 管理外）。

```powershell
# waitress標準出力ログ(stdout_*.log)のうち、最終更新から保持日数を超えたものを削除する。
# 稼働中プロセスが書き込み中のファイルはWindowsが排他ロックしているため削除に失敗する。
# それは想定内の挙動なので握りつぶし（-ErrorAction SilentlyContinue）、次回実行に回す。
param(
    [string]$LogDir = "C:\ja_system\storage\logs",
    [int]$RetentionDays = 30
)

$cutoff = (Get-Date).AddDays(-$RetentionDays)
$targets = Get-ChildItem -Path $LogDir -Filter "stdout_*.log" -File -ErrorAction Stop |
    Where-Object { $_.LastWriteTime -lt $cutoff }

foreach ($f in $targets) {
    Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $f.FullName) {
        Write-Output "SKIP (使用中): $($f.Name)"
    } else {
        Write-Output "DELETED: $($f.Name)"
    }
}
Write-Output "完了: 対象$($targets.Count)件 (保持$RetentionDays日, $(Get-Date -Format s))"
```

保持日数は既定30日。変更する場合はタスクの引数で `-RetentionDays 60` のように渡す。
対象は `stdout_*.log` のみ（同フォルダに他のログがあっても触らない）。

## 2. 手動で動作確認する

管理者権限のPowerShellで、まず対象を確認してから実行する（`-WhatIf` は付けていないため、
実行前に下の一覧で消える予定のファイルを目視する）。

```powershell
Get-ChildItem C:\ja_system\storage\logs\stdout_*.log |
    Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) |
    Select-Object Name, Length, LastWriteTime
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\ja_system\bat\purge_stdout_logs.ps1
```

## 3. タスクスケジューラへ登録する

他の定期タスクと同様、`C:\ja_system\bat\register_scheduled_tasks.ps1` に組み込み済み
（タスク名 `JaDocSys_PurgeStdoutLogs`、毎日 04:40、SYSTEM 実行）。スクリプトを配置したうえで、
管理者権限の PowerShell で再実行するだけでよい（`-Force` 上書きのため何度でも安全）。

```powershell
cd C:\ja_system\bat
.\register_scheduled_tasks.ps1
```

即時実行・確認・解除:

```powershell
Start-ScheduledTask JaDocSys_PurgeStdoutLogs
Get-ScheduledTaskInfo JaDocSys_PurgeStdoutLogs
.\register_scheduled_tasks.ps1 -Remove   # JaDocSys_* を全て解除（開発PC試験後用）
```

保持日数を既定の30日から変える場合は、`purge_stdout_logs.ps1` の `param` 既定値を編集する。

## 4. 運用上の注意

- **起動失敗の調査用ログ**なので、保持日数は障害調査に足りる長さ（30日程度）を維持する。
- 出力先フォルダ `C:\ja_system\storage\logs` が無いと waitress の起動自体に失敗することがある。
  また IIS のアプリケーションプールIDに書き込み権限が必要。
- 1プロセスが長期間動き続けてログが肥大化する場合は、Django の `LOGGING` 側で
  ローテーション付きハンドラ（`RotatingFileHandler`）へ出力し、コンソール出力を絞ることを検討する。
  この手順のスクリプトは「ファイル単位の削除」のみで、稼働中ファイルの切り詰めはしない。
- `stdoutLogEnabled="false"` にすると起動失敗の原因調査ができなくなるため、通常は有効のまま
  この定期削除で運用する。
