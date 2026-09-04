import logging

from core.text_normalization import filter_by_full_name
from organizations.services import department_composite_order_by
from permissions.models import PermissionProfile, PermissionRole

logger = logging.getLogger(__name__)


def get_profile(employee):
    """employeeのPermissionProfileを返す。まだ権限管理（第二陣screen-authority-edit）で作成されて
    いない職員は`None`。呼び出し側は`None`のとき最も制限の強い（一般職員相当の）扱いにする。
    """
    try:
        return employee.permission_profile
    except PermissionProfile.DoesNotExist:
        return None


def get_role(employee):
    profile = get_profile(employee)
    return profile.role if profile else PermissionRole.STAFF


def is_admin(employee):
    """get_role(employee) == PermissionRole.ADMINの短縮形。masters/views.py・
    permissions/views.py双方でこの比較がベタ書きで繰り返し重複していたため集約する
    （コード監査で発見、2026-08-24修正。masters/views.py._is_adminはこの関数の別名になる）。
    """
    return get_role(employee) == PermissionRole.ADMIN


def admin_count(*, exclude_profile_pk=None):
    """システム権限が"管理者"かつ在職中（is_retired=False）の職員の人数。

    xlsx 権限管理!B222-223 / 職員マスタ!B127-128「システム全体で管理者が0人にならないように
    チェックを掛ける」の判定用。退職者は職員マスタ編集・CSV取込のどちらの経路でも
    accounts.services.reset_permission_profile_if_needed で権限がSTAFFへリセットされるのが
    通常だが、Django admin での直接編集や、退職者を後から権限管理編集で管理者へ設定する経路
    （AuthorityEditView は is_retired を見ない）でも role=ADMIN が残りうる。ログイン不能な
    退職者を「有効な管理者」に数えると 0人ガードをすり抜けるため、明示的に is_retired=False で
    絞る（会話ログ 2026-09-04 の指摘③）。
    """
    qs = PermissionProfile.objects.filter(
        role=PermissionRole.ADMIN, employee__is_retired=False
    )
    if exclude_profile_pk is not None:
        qs = qs.exclude(pk=exclude_profile_pk)
    return qs.count()


def would_orphan_admins(profile, new_role):
    """`profile`のシステム権限を`new_role`へ変更すると、システム全体の"管理者"が0人になるか。

    現在ADMINでない、または変更後もADMINのままなら影響しない。現在ADMINでADMIN以外へ
    下げる更新のときだけ、他に在職中のADMINが1人も居なければTrue。権限管理編集の更新（X-1）、
    職員CSV取込の所属長フラグ降格（X-2）、および本支所〜役職変更・退職に伴う権限リセット
    （accounts.services.reset_permission_profile_if_needed。手動編集・CSV取込の両経路。
    Rev1.5 はこのリセット経路自体の0人ガードを明記していないが、明示的なロール変更だけ塞いで
    リセット経由を野放しにすると「本支所を変えたら管理者が消えた」というサイレントな事故が
    残るため揃える。会話ログ 2026-09-04 の指摘①）で共有する。
    """
    if profile.role != PermissionRole.ADMIN or new_role == PermissionRole.ADMIN:
        return False
    return admin_count(exclude_profile_pk=profile.pk) == 0


def can_select_department(employee, *, kind="document"):
    """保管・検索画面で自部署以外の部署を選択できるか（部署名「選択」ボタンの表示可否）。

    - kind="document"（既定、保管画面の部署選択も含む）: 管理者のみ表示
      （xlsx 保管!B79-82、検索・閲覧・変更!B50-52(Rev1.1)で文書側は管理者のみに単純化された）。
    - kind="contract": 管理者、または権限管理の「契約書-部門間閲覧設定」
      （PermissionProfile.contract_visible_departments）が1件以上設定されている職員
      （xlsx 検索・閲覧・変更!B421-423(Rev1.1)「権限が"管理者"。または契約書-部門間閲覧設定に
      設定がある場合に表示。」）。この場合も選べる部署自体はcontract_searchable_department_ids()で
      自部署＋閲覧部署範囲＋この設定の部署に限定する（無制限にはしない）。
    """
    if get_role(employee) == PermissionRole.ADMIN:
        return True
    if kind == "contract":
        profile = get_profile(employee)
        return bool(profile and profile.contract_visible_departments.exists())
    return False


