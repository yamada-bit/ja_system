import io
import logging

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import Error as DBError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from pypdf.errors import PyPdfError

from audit import services as audit_services
from core import deletion_services, searchable_pdf_services
from core.file_serving import apply_file_response_security_headers, resolve_as_attachment
from core.searchable_pdf_services import SearchablePdfUnavailable
from permissions.services import can_download

logger = logging.getLogger(__name__)


class BaseFileServeView(View):
    """検索結果詳細のダウンロード/プレビュー共通実装。documents.views.DownloadView/PreviewView・
    contracts.views.DownloadView/PreviewViewの計4クラスが、モデル・as_attachment・監査ログ文言
    以外完全に同一実装のまま重複していたため集約した（品質レビューで発見、2026-08-25修正）。

    `model`/`kind`/`scoped_lookup`/`as_attachment`/`audit_action`/`entity_label`をクラス変数で
    指定して継承する（`scoped_lookup`はdocuments.services.scoped_get_object_or_404/
    contracts.services.scoped_get_object_or_404を`staticmethod()`でラップして渡す）。documents側は
    監査ログに`personal_info_flag`も付与するため`audit_extra_kwargs()`をオーバーライドする。
    """

    model = None
    kind = None
    scoped_lookup = None
    as_attachment = None
    audit_action = None
    entity_label = None

    def audit_extra_kwargs(self, obj):
        return {}

    def get(self, request, pk):
        obj = self.scoped_lookup(self.model.objects.filter(is_deleted=False), request.user, pk)
        if not can_download(request.user, kind=self.kind):
            action_label = "ダウンロード" if self.as_attachment else "プレビュー"
            logger.warning(
                "%s権限の無いユーザーによる試行: employee_no=%s %s_id=%s",
                action_label,
                request.user.employee_no,
                self.kind,
                pk,
            )
            raise PermissionDenied(f"{action_label}権限がありません。")
        try:
            # セキュリティレビュー H-3: プレビュー（as_attachment=False）でも、PDF・ラスター画像
            # 以外はインライン配信させず添付ダウンロードへ倒す。加えてどの形式でも nosniff と
            # 実行禁止 CSP を付与し、アップロードされた .html/.svg 等が同一オリジンで実行される
            # 経路を塞ぐ（core.file_serving のモジュール docstring 参照）。
            as_attachment = resolve_as_attachment(
                wants_inline=not self.as_attachment, filename=obj.display_name
            )
            response = FileResponse(
                obj.file.open("rb"), as_attachment=as_attachment, filename=obj.display_name
            )
            apply_file_response_security_headers(response)
        except OSError:
            # FileNotFoundError（実体欠損）だけでなくPermissionError（ロック・権限エラー等）も
            # OSErrorのサブクラスのため、ストレージI/O境界で起こりうるOSError全般をここで
            # 利用者向けのHttp404に変換する。
            logger.exception("ファイル実体の取得に失敗しました: %s_id=%s", self.kind, pk)
            raise Http404("ファイルが見つかりません。")
        # 原本にはない追加対応（2026-08-12）。登録・更新・削除は元々audit_services.log()で
        # 記録されるのに、文書管理システムの核心操作である「誰がいつ閲覧・持ち出したか」の
        # ダウンロード/プレビューだけ監査ログに一切残っていなかった（未実装改善候補の棚卸しで
        # 発見）。ファイルI/O成功後（ユーザーが実際に中身を受け取れる状態になった後）に記録する。
        # イベントメッセージは原本index.html:3310,3312,3316,3317の操作履歴ログサンプル
        # （「ファイル名：契約書_001」等）に合わせ、タイトルではなく実ファイル名(display_name)を
        # 「ファイル名：」形式で記録する（原本フィデリティ監査で発見：以前は
        # 「{entity_label}「{title}」を〜しました。」という原本に無い独自形式だった）。
        audit_services.log(
            employee=request.user,
            action=self.audit_action,
            event_message=f"ファイル名：{obj.display_name}",
            **self.audit_extra_kwargs(obj),
        )
        return response


