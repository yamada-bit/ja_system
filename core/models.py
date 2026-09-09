from django.db import models


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
    """title/memo/extracted_textのシャドウカラム（*_normalized）を、save()のたびに
    core.text_normalization.normalize_for_search()で再計算・永続化するMixin。
    documents.Document.save/contracts.Contract.saveが完全に同一実装のまま重複していたため
    集約した（品質レビューで発見、2026-08-25修正）。

    update_fieldsが指定されたsave()（core.text_extraction_services/extract_pending_pdf_text
    バッチのsave(update_fields=["extracted_text"])等）ではDjangoがそこに列挙されたカラムしか
    UPDATE文に含めないため、対応する正規化カラムをここで追加しないと値をセットしたつもりでも
    DBに反映されない。title/memo/extracted_text/title_normalized/memo_normalized/
    extracted_text_normalizedの6フィールドを持つモデルで継承する。

    update_fields指定時は、その中に元カラムが含まれる正規化だけを計算する。論理削除・移動
    （update_fields=["is_deleted","deleted_at"]）では正規化を一切走らせない。extracted_textは
    OCR全文で数十KBになり得るため、一括削除で件数ぶん無駄なNFKC正規化を避ける
    （コードレビューR-7、2026-08-28修正）。
    """

    # (元カラム, シャドウカラム) の対応。Fieldではない単なるクラス属性。
    _NORMALIZED_FIELD_MAP = (
        ("title", "title_normalized"),
        ("memo", "memo_normalized"),
        ("extracted_text", "extracted_text_normalized"),
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from core.text_normalization import normalize_for_search

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