def contract_searchable_department_ids(employee):
    """契約書検索・保管画面で選択・閲覧してよい部署IDの一覧を返す。管理者は`None`
    （無制限を意味する）。非管理者は自部署＋閲覧部署範囲テーブル（部署統合・分割）＋
    権限管理の契約書-部門間閲覧設定で追加された部署に限定する。

    対になるdocuments.services.document_searchable_department_idsはdocuments側に置いているが、
    こちらをpermissions側に置いているのは意図的（配置理由の詳細はdocument_searchable_
    department_idsのdocstring参照）：本関数はPermissionProfile.contract_visible_departments
    （permissionsアプリ固有データ）に依存するため。
    """
    from organizations.services import visible_department_ids

    if get_role(employee) == PermissionRole.ADMIN:
        return None
    ids = set(visible_department_ids(employee))
    profile = get_profile(employee)
    if profile:
        ids.update(profile.contract_visible_departments.values_list("pk", flat=True))
    return ids


def can_download(employee, *, kind):
    """検索・閲覧画面のダウンロードボタン表示可否（要再確認No.20〜22、権限管理!B177-180,B193-194
    「文書管理-文書-ダウンロード」「契約書-文書-ダウンロード」フラグが対応）。
    kindは"document"または"contract"。

    管理者はフラグの値に関わらず常に可（`can_select_department`/`can_edit_retention`と同じ理由。
    xlsxの「※管理者は、所属長及び職員に対して設定する」という記述は、管理者自身がこの階層の
    最上位で他者に対して権限を付与する側であることを示しており、管理者自身に設定が必要という
    趣旨ではないと判断した）。
    """
    if get_role(employee) == PermissionRole.ADMIN:
        return True
    profile = get_profile(employee)
    if profile is None:
        return False
    if kind == "document":
        return profile.doc_download
    if kind == "contract":
        return profile.contract_download
    raise ValueError(f"unknown kind: {kind}")


def can_edit_contract(employee):
    """契約書の保存・編集を行ってよいか（xlsx 権限管理!B193-198、Rev1.2で新規追加）。
    文書側に対応するフラグは無く、文書の保存・編集は従来通り無条件で可能（documents/views.py・
    contracts/views.pyのBulkEditStartView等docstring参照）。管理者は常に可能。

    OFFの場合の制御は呼び出し側で下記2箇所に分かれる：
    - 保存不可：メイン画面の保管枠内「契約書」ボタンを非表示（templates/core/menu.html）。
    - 編集不可：契約書詳細ポップアップの「編集」「削除」ボタンを非表示（contracts/api.py）。
    """
    if get_role(employee) == PermissionRole.ADMIN:
        return True
    profile = get_profile(employee)
    return bool(profile and profile.contract_edit)


def can_edit_retention(employee):
    """保存済み文書の保存期間（保存満了日の元になる`retention_period`）を編集してよいか
    （xlsx 権限管理!B172-175(Rev1.1)「文書管理-文書-保存満了日変更」。OFFの場合、対象者は
    保存した文書の「保存期間」は編集出来ないように制御する）。管理者は常に編集可能。
    """
    if get_role(employee) == PermissionRole.ADMIN:
        return True
    profile = get_profile(employee)
    return bool(profile and profile.doc_retention_edit)


# screen-authority-listのソート対象列（xlsx 権限管理!B53-59）。一覧表示とCSV出力
# （xlsx B39検索条件を踏まえ、一覧と同じ絞込み・並び順を再利用）で共有する。「部署」列は
# `employee.department`（`Department.__str__` = 本支所名｜部課名）を表示する単一列のため、
# 特殊扱い（下記filter_authority_queryset参照）で本支所コード→部課コードの複合ソートにする
# （section_codeのみでは本支所をまたいで無関係にソートされ、documents/contracts検索の
# 「保存情報」列と同じ「表示と無関係な列でソートされる」不具合になるため、2026-08-17修正）。
AUTHORITY_SORT_FIELDS = {
    "employee_no": "employee_no",
    "department": "department__section_code",  # 特殊扱い（下記filter_authority_queryset参照）、単体では未使用。
    "name": "name",
    "position": "position",
    "role": "permission_profile__role",
}


def can_manage_target(viewer, target):
    """screen-authority-detail/edit: viewerがtargetの権限を編集してよいか。
    xlsx 権限管理!B156(要再確認No.2)「所属長は自分の権限の変更が不可」、B113「所属長は自分の部署の
    "一般"職員のみ権限変更可」に対応。管理者は制限なし。一般ロールは編集不可
    （xlsxに一般ロールの編集可否の明記は無いが、権限管理という機微な画面の性質上、
    最も制限の強い「編集不可」に倒す）。
    """
    viewer_role = get_role(viewer)
    if viewer_role == PermissionRole.ADMIN:
        return True
    if viewer_role != PermissionRole.MANAGER:
        return False
    if target.pk == viewer.pk:
        return False
    if target.department_id != viewer.department_id:
        return False
    return get_role(target) == PermissionRole.STAFF


