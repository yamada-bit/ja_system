import csv
import io
import logging
import unicodedata

from django.db import transaction

from accounts.models import Employee, Position, Rank
from accounts.services import LastAdminError, reset_permission_profile_if_needed
from audit import services as audit_services
from organizations.models import RETIRED_SECTION_CODE, Department
from permissions.models import PermissionProfile, PermissionRole
from permissions.services import would_orphan_admins

logger = logging.getLogger(__name__)

# xlsx 職員マスタ!B94-95(Rev1.1「フォーム変更」)に埋め込み画像として存在する取込用CSVレイアウト。
# 列順は固定（職員番号,氏名,支所コード,本支所名正式名称,部課コード,部課名,役職コード,役職名,
# 職階コード,職階名,所属長フラグ）。ヘッダー行が1行あることを前提にする。
CSV_HEADER = [
    "職員番号", "氏名", "支所コード", "本支所名正式名称", "部課コード", "部課名",
    "役職コード", "役職名", "職階コード", "職階名", "所属長フラグ",
]


class CsvImportError(Exception):
    """取込用CSV自体が読めない・列数が合わない等、行単位の処理に進めない場合のエラー。"""


class ImportSummary:
    """取込結果の集計（screen-staff-listへ表示するメッセージ用）。"""

    def __init__(self):
        self.created = 0
        self.updated = 0
        self.retired = 0
        self.unchanged = 0
        self.errors = []

    def __str__(self):
        return (
            f"新規登録{self.created}件、更新{self.updated}件、退職扱い{self.retired}件、"
            f"変更なし{self.unchanged}件"
            + (f"、エラー{len(self.errors)}件" if self.errors else "")
        )