class BaseSearchablePdfView(View):
    """検索用PDF（OCRテキスト埋め込み版）の遅延生成・配信共通実装（監査 案3、2026-09-11）。

    `ocr_textdata` が保存されているスキャン文書について、原本PDF＋座標データからその場で透明
    テキストを埋め込んだPDFを組み立てて添付ダウンロード配信する。`can_download` 権限で保護し、
    BaseFileServeView と同じセキュリティヘッダを付与する。旧 `searchable_file`（事前生成・恒久
    保存のFileField）を置き換えたもの。従来の実装と同じく、この時点ではどの画面からもリンクして
    いない（利用者向けUIの追加は別途）。

    `model`/`kind`/`scoped_lookup`/`audit_action` をクラス変数で指定して継承する。
    """

    model = None
    kind = None
    scoped_lookup = None
    audit_action = None

    def audit_extra_kwargs(self, obj):
        return {}

    def get(self, request, pk):
        obj = self.scoped_lookup(self.model.objects.filter(is_deleted=False), request.user, pk)
        if not can_download(request.user, kind=self.kind):
            logger.warning(
                "検索用PDFダウンロード権限の無いユーザーによる試行: employee_no=%s %s_id=%s",
                request.user.employee_no, self.kind, pk,
            )
            raise PermissionDenied("ダウンロード権限がありません。")
        try:
            pdf_bytes = searchable_pdf_services.build_searchable_pdf(obj)
        except SearchablePdfUnavailable:
            # テキスト層PDF・OCR前・OCR_STORE_TEXTDATA=False でOCRされた文書は座標データを
            # 持たないため生成できない。
            raise Http404("この文書には検索用PDFがありません。")
        except OSError:
            logger.exception("検索用PDF生成時のファイル実体取得に失敗しました: %s_id=%s", self.kind, pk)
            raise Http404("ファイルが見つかりません。")
        except PyPdfError:
            # 原本PDF実体が破損・切り詰め等でpypdfが解析できない場合（core.pdf_text_embed_services.
            # embed_textdatas_into_pdfのPdfReader呼び出しが送出）。OSErrorと同様にファイルI/O境界の
            # 異常として扱い、未捕捉のまま500になるのを防ぐ（2026-09-11監査で発見：案3のPDF埋め込み
            # 遅延生成〈core.searchable_pdf_services〉導入時、pypdf固有の例外がここに素通しだった）。
            logger.exception("検索用PDF生成時にPDFの解析に失敗しました: %s_id=%s", self.kind, pk)
            raise Http404("この文書のPDFを読み込めませんでした。")
        response = FileResponse(
            io.BytesIO(pdf_bytes),
            as_attachment=True,
            filename=f"検索用_{obj.display_name}",
            content_type="application/pdf",
        )
        apply_file_response_security_headers(response)
        audit_services.log(
            employee=request.user,
            action=self.audit_action,
            event_message=f"ファイル名：{obj.display_name}",
            **self.audit_extra_kwargs(obj),
        )
        return response


