import logging

from django.contrib import messages
from django.db import Error as DBError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from audit import services as audit_services
from core import bulk_edit_services, deletion_services
from core.double_submit import consume_token, issue_token
from core.file_type_services import get_preview_kind
from permissions.services import can_download

logger = logging.getLogger(__name__)


class BaseBulkEditView(View):
    """一括編集ウィザード本体（ステージング型。2026-08-28ユーザー確定）の共通実装。

    `BulkEditStartView` がセッションに積んだpk一覧をページャー（＜ N/M ＞）で1件ずつ巡回し、
    入力値・削除マーク（契約書は関連書類の増減も）を**すべてセッションにステージ**する。
    「更新」ボタンを押したときに初めて全ページを検証→1トランザクションで確定する（変更が無い
    ページは「更新なし」で保存も監査ログもしない＝DB現在値との比較。1ページでも入力エラーが
    あれば全体を止め最初のエラーページを表示）。「キャンセル」でステージ内容を破棄する。

    documents.views.BulkEditView / contracts.views.BulkEditView が、モデル・フォーム初期値・
    監査ログ文言・（契約書のみ）関連書類ステージを除き行単位でほぼ一致していたため集約した
    （コードレビュー B No.4、2026-09-09。core.record_views の BaseFileServeView /
    BaseBulkDownloadView / BaseDeleteView と同じパターン）。ステージ用のセッション操作は
    `core.bulk_edit_services` に集約済みで、本クラスはそのオーケストレーションと画面遷移を担う。

    以前は各ページ移動の都度DBへ保存する save-as-you-go 方式だった（詳細は
    HTML_REIMPL_CHECKLIST_ARCHIVE.md「一括編集を全ページ一括確定モデルへ改修」節）。
    単体編集用のトークン名（"documents_edit"）とは別の "<app>_bulk_edit" を使い、別タブで
    単体編集中でも干渉しないようにする。

    認証・追加権限（契約書の `RequiresContractEditMixin` 等）はサブクラス側の基底クラスで
    与える（`core.record_views` の各基底ビューと同じく、本クラス自身は `View` のみ継承）。

    サブクラスが指定するクラス変数:
      model / template_name / form_id / session_key / entity_name / kind /
      context_object_name / form_field_names / search_url_name / bulk_edit_url_name /
      scoped_lookup（`staticmethod()` でラップした scoped_get_object_or_404）/
      dept_ids_resolver（`staticmethod()` でラップした *_searchable_department_ids。
      「更新」確定直前の部署スコープ再検証に使う。詳細は `_committable_pks`）
    オーバーライドするフック:
      build_form(obj, data=None, marked_delete=False)          … 必須
      commit_one_update(request, obj, form, state) -> bool      … 必須（dirty判定＋反映、更新したらTrue）
      base_queryset() / commit_queryset(pks)                    … prefetch を足したい場合
      audit_extra_kwargs(obj)                                   … personal_info_flag 等
      stage_extra(request, obj)                                 … 追加のページステージ（関連書類）
      render_context_extra(request, form, state)                … 保存満了日プレビュー・関連書類行 等
      complete_context_extra(request, form)                     … 完了モーダル背後の再描画用
    """

    model = None
    template_name = None
    form_id = None
    session_key = None
    entity_name = None
    kind = None
    context_object_name = None
    form_field_names = ()
    search_url_name = None
    bulk_edit_url_name = None
    scoped_lookup = None
    dept_ids_resolver = None
    audit_update_action = "保管画面２　更新"
    audit_delete_action = "保管画面２　削除"

    # --- サブクラス用フック（既定は最小挙動） -----------------------------------------------
    def base_queryset(self):
        """ページ巡回（`_current_object`）で使う基底クエリセット。"""
        return self.model.objects.filter(is_deleted=False)

    def commit_queryset(self, pks):
        """「更新」確定時に対象を一括ロードするクエリセット。"""
        return self.model.objects.filter(pk__in=pks)

    def build_form(self, obj, data=None, marked_delete=False):
        raise NotImplementedError

    def audit_extra_kwargs(self, obj):
        return {}

    def stage_extra(self, request, obj):
        """`stage_page` の直後に呼ばれる（削除マークされていないページのみ）。契約書はここで
        関連書類（紐付け先契約書pkの並び）をステージする。"""

    def commit_one_update(self, request, obj, form, state):
        """`obj` を `form.cleaned_data` に基づき更新する（変更が無ければ何もしない）。
        実際に更新したら True（＝「更新」）、変更なしなら False（＝「更新なし」）を返す。
        監査ログとトランザクションは呼び出し側（`_commit`）が持つ。"""
        raise NotImplementedError

    def render_context_extra(self, request, form, state):
        """編集ページ描画時にコンテキストへ足し込む追加キー。"""
        return {}

    def complete_context_extra(self, request, form):
        """完了モーダル描画時にコンテキストへ足し込む追加キー。"""
        return {}

    # --- 内部 ----------------------------------------------------------------------------
    def _state(self, request):
        state = bulk_edit_services.get_bulk_edit_state(request.session, self.session_key)
        if not state:
            messages.error(request, "編集対象が選択されていません。検索結果一覧からやり直してください。")
            return None
        return state

    def _current_object(self, request, state):
        # セキュリティレビューで発見：部署スコープ外の対象へのセッション改ざん・URL直打ちを防ぐ
        # （*.services.scoped_get_object_or_404 docstring参照）。
        return self.scoped_lookup(
            self.base_queryset(), request.user, state["pks"][state["index"]]
        )

    def get(self, request):
        state = self._state(request)
        if state is None:
            return redirect(self.search_url_name)
        self.object = self._current_object(request, state)
        marked_delete = bulk_edit_services.is_marked_for_delete(state, self.object.pk)
        staged = bulk_edit_services.staged_page_data(state, self.object.pk)
        form = self.build_form(self.object, data=staged, marked_delete=marked_delete)
        token = issue_token(request.session, self.form_id)
        return render(
            request, self.template_name, self._context(request, form, token, state, marked_delete)
        )

    def post(self, request):
        # 「キャンセル」/「＜ 戻る」：ステージ内容を破棄する。
        if request.POST.get("bulk_action") == "cancel":
            bulk_edit_services.discard_bulk_edit(request.session, self.session_key)
            return redirect(self.search_url_name)

        state = self._state(request)
        if state is None:
            return redirect(self.search_url_name)
        self.object = self._current_object(request, state)

        submitted_token = request.POST.get("token", "")
        if not consume_token(request.session, self.form_id, submitted_token):
            messages.error(request, "二重に送信された可能性があるため処理を中断しました。もう一度やり直してください。")
            return redirect(self.bulk_edit_url_name)

        marked_delete = bulk_edit_services.is_marked_for_delete(state, self.object.pk)
        # 削除予定ページはフィールドがdisabledで送信されないため、入力値のステージ対象にしない。
        if not marked_delete:
            bulk_edit_services.stage_page(
                request.session,
                self.session_key,
                self.object.pk,
                {k: request.POST.get(k, "") for k in self.form_field_names},
            )
            self.stage_extra(request, self.object)

        total = len(state["pks"])
        index = state["index"]
        action = request.POST.get("bulk_action")
        nav = request.POST.get("bulk_nav")

        if action == "toggle_delete":
            # セキュリティレビュー M-1: 削除マークを「付ける」操作は can_delete() をサーバー側で
            # 検証する（マーク解除は常に許可）。_commit 側にも同じ検証があるが、そもそも不正な
            # マークを積ませない。
            if not marked_delete and not deletion_services.can_delete(self.object):
                logger.warning(
                    "一括編集で削除できない%sへの削除マークを拒否しました: employee_no=%s pk=%s",
                    self.entity_name,
                    request.user.employee_no,
                    self.object.pk,
                )
                messages.error(
                    request,
                    deletion_services.deletion_denial_message(self.object, entity_name=self.entity_name),
                )
                return redirect(self.bulk_edit_url_name)
            bulk_edit_services.toggle_delete_mark(request.session, self.session_key, self.object.pk)
            return redirect(self.bulk_edit_url_name)
        if nav == "prev":
            if index > 0:
                bulk_edit_services.set_bulk_edit_index(request.session, self.session_key, index - 1)
            return redirect(self.bulk_edit_url_name)
        if nav == "next":
            if index < total - 1:
                bulk_edit_services.set_bulk_edit_index(request.session, self.session_key, index + 1)
            return redirect(self.bulk_edit_url_name)

        # 「更新」ボタン（bulk_action=update）：全ページ一括確定。
        return self._commit(request)

    def _committable_pks(self, request, pks):
        """「更新」確定の直前に、ウィザード開始後の状況変化を反映して「いま確定してよい」pk集合を
        絞り直す。`resolve_ordered_pks` が開始時に保証する「is_deleted=False ＋ 部署スコープ」を
        確定経路でも再適用する（コードレビュー audit/core No.1、2026-09-10）。

        `_current_object`（各ページ表示）は `scoped_lookup` と `base_queryset()` を通すが、
        確定経路の `commit_queryset(pks)` は既定が pk__in だけで、表示中でない他ページの pk は
        一切再検証されなかった。想定シナリオ:
          (a) ウィザード開始後に管理者が当該職員の閲覧部署範囲を縮小 → もう閲覧できない他部署
              レコードへのステージ済み編集/削除がそのまま確定される。
          (b) 別タブ／他ユーザーが対象を論理削除した後に「更新」 → ゴミ箱内のレコードに編集が
              走り「更新」監査ログまで残る。
        CLAUDE.md「ボタンの表示/非表示とサーバー側権限チェックは別物」「URL直打ち／セッション
        改ざんを想定してサーバー側も確認する」。`dept_ids_resolver` 未設定のサブクラス
        （保管画面２等）では is_deleted のみ再確認する。
        """
        qs = self.model.objects.filter(pk__in=pks, is_deleted=False)
        if self.dept_ids_resolver is not None:
            allowed_department_ids = self.dept_ids_resolver(request.user)
            if allowed_department_ids is not None:
                qs = qs.filter(department_id__in=allowed_department_ids)
        return set(qs.values_list("pk", flat=True))

    def _commit(self, request):
        state = bulk_edit_services.get_bulk_edit_state(request.session, self.session_key)
        pks = state["pks"]
        to_delete = set(state.get("to_delete", []))
        staged = state.get("staged", {})
        committable = self._committable_pks(request, pks)
        # 開始後に部署スコープ外・論理削除済みになった pk は確定対象から静かに除外する
        # （resolve_ordered_pks と同じく「選択した覚えのない対象」を確定に紛れ込ませない）。
        objs_by_pk = {
            o.pk: o for o in self.commit_queryset(pks) if o.pk in committable
        }
        dropped = [pk for pk in pks if pk not in committable]
        if dropped:
            logger.warning(
                "%sの一括編集確定時に、開始後スコープ外/論理削除済みになった対象を除外しました: "
                "employee_no=%s pks=%s",
                self.entity_name,
                request.user.employee_no,
                dropped,
            )

        # --- 検証パス：ステージ済みで削除予定でない全ページを検証。1つでもNGなら全体を止める。 ---
        forms_by_pk = {}
        invalid = []  # [(index, form)]
        for i, pk in enumerate(pks):
            if pk in to_delete or str(pk) not in staged or pk not in objs_by_pk:
                continue
            f = self.build_form(objs_by_pk[pk], data=staged[str(pk)])
            if f.is_valid():
                forms_by_pk[pk] = f
            else:
                invalid.append((i, f))

        if invalid:
            first_index, first_form = invalid[0]
            bulk_edit_services.set_bulk_edit_index(request.session, self.session_key, first_index)
            messages.error(request, f"{first_index + 1}件目に入力エラーがあります。修正してください。")
            self.object = objs_by_pk[pks[first_index]]
            token = issue_token(request.session, self.form_id)
            state = bulk_edit_services.get_bulk_edit_state(request.session, self.session_key)
            return render(
                request,
                self.template_name,
                self._context(request, first_form, token, state, marked_delete=False),
            )

        # --- 削除予定pkの can_delete() 検証パス（セキュリティレビュー M-1） ---
        # UI は edit.html の {% if can_delete %} で「削除」ボタンを隠すが、セッション改ざんや
        # toggle_delete ハンドラの直叩きで削除マークが付く余地があるため、確定前にサーバー側でも
        # 「削除済み／登録から1週間以上経過」を再検証する（BaseDeleteView.post 等、他の全削除経路と
        # 同じ扱い。1件でもNGならコミット全体を止めて該当ページへ誘導する）。
        undeletable = [
            i
            for i, pk in enumerate(pks)
            if pk in to_delete and pk in objs_by_pk and not deletion_services.can_delete(objs_by_pk[pk])
        ]
        if undeletable:
            first_index = undeletable[0]
            self.object = objs_by_pk[pks[first_index]]
            bulk_edit_services.set_bulk_edit_index(request.session, self.session_key, first_index)
            logger.warning(
                "一括編集で削除できない%sへの削除確定を拒否しました: employee_no=%s pk=%s is_deleted=%s",
                self.entity_name,
                request.user.employee_no,
                self.object.pk,
                self.object.is_deleted,
            )
            messages.error(
                request,
                f"{first_index + 1}件目: "
                + deletion_services.deletion_denial_message(self.object, entity_name=self.entity_name),
            )
            token = issue_token(request.session, self.form_id)
            state = bulk_edit_services.get_bulk_edit_state(request.session, self.session_key)
            return render(
                request,
                self.template_name,
                self._context(
                    request,
                    self.build_form(self.object, marked_delete=True),
                    token,
                    state,
                    marked_delete=True,
                ),
            )

        # --- 確定パス ---
        status_by_pk = {}
        try:
            with transaction.atomic():
                for pk in pks:
                    obj = objs_by_pk.get(pk)
                    if obj is None:
                        continue
                    if pk in to_delete:
                        obj.is_deleted = True
                        obj.deleted_at = timezone.now()
                        obj.save(update_fields=["is_deleted", "deleted_at"])
                        audit_services.log(
                            employee=request.user,
                            action=self.audit_delete_action,
                            event_message=f"{self.entity_name}「{obj.title}」を削除しました。",
                            **self.audit_extra_kwargs(obj),
                        )
                        status_by_pk[pk] = "削除"
                    elif pk in forms_by_pk:
                        f = forms_by_pk[pk]
                        if self.commit_one_update(request, obj, f, state):
                            audit_services.log(
                                employee=request.user,
                                action=self.audit_update_action,
                                event_message=f"{self.entity_name}「{obj.title}」を更新しました。",
                                **self.audit_extra_kwargs(obj),
                            )
                            status_by_pk[pk] = "更新"
                        else:
                            status_by_pk[pk] = "更新なし"
                    else:
                        status_by_pk[pk] = "更新なし"
        except DBError:
            logger.exception(
                "%sの一括編集確定中にエラーが発生しました: employee_no=%s",
                self.entity_name,
                request.user.employee_no,
            )
            messages.error(request, "更新に失敗しました。もう一度お試しください。")
            return redirect(self.bulk_edit_url_name)

        bulk_edit_services.clear_bulk_edit_state(request.session, self.session_key)
        return self._render_complete(request, pks, status_by_pk)

    def _render_complete(self, request, pks, status_by_pk):
        rows_objs = {o.pk: o for o in self.model.objects.filter(pk__in=pks)}
        rows = [
            {"obj": rows_objs[pk], "status": status_by_pk.get(pk, "更新なし")}
            for pk in pks
            if pk in rows_objs
        ]
        counts = {
            "updated": sum(1 for r in rows if r["status"] == "更新"),
            "unchanged": sum(1 for r in rows if r["status"] == "更新なし"),
            "deleted": sum(1 for r in rows if r["status"] == "削除"),
        }
        if not rows:
            # 更新確定の直後に対象が全件物理削除された場合（日次purgeバッチとの競合）。完了モーダルの
            # 背後に敷くフォームを描画できないため検索画面へ戻す（コードレビューC-7、2026-08-28修正）。
            messages.error(request, "編集対象が見つかりませんでした。検索結果一覧からやり直してください。")
            return redirect(self.search_url_name)
        # 完了モーダルの背後に敷くedit.htmlは1件目のフォームで描画する（モーダルが全面を覆う）。
        self.object = rows[0]["obj"]
        form = self.build_form(self.object)
        token = issue_token(request.session, self.form_id)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                self.context_object_name: self.object,
                "token": token,
                "title_field": form["title_0"],
                "complete": {"mode": "bulk", "rows": rows, "counts": counts},
                "preview_kind": get_preview_kind(self.object.display_name),
                "can_download": can_download(request.user, kind=self.kind),
                **self.complete_context_extra(request, form),
            },
        )

    def _context(self, request, form, token, state, marked_delete):
        total = len(state["pks"])
        index = state["index"]
        return {
            "form": form,
            self.context_object_name: self.object,
            "token": token,
            "title_field": form["title_0"],
            "preview_kind": get_preview_kind(self.object.display_name),
            "can_download": can_download(request.user, kind=self.kind),
            "bulk": {
                "index": index + 1,
                "total": total,
                "has_prev": index > 0,
                "has_next": index < total - 1,
            },
            "marked_delete": marked_delete,
            "can_delete": deletion_services.can_delete(self.object),
            **self.render_context_extra(request, form, state),
        }
