# 職員マスタ（Employee）・Rank・Position は専用の業務画面（screen-staff-list/detail/regist/edit、
# /accounts/staff/〜）で管理する。管理サイトからの直接編集は職員番号の正規化・Argon2 ハッシュ・
# 権限プロファイル連動・監査ログを迂回させるため、閲覧専用も含めて admin へは登録しない
# （organizations/masters は履歴確認用に ReadOnlyModelAdmin で登録済みだが、accounts は
# 個人情報を含むため登録自体を見送る。規約準拠監査 R10、2026-09-10）。