class BaseBulkDownloadView(View):
    """screen-search「一括ダウンロード」共通実装。documents.views.BulkDownloadView/
    contracts.views.BulkDownloadViewが完全に同一実装のまま重複していたため集約した
    （品質レビューで発見、2026-08-25修正）。

    `model`/`kind`/`dept_ids_resolver`/`zip_builder`/`audit_action`/`entity_label`/
    `search_url_name`/`zip_filename`をクラス変数で指定して継承する。documents側は監査ログに
    `personal_info_flag`も付与するため`audit_extra_kwargs()`をオーバーライドする。
    """

    model = None
    kind = None
    dept_ids_resolver = None
    zip_builder = None
    audit_action = None
    entity_label = None
    search_url_name = None
    zip_filename = None

    def audit_extra_kwargs(self, objects):
        return {}

    @staticmethod
    def _file_size(obj):
        """合計サイズ判定用。実体欠損（OSError）やファイル未設定（ValueError）は0として数える
        （欠損の扱いはZIP構築側が missing_count として利用者へ警告するため、ここでは止めない）。"""
        try:
            return obj.file.size
        except (OSError, ValueError):
            return 0

    def post(self, request):
        pks = request.POST.getlist("pks")
        if not pks:
            # 通常はクライアント側 common.js startBulkDownload() のalertで弾かれる
            # （2026-09-08ユーザー依頼で一括編集と同じalert方式に変更）。ここはURL直打ち・
            # JS無効時の保険。文言はそのalert（「ダウンロードするデータが選択されていません。」）に
            # 合わせる（BulkEditStartViewのmessagesがstartBulkEditのalert文言に揃えてあるのと同じ）。
            messages.error(request, "ダウンロードするデータが選択されていません。")
            return redirect(self.search_url_name)
        if not can_download(request.user, kind=self.kind):
            logger.warning(
                "ダウンロード権限の無いユーザーによる一括ダウンロード試行: employee_no=%s",
                request.user.employee_no,
            )
            raise PermissionDenied("ダウンロード権限がありません。")

        # pksはURLパスコンバータを経由しない生のPOST値のため、改ざんや誤ったリンク等で数値以外が
        # 混入し得る（search_services.build_queryset参照）。無効な値は除外しつつ、不正アクセス
        # 試行の兆候として警告ログに残す。
        valid_pks = []
        for p in pks:
            try:
                valid_pks.append(int(p))
            except (TypeError, ValueError):
                logger.warning(
                    "一括ダウンロードの選択値(pks)に不正な値が含まれていたため除外しました: "
                    "employee_no=%s value=%r",
                    request.user.employee_no,
                    p,
                )

        # セキュリティレビューで発見：部署スコープ外の対象も静かに除外する
        # （scoped_get_object_or_404 docstring参照。2026-08-25修正）。
        allowed_department_ids = self.dept_ids_resolver(request.user)
        objects = self.model.objects.filter(pk__in=valid_pks, is_deleted=False)
        if allowed_department_ids is not None:
            objects = objects.filter(department_id__in=allowed_department_ids)
        # クエリセットを一度だけ評価する。以前は count()・zip_builder の反復・audit_extra_kwargs
        # 内の privacy_flag 集計でそれぞれ再SELECTしていた（コードレビューR-4、2026-08-28修正）。
        objects = list(objects)
        total_count = len(objects)

        # ZIPはメモリ上で組み立てて一括で返すため（core.zip_services.build_zip_archive）、
        # 合計サイズが大きいとメモリ不足や、リクエストのタイムアウト（httpPlatformHandlerの
        # requestTimeout/LB）による502になる。構築前にファイルサイズだけで判定して拒否し、
        # 選択を減らして再実行するよう案内する（上限はsettings.BULK_DOWNLOAD_MAX_TOTAL_BYTES）。
        total_bytes = sum(self._file_size(obj) for obj in objects)
        if total_bytes > settings.BULK_DOWNLOAD_MAX_TOTAL_BYTES:
            limit_mb = settings.BULK_DOWNLOAD_MAX_TOTAL_BYTES // (1024 * 1024)
            logger.warning(
                "一括ダウンロードの合計サイズが上限を超えたため拒否しました: employee_no=%s 件数=%s 合計=%sバイト",
                request.user.employee_no, total_count, total_bytes,
            )
            messages.error(
                request,
                f"選択したファイルの合計サイズが上限（{limit_mb}MB）を超えているためダウンロードできません。"
                "選択する件数を減らして、もう一度お試しください。",
            )
            return redirect(self.search_url_name)
        # ZIP構築自体はcore.zip_services.build_zip_archiveへ分離済み（規約準拠監査で発見：
        # ファイルI/Oを伴うビジネスロジックがビューに直書きされていた。件数の不一致は下の
        # messages.warningで利用者にも案内する）。
        zip_bytes, missing_count = self.zip_builder(objects)

        logger.info(
            "一括ダウンロードを実行しました: employee_no=%s 件数=%s", request.user.employee_no, total_count
        )
        # 単体ダウンロード/プレビューと同様の追加対応（2026-08-12）。個々のファイル単位ではなく
        # 一括ダウンロード1回の操作として1件だけ記録する（ZIPに含まれる件数だけログが増殖すると
        # 操作履歴ログ本来の「画面操作の履歴」という粒度から外れるため）。
        audit_services.log(
            employee=request.user,
            action=self.audit_action,
            event_message=f"{self.entity_label}{total_count}件を一括ダウンロードしました。",
            **self.audit_extra_kwargs(objects),
        )
        if missing_count:
            # 「見つからなかった」だけでなく権限不整合・I/Oエラー等も含む（zip_servicesの捕捉範囲を
            # OSError全般に広げたため。レビュー指摘C-3）。
            messages.warning(
                request,
                f"選択した{total_count}件中{missing_count}件のファイルを取得できなかったため、"
                "ダウンロードされたZIPに含まれていません。",
            )
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{self.zip_filename}"'
        return response


