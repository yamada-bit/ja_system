# 操作履歴ログ（AuditLog）は専用の業務画面（screen-audit-log、/audit/）で閲覧・CSV 出力する。
# ログは追記専用で編集・削除する運用が無く、保存期間超過分は日次バッチ
# purge_expired_audit_logs が物理削除するため、閲覧専用も含めて admin へは登録しない
# （規約準拠監査 R24、2026-09-10）。
