from django.db import models

from core.text_normalization import normalize_for_search


class UuidPrefixedFilenameMixin(models.Model):
    """storage_paths.*_upload_pathが付与する重複防止UUIDプレフィックス（"{uuid}_{filename}"形式）
    を除いた、元のアップロードファイル名部分だけを返す`display_name`プロパティ。
    documents.Document.display_name/contracts.Contract.display_nameが完全に同一実装のまま
    重複していたため集約した（品質レビューで発見、2026-08-25修正。Rev1.6でcontracts.RelatedFileは
    廃止）。`file`フィールドを持つモデルで継承する。
    """

    class Meta:
        abstract = True

    @property
    def display_name(self):
        basename = self.file.name.rsplit("/", 1)[-1]
        return basename.split("_", 1)[1] if "_" in basename else basename


class NormalizedTextFieldsMixin(models.Model):
    """ユーザー入力の title/memo のシャドウカラム（*_normalized）を、save()のたびに
    core.text_normalization.normalize_for_search()で再計算・永続化するMixin。
    documents.Document.save/contracts.Contract.saveが完全に同一実装のまま重複していたため
    集約した（品質レビューで発見、2026-08-25修正）。

    update_fieldsが指定されたsave()（例：title だけ更新）でもDjangoは列挙カラムしか
    UPDATE文に含めないため、対応する正規化カラムをここで追加する。

    update_fields指定時は、その中に元カラムが含まれる正規化だけを計算する。論理削除・移動
    （update_fields=["is_deleted","deleted_at"]）では正規化を一切走らせない
    （コードレビューR-7、2026-08-28修正）。

    `extracted_text_normalized` はこのMixinの対象外：以前は生 `extracted_text` カラムから
    save() ごとに導出していたが、生カラムを廃止（監査 案1、2026-09-11）し、抽出サービス
    （core.text_extraction_services / core.management.commands.extract_pending_pdf_text）が
    NFKC 正規化した値を直接セットして `save(update_fields=["extracted_text_normalized",
    "text_extracted"])` する方式に変えた。通常の title/memo 保存でこの列を触らないため、
    OCR全文（数十KB〜数MB）を毎回無駄に再正規化する問題も無くなった。
    """

    # (元カラム, シャドウカラム) の対応。Fieldではない単なるクラス属性。
    _NORMALIZED_FIELD_MAP = (
        ("title", "title_normalized"),
        ("memo", "memo_normalized"),
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        targets = None if update_fields is None else set(update_fields)
        for src, shadow in self._NORMALIZED_FIELD_MAP:
            if targets is None or src in targets:
                setattr(self, shadow, normalize_for_search(getattr(self, src)))
                if targets is not None:
                    targets.add(shadow)
        if targets is not None:
            kwargs["update_fields"] = targets
        super().save(*args, **kwargs)