class BaseDeleteView(View):
    """検索結果詳細ポップアップ「削除」ボタン共通実装（論理削除のみ）。documents.views.DeleteView/
    contracts.views.DeleteViewが、contracts側の追加権限チェック（can_edit_contract）・監査ログの
    personal_info_flag以外完全に同一実装のまま重複していたため集約した（品質レビューで発見、
    2026-08-25修正）。

    原本index.html:1125-1131のtriggerDeleteFromDetail()はfetch()の完了を待ってポップアップを
    閉じる・完了アラート・一覧再描画を行う設計のため、common.js側は`X-Requested-With`ヘッダーを
    付けてAJAX呼び出しし、JSONレスポンスを期待する（AJAXでない直接POSTはredirectを返す）。

    `model`/`scoped_lookup`/`entity_label`/`search_url_name`をクラス変数で指定して継承する。
    contracts側のような追加の権限チェックは`extra_permission_check()`をオーバーライドする
    （Noneを返せば許可、それ以外は拒否理由メッセージ文字列を返す）。documents側は監査ログに
    personal_info_flagも付与するため`audit_extra_kwargs()`をオーバーライドする。
    """

    model = None
    scoped_lookup = None
    entity_label = None
    audit_action = "検索・閲覧画面　削除"
    search_url_name = None

    def extra_permission_check(self, request, obj):
        return None

    def audit_extra_kwargs(self, obj):
        return {}

    def post(self, request, pk):
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        try:
            obj = self.scoped_lookup(self.model.objects.all(), request.user, pk)
        except Http404:
            # common.js側はfetch().then(r=>r.json())で応答をJSONとしてparseするため、AJAX呼び出し
            # 時にDjango標準の404 HTMLページを返すとクラスdocstring記載のバグが別経路（対象未存在）
            # で再発する。AJAX判定時はJSONで404を返す。
            if is_ajax:
                return JsonResponse(
                    {"success": False, "message": f"対象の{self.entity_label}が見つかりません。"}, status=404
                )
            raise

        denial_message = self.extra_permission_check(request, obj)
        if denial_message is not None:
            if is_ajax:
                return JsonResponse({"success": False, "message": denial_message}, status=403)
            raise PermissionDenied(denial_message)

        if not deletion_services.can_delete(obj):
            # 削除済み、および初回登録から1週間以上経過しているものは削除不可。UI側
            # （common.jsのrenderDetailPopup()）はdelete_urlがNoneの間ボタン自体を隠すが、
            # API直叩き等に備えサーバー側でも拒否する。
            logger.warning(
                "削除できない%sへの削除操作を拒否しました: employee_no=%s pk=%s is_deleted=%s",
                self.entity_label,
                request.user.employee_no,
                pk,
                obj.is_deleted,
            )
            message = deletion_services.deletion_denial_message(obj, entity_name=self.entity_label)
            if is_ajax:
                return JsonResponse({"success": False, "message": message}, status=403)
            raise PermissionDenied(message)

        try:
            obj.is_deleted = True
            obj.deleted_at = timezone.now()
            obj.save(update_fields=["is_deleted", "deleted_at"])
        except DBError:
            # DB接続断・制約違反等で削除が失敗した場合も、上記と同じ理由でAJAX時はJSONを返す
            # 必要がある（このexcept節が無いと非AJAX時と同じ生の500応答になりfetch側が壊れる）。
            logger.exception("%sの削除処理に失敗しました: pk=%s", self.entity_label, pk)
            if is_ajax:
                return JsonResponse(
                    {"success": False, "message": "削除に失敗しました。もう一度お試しください。"}, status=500
                )
            messages.error(request, "削除に失敗しました。もう一度お試しください。")
            return redirect(self.search_url_name)

        audit_services.log(
            employee=request.user,
            action=self.audit_action,
            event_message=f"{self.entity_label}「{obj.title}」を削除しました。",
            **self.audit_extra_kwargs(obj),
        )
        success_message = f"{self.entity_label}を削除しました。"

        if is_ajax:
            return JsonResponse({"success": True, "message": success_message})
        return self._post_delete_redirect(request, obj, success_message)

    def _post_delete_redirect(self, request, obj, success_message):
        """非AJAX削除（画面フォームからのPOST）後の遷移。完了メッセージを出して検索画面へ戻る。
        単独編集画面（edit.html）の削除ボタンもこの経路で、EditDeleteViewは監査ログのaction名を
        差し替えるだけで遷移先はこの既定のまま（検索画面）。一括編集（BulkEditView）の削除は
        「更新」ボタンでまとめて確定するステージ型のため、このビューは通らない。
        遷移先を変えたいサブクラスがあればここをオーバーライドできる（現状は該当なし）。"""
        messages.success(request, success_message)
        return redirect(self.search_url_name)