def visible_employees(viewer):
    """xlsx 権限管理!B68-70: 管理者は全部署全職員、所属長は自部署の職員のみ閲覧可。
    「一般」の閲覧範囲はxlsxに記載が無いため、最も制限の強い所属長と同じ「自部署のみ」に
    倒す（未確定の権限を広く与えない安全側の判断）。なお現行仕様では一般ロールは権限管理
    画面自体にアクセスできず（SETTINGS_MENU_VISIBLE_ROLES["authority_management"]参照、
    SettingsMenuAccessMixinでサーバー側403）、この分岐は現状到達しない。将来一般ロールにも
    本画面へのアクセスを許可する仕様変更が入る場合に、その時点で閲覧範囲を改めて確認する
    （ユーザー判断、2026-08-21。現時点では業務判断待ちの未解決事項として扱わない）。
    """
    from accounts.models import Employee

    # authority_list.html・_flags_row()（CSV出力）がいずれもemployee.permission_profileの3つの
    # ManyToManyField（doc_visible_groups/contract_visible_departments/contract_visible_groups）
    # を行ごとに参照するため、prefetch_relatedしておかないと一覧・CSV出力の行数に比例した
    # N+1クエリが発生する（コード監査で発見、2026-08-25修正）。
    qs = Employee.objects.select_related("department", "permission_profile").prefetch_related(
        "permission_profile__doc_visible_groups",
        "permission_profile__contract_visible_departments",
        "permission_profile__contract_visible_groups",
    )
    if get_role(viewer) == PermissionRole.ADMIN:
        return qs
    return qs.filter(department_id=viewer.department_id)


def filter_authority_queryset(viewer, form, *, sort_key=None, sort_dir="asc"):
    """screen-authority-listの検索条件・ソート順でEmployeeを絞り込む（一覧表示とCSV出力で共有）。"""
    qs = visible_employees(viewer)
    if form.is_valid():
        if form.cleaned_data.get("department"):
            qs = qs.filter(department=form.cleaned_data["department"])
        if form.cleaned_data.get("name"):
            qs = filter_by_full_name(qs, form.cleaned_data["name"])
    field = AUTHORITY_SORT_FIELDS.get(sort_key)
    if sort_key == "department":
        # 表示されている「本支所名｜部課名」の並びと一致させるため本支所コード→部課コードの
        # 複合ソートにする（section_codeのみでは本支所をまたいで無関係にソートされていた）。
        # masters.views.GroupListView/CategoryListViewの"department"特殊扱いと同一ロジックのため
        # organizations.services側へ集約した（コード監査で発見、2026-08-25修正）。
        qs = department_composite_order_by(qs, sort_dir, "employee_no")
    elif field:
        prefix = "-" if sort_dir == "desc" else ""
        qs = qs.order_by(f"{prefix}{field}", "employee_no")
    else:
        # xlsx B48-50: 初期ソート順は部課コード（本支所コード+部課コードの5桁にて）→役職コード
        # →権限コード。section_codeだけでは本支所をまたいで無関係にソートされるため、
        # sort_key="department"のソートと同様branch_code→section_codeの複合キーにする。
        qs = qs.order_by(
            "department__branch_code", "department__section_code",
            "position", "permission_profile__role", "employee_no",
        )
    return qs


# screen-settings（設定メニュー）のボタン出し分け。xlsx 設定メニュー!B46以降はセル値ではなく
# 埋め込み画像の表として入っており（openpyxlでセル値のみを見る過去の突き合わせでは見落とされて
# いた）、システム権限（管理者(DX)/所属長/ユーザー）ごとに○/―が定義されている。
# 「権限管理」ボタンは表側では「所属長への権限付与」(管理者のみ○)と「職員への権限付与」
# (管理者/所属長○)の2行に分かれているが、PermissionProfileが「所属長への権限付与」
# 「職員への権限付与」という個別フラグを廃止しシステム権限プルダウン1本に統一した
# （PermissionProfile docstring参照）ため、緩い方＝「職員への権限付与」の行（管理者/所属長）を
# ボタン自体の表示可否として採用する（ユーザー確認・承認済み、2026-08-20）。
SETTINGS_MENU_VISIBLE_ROLES = {
    "staff_master": {PermissionRole.ADMIN},
    "dept_management": {PermissionRole.ADMIN},
    "authority_management": {PermissionRole.ADMIN, PermissionRole.MANAGER},
    "class_management": {PermissionRole.ADMIN, PermissionRole.MANAGER},
    "category_management": {PermissionRole.ADMIN, PermissionRole.MANAGER, PermissionRole.STAFF},
    "eapproval_management": {PermissionRole.ADMIN},
    "notice_management": {PermissionRole.ADMIN},
    "retention_setting": {PermissionRole.ADMIN},
    "item_management": {PermissionRole.ADMIN},
    "audit_log": {PermissionRole.ADMIN},
    "other_settings": {PermissionRole.ADMIN, PermissionRole.MANAGER, PermissionRole.STAFF},
}