def import_staff_csv(file_obj, *, actor):
    """職員マスタCSV取込（xlsx 職員マスタ!B93-142、Rev1.1で所属長フラグ列が追加された）。

    1行=1職員。部署（本支所/部課）は取込時に無ければ新規登録、名称に差分があれば更新する
    （B127-138）。職員は職員番号で既存レコードと突き合わせ、氏名のみの変更・部課/役職/職階の
    変更（異動・昇格降格扱いで権限リセット）・部課コード"99"（退職扱い）・新規登録
    （権限管理は初期値、パスワードは"ja"+職員番号下4桁）のいずれかとして扱う。取込用CSVに
    存在しない既存職員は処理不要（削除しない、B121-122）。所属長フラグ"1"の行は、対象職員の
    権限管理システム権限を「所属長」に更新する（B124-125、後述の権限管理と連動する数少ない
    CSV取込項目）。

    1行の処理失敗（必須列欠落・コード不正等）は他の行の処理を止めず、summary.errorsに集積する
    （インポート全体が1行のミスで巻き戻ると大量データの再取込コストが大きいため）。
    """
    summary = ImportSummary()
    try:
        text = file_obj.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvImportError("CSVファイルの文字コードを確認してください（UTF-8を想定しています）。") from exc

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise CsvImportError("CSVファイルが空です。")
    if [h.strip() for h in header] != CSV_HEADER:
        raise CsvImportError(f"CSVの列構成が想定と異なります。期待する列: {','.join(CSV_HEADER)}")

    for line_no, row in enumerate(reader, start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        try:
            _import_row(row, actor=actor, summary=summary)
        except ValueError as exc:
            # 列数不一致・必須列欠落・コード不正等、行データ起因の想定内エラー。メッセージ自体が
            # 日本語で利用者にわかる内容になっているためそのまま表示する。
            logger.warning("職員マスタCSV取込で行の処理に失敗しました: line=%s error=%s", line_no, exc)
            summary.errors.append(f"{line_no}行目: {exc}")
        except Exception:
            # コードのバグ等、想定外の例外。生の例外メッセージ（英語・非制御下の文言になりうる）を
            # そのまま利用者に見せず、詳細はlogger.exceptionで記録した上で汎用メッセージを返す
            # （CLAUDE.md「利用者にわかるエラー応答を返す」）。
            logger.exception("職員マスタCSV取込で行の処理に失敗しました（想定外エラー）: line=%s", line_no)
            summary.errors.append(f"{line_no}行目: 処理中に予期しないエラーが発生しました。")

    logger.info(
        "職員マスタCSV取込を実行しました: employee_no=%s 結果=%s", actor.employee_no, summary
    )
    audit_services.log(
        employee=actor,
        action="職員マスタ　CSV取込",
        event_message=f"職員マスタCSV取込,{summary}",
    )
    return summary


def _import_row(row, *, actor, summary):
    if len(row) != len(CSV_HEADER):
        raise ValueError(f"列数が{len(CSV_HEADER)}列ではありません（{len(row)}列）。")
    (
        employee_no, name, branch_code, branch_name, section_code, section_name,
        position_code, position_name, rank_code, rank_name, manager_flag,
    ) = (cell.strip() for cell in row)

    if not employee_no:
        raise ValueError("職員番号が空です。")
    # StaffRegistForm.clean_employee_no()と同じ正規化・検証（xlsx 職員マスタ!B173「半角数字の
    # みを許可。全角の場合は登録時に半角へ変換」）。CSV取込はcreate_user()/save()を直接呼ぶため
    # フォームのclean_employee_no()を経由せず、ここで明示的に揃える必要がある
    # （コード監査で発見：以前は.strip()のみで全角数字や数字以外がそのまま保存されていた、
    # 2026-08-25修正）。
    # [優先度: 低・見送り、規約準拠監査 2026-08-25] 上記NFKC正規化には、姉妹バグである
    # rank_code/position_codeのchoices未検証（下記、2026-08-24修正）に対応する
    # test_invalid_rank_code_is_rejected/test_invalid_position_code_is_rejectedと同様の
    # 回帰テストがImportStaffCsvServiceTestsに無い（StaffRegistFormTests.
    # test_fullwidth_employee_no_converted_to_halfwidthは手動登録フォーム側のみでCSV取込側は
    # 未カバー）。実装済みロジックへの追加テストであり緊急性は無いため見送るが、将来
    # _import_row()をリファクタリングした際にNFKC正規化だけ回帰が検知されないリスクは残る。
    employee_no = unicodedata.normalize("NFKC", employee_no)
    if not employee_no.isdigit():
        raise ValueError(f"職員番号が不正です（半角数字のみ許可）: {employee_no}")
    # StaffRegistForm/StaffEditFormはrank/positionをChoiceFieldで検証するが、CSV取込は
    # Employee.objects.create_user()/save()を直接呼ぶためDjangoのchoices検証を経由しない
    # （choicesはDB/save層では強制されない）。手動フォームと同じ検証をここでも行う
    # （コード監査で発見：以前は不正コードが無検証で保存されていた、2026-08-24修正）。
    if rank_code not in Rank.values:
        raise ValueError(f"職階コードが不正です: {rank_code}")
    if position_code not in Position.values:
        raise ValueError(f"役職コードが不正です: {position_code}")

    with transaction.atomic():
        department = _upsert_department(branch_code, branch_name, section_code, section_name)
        _import_employee(
            employee_no=employee_no, name=name, department=department,
            section_code=section_code, position_code=position_code, rank_code=rank_code,
            manager_flag=manager_flag, actor=actor, summary=summary,
        )


def _upsert_department(branch_code, branch_name, section_code, section_name):
    """xlsx 職員マスタ!B127-138。本支所コード＋部課コードの組み合わせで部署マスタを
    新規登録・更新する（Department.Meta.constraints unique_department_branch_sectionと同じキー）。
    """
    department, created = Department.objects.get_or_create(
        branch_code=branch_code, section_code=section_code,
        defaults={"branch_name": branch_name, "section_name": section_name},
    )
    if not created and (department.branch_name != branch_name or department.section_name != section_name):
        department.branch_name = branch_name
        department.section_name = section_name
        department.save(update_fields=["branch_name", "section_name"])
    return department


def _import_employee(*, employee_no, name, department, section_code, position_code, rank_code, manager_flag, actor, summary):
    try:
        employee = Employee.objects.get(employee_no=employee_no)
    except Employee.DoesNotExist:
        employee = None

    if employee is None:
        # xlsx B117-119「職員マスタテーブルに存在しない場合...新規登録扱いとし『権限管理』は
        # 初期値をセットしておく。パスワードの初期値はjaXXXX(XXXXは職員番号)とする」。
        employee = Employee.objects.create_user(
            employee_no=employee_no, name=name, password="ja" + employee_no[-4:],
            department=department, rank=rank_code, position=position_code,
            is_retired=(section_code == RETIRED_SECTION_CODE),
        )
        PermissionProfile.objects.create(employee=employee, role=PermissionRole.STAFF)
        summary.created += 1
        _apply_manager_flag(employee, manager_flag, actor)
        return

    changed_fields = []
    department_changed = employee.department_id != department.pk
    rank_changed = employee.rank != rank_code
    position_changed = employee.position != position_code

    if employee.name != name:
        # xlsx B111-112(Rev1.1)「職員番号が同じで氏名が変わった場合...氏名を更新する」。
        employee.name = name
        changed_fields.append("name")
    if department_changed:
        employee.department = department
        changed_fields.append("department")
    if rank_changed:
        employee.rank = rank_code
        changed_fields.append("rank")
    if position_changed:
        employee.position = position_code
        changed_fields.append("position")

    is_retiring_now = section_code == RETIRED_SECTION_CODE and not employee.is_retired
    if is_retiring_now:
        # xlsx B114-115「部課コードが"99"の場合...退職扱いとし対象職員の退職フラグをセットする」。
        employee.is_retired = True
        changed_fields.append("is_retired")

    if changed_fields:
        employee.save(update_fields=changed_fields)
        # xlsx B108-109「部課コード、役職コード、職階コードのいずれかに差分があった場合...
        # 異動、昇格/降格扱いとし権限設定をリセットする」。退職も同じくリセット対象
        # （accounts.services.reset_permission_profile_if_needed参照）。
        reset_permission_profile_if_needed(
            employee, department_changed=department_changed, rank_changed=rank_changed,
            position_changed=position_changed, retired_changed=is_retiring_now, actor=actor,
        )
        if is_retiring_now:
            summary.retired += 1
        else:
            summary.updated += 1
    else:
        summary.unchanged += 1

    _apply_manager_flag(employee, manager_flag, actor)


def _apply_manager_flag(employee, manager_flag, actor):
    """xlsx B124-125(Rev1.1)「所属長フラグが"1"の場合...後述『権限管理』権限マスタの対象者を
    『所属長』として権限更新する」。

    - STAFF → MANAGER：従来どおり昇格。
    - ADMIN → MANAGER：Rev1.5 職員マスタ!B127-128 で降格を許容（以前は「CSV取込という間接経路で
      管理者権限を意図せず引き下げる事故を避ける」ため据え置いていたが、Rev1.5 が明示的に
      「システム権限"管理者"が所属長フラグによって"所属長"に変更になった際、管理者が0人に
      ならないようチェックを設ける」＝降格前提のチェックを要求したため方針転換。
      ユーザー確認済み 2026-09-04）。ただし would_orphan_admins() が True（他に管理者が居ない）
      なら、B128「メッセージを表示し、CSV取込による更新を中止する」に従い ValueError を投げる。
      import_staff_csv() 側でその行のトランザクションがロールバックされ summary.errors に集積される
      （中止は行単位。1行のミスで取込全体を止めないという本モジュールの方針〈import_staff_csv
      docstring〉に沿う）。
    - MANAGER：変更なし。

    退職扱いになった職員は昇格・降格とも行わない（同じ行でreset_permission_profile_if_neededが
    安全側にSTAFFへリセット済み。HRエクスポート側で所属長フラグが退職時に再ゼロ化されていない
    実データがあり得るため、コード側で防御する。コード監査で発見、2026-08-24修正）。
    """
    if manager_flag != "1":
        return
    if employee.is_retired:
        return
    profile, _ = PermissionProfile.objects.get_or_create(
        employee=employee, defaults={"role": PermissionRole.MANAGER}
    )
    if profile.role == PermissionRole.MANAGER:
        return
    if profile.role == PermissionRole.ADMIN and would_orphan_admins(profile, PermissionRole.MANAGER):
        # reset_permission_profile_if_needed と同じ LastAdminError（ValueError サブクラス）で
        # 揃える。import_staff_csv の except ValueError が行単位に握って summary.errors へ集積する。
        raise LastAdminError(
            "所属長フラグにより管理者を所属長へ変更しようとしましたが、システムの管理者が"
            "0人になるため、この行の取込を中止しました。先に他の職員を管理者に設定してください。"
        )
    previous_role = profile.role
    profile.role = PermissionRole.MANAGER
    profile.save(update_fields=["role"])
    demotion = previous_role == PermissionRole.ADMIN
    logger.info(
        "CSV取込の所属長フラグにより権限を所属長へ更新しました: employee_no=%s %s->manager",
        employee.employee_no, previous_role,
    )
    # reset_permission_profile_if_needed（accounts/services.py）と同種の「権限に関わる操作」
    # のため、こちらもaudit_services.log()で操作履歴ログへ記録する（コード監査で発見：
    # 以前はlogger.infoのみで、CSV取込経由の所属長昇格が/audit/画面から追跡できなかった）。
    audit_services.log(
        employee=actor,
        action="職員マスタ　CSV取込 所属長降格" if demotion else "職員マスタ　CSV取込 所属長昇格",
        event_message=(
            f"職員：{employee.name}({employee.employee_no}),"
            f"所属長フラグにより権限を{'管理者から' if demotion else ''}所属長へ更新しました"
        ),
    )
