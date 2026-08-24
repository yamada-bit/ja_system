import logging

from django.db.models import Q

logger = logging.getLogger(__name__)


def department_scope_ids(employee):
    """分類管理・カテゴリー管理画面（一覧・登録・編集・削除）の部署スコープ。

    管理者は`None`（無制限＝全部署）、それ以外は自部署のみ（xlsx 分類管理!B73-75、
    カテゴリー管理!B78-80、Rev1.2で追加）。documents/contracts側の分類・カテゴリー選択
    （permissions.services.department_ids_for_group_scope）とは目的が異なる別関数
    （こちらは分類・カテゴリー"マスタ自体"の管理範囲、あちらは文書・契約書保存/検索時に
    "選択できる"分類・カテゴリーの範囲）ため、意図的に分けている。
    """
    from permissions.models import PermissionRole
    from permissions.services import get_role

    if get_role(employee) == PermissionRole.ADMIN:
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