def visible_settings_menu_items(employee):
    """設定メニュー画面の各ボタンについて、employeeのシステム権限で表示してよいかを
    ボタンキー→bool の辞書で返す（SETTINGS_MENU_VISIBLE_ROLES参照）。
    """
    role = get_role(employee)
    return {key: role in roles for key, roles in SETTINGS_MENU_VISIBLE_ROLES.items()}


def can_access_settings_menu_item(employee, key):
    """設定メニューの各ボタン背後にある実画面へのアクセス可否。
    permissions.mixins.SettingsMenuAccessMixinのdispatch()から呼ばれる、URL直打ち対策の本体
    （visible_settings_menu_itemsと同じSETTINGS_MENU_VISIBLE_ROLESを参照することで、
    ボタン非表示とアクセス拒否のロール判定がずれないようにする）。
    """
    return get_role(employee) in SETTINGS_MENU_VISIBLE_ROLES[key]


def department_ids_for_group_scope(employee, *, kind):
    """文書・契約書の保存/検索画面で選択できる分類(masters.Group)・カテゴリー(masters.Category)を
    部署単位で絞り込むための部署ID集合を返す。`None`は無制限（管理者）。
    （xlsx 検索・閲覧・変更!P96,P152,P470,P507「分類/カテゴリー選択は…自部署の内容を表示」
    「※部署を複数選択できる権限の場合は、選択した部署分の分類/カテゴリーを選択出来るように
    すること」、保管!P139,P174,P430,P459も同旨、Rev1.2で追加）。

    kind="document"はcan_select_department(kind="document")と同じく管理者のみ無制限、
    非管理者は常に自部署のみ（文書側は部署選択自体が管理者のみに単純化されているため）。
    kind="contract"はcontract_searchable_department_ids()と同じ範囲（自部署＋閲覧部署範囲＋
    契約書-部門間閲覧設定）を再利用する——これにより「部署を複数選択できる権限の場合」の
    分類/カテゴリー選択肢が、選択可能な部署全体の和集合として自然に満たされる。ただし
    検索/保管フォームで実際に選択中の部署の値には動的に追従しない（選択可能な部署全体を
    常時候補にする簡略化。動的な追従にはpopup-select側の新規JS連動が必要になるため、
    今回のRev1.2反映では対象外とした）。
    """
    if kind == "contract":
        return contract_searchable_department_ids(employee)
    if kind != "document":
        # can_download()と同じ理由：想定外のkindを"document"扱いで握りつぶさず、
        # 呼び出し側の誤り（typo等）として早期に気付けるようにする
        # （コード監査で発見：以前はkindを検証しておらず、"document"分岐へ暗黙に
        # フォールスルーしていた、2026-08-24修正）。
        raise ValueError(f"unknown kind: {kind}")
    if get_role(employee) == PermissionRole.ADMIN:
        return None
    return {employee.department_id}


def visible_groups(employee, *, kind):
    """保存/検索時の分類選択ポップアップに表示してよい分類(masters.Group)の一覧
    （要再確認No.8等、権限管理!B203-205「所属長による権限設定で分類選択の表示/非表示を行う」）。
    PermissionProfileが無い、またはdoc_visible_groups/contract_visible_groupsが未設定（空）の場合は
    制限なし（全件）とみなす——「所属長への権限付与」自体が保留気味の項目であり、未設定を
    「何も見せない」に倒すと第一陣の検索・保管画面が事実上使えなくなってしまうため。
    """
    profile = get_profile(employee)
    if profile is None:
        return None  # None = 呼び出し側でフィルタなし(全件)として扱う
    if kind == "document":
        qs = profile.doc_visible_groups
    elif kind == "contract":
        qs = profile.contract_visible_groups
    else:
        # can_download()/department_ids_for_group_scope()と同じ理由：想定外のkindを
        # "contract"扱いで握りつぶさず、呼び出し側の誤り（typo等）として早期に気付けるように
        # する（コード監査で発見：この関数だけkind検証が無く、"document"以外を全て契約書向け
        # クエリへ暗黙にフォールスルーしていた、2026-08-25修正）。
        raise ValueError(f"unknown kind: {kind}")
    if not qs.exists():
        return None
    return qs
