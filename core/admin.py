from django.contrib import admin


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """閲覧専用のDjango管理サイト登録。

    分類・カテゴリー・保存期間設定・部署・閲覧部署範囲・メイン画面項目設定は、いずれも
    アプリ側に専用のCRUD画面があり、そちらを通すことで論理削除・重複制御・監査ログ記録・
    部署スコープ判定が働く。管理サイトから直接編集できてしまうとこれらを迂回するため、
    管理サイトでは「本番データを画面を開かず一覧・確認できる」用途に限定し、追加・変更・
    削除は一切許可しない（`masters.SystemSetting`だけは編集経路が実質DB直接操作しか無いため
    例外的に変更可能＝`SystemSettingAdmin`）。

    review_pending.txt No.23（admin未登録による運用上の不便さ）への対応。
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        # 具体的なフィールド一覧を各Adminで持たなくて済むよう、モデルの全concreteフィールドを
        # 動的に読み取り専用にする。
        return [f.name for f in self.model._meta.fields]
