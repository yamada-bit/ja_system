import logging

from django.db.models import Q

from core.scoping_services import scoped_get_object_or_404 as _core_scoped_get_object_or_404

logger = logging.getLogger(__name__)


def department_scope_ids(employee):
    """分類管理・カテゴリー管理画面（一覧・登録・編集・削除）の部署スコープ。

    管理者は`None`（無制限＝全部署）、それ以外は自部署のみ（xlsx 分類管理!B73-75、
    カテゴリー管理!B78-80、Rev1.2で追加）。documents/contracts側の分類・カテゴリー選択
    （permissions.services.department_ids_for_group_scope）とは目的が異なる別関数
    （こちらは分類・カテゴリー"マスタ自体"の管理範囲、あちらは文書・契約書保存/検索時に
    "選択できる"分類・カテゴリーの範囲）ため、意図的に分けている。
    """
    from permissions.services import is_admin

    if is_admin(employee):
        return None
    return {employee.department_id}


def scope_queryset_by_department(qs, dept_ids):
    """masters.Group/masters.Categoryのクエリセットを部署IDで絞り込む共通ヘルパー。

    `dept_ids`が`None`の場合は無制限（管理者、フィルタしない）。それ以外の場合は
    `department_id`が`dept_ids`に含まれる行に加えて、`department_id`が未設定（NULL）の行も
    含める。department列自体がRev1.2で新規追加したnull許容フィールドのため、移行前に
    作成された既存データ（部署未設定）が非管理者から一切見えなくなる・編集できなくなる
    退行を避ける目的（Group/Category docstring参照）。将来、既存データの部署を全件
    バックフィルしてNULLを無くせば、この「NULLも含める」分岐は実質的に無害化する
    （該当行が無くなるだけで、フィルタロジック自体は変更不要）。
    """
    if dept_ids is None:
        return qs
    return qs.filter(Q(department_id__in=dept_ids) | Q(department_id__isnull=True))


def scoped_get_object_or_404(base_qs, employee, pk):
    """masters.Group/Categoryの編集・削除確認画面で、部署スコープ外のpkへのURL直叩きを404に
    しつつ、セキュリティ上意味のある事象としてlogger.warningに残す共通ヘルパー。

    以前はGroupEditView/GroupDeleteView/CategoryEditView/CategoryDeleteViewの`_get_object`と
    ほぼ同一のアルゴリズムを本アプリ独自に再実装していたが、documents/contracts側で同じ目的の
    core.scoping_services.scoped_get_object_or_404が既に集約されていた（2026-08-25にNULL許容の
    絞り込み方式をscope_queryset引数として一般化）ため、そちらに委譲する形に揃えた
    （ログもentity_name="分類/カテゴリー"の日本語表記に統一され、documents/contracts側と
    一貫するようになった。コード監査で発見、2026-08-25修正）。
    """
    entity_name = "分類" if base_qs.model.__name__ == "Group" else "カテゴリー"
    return _core_scoped_get_object_or_404(
        base_qs,
        employee,
        pk,
        dept_ids_resolver=department_scope_ids,
        entity_name=entity_name,
        scope_queryset=scope_queryset_by_department,
    )
