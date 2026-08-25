from django.db import models


class UuidPrefixedFilenameMixin(models.Model):
    """storage_paths.*_upload_pathが付与する重複防止UUIDプレフィックス（"{uuid}_{filename}"形式）
    を除いた、元のアップロードファイル名部分だけを返す`display_name`プロパティ。
    documents.Document.display_name/contracts.Contract.display_name/contracts.RelatedFile.
    display_nameの3箇所が完全に同一実装のまま重複していたため集約した（品質レビューで発見、
    2026-08-25修正）。`file`フィールドを持つモデルで継承する。
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
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from core.text_normalization import normalize_for_search

        self.title_normalized = normalize_for_search(self.title)
        self.memo_normalized = normalize_for_search(self.memo)
        self.extracted_text_normalized = normalize_for_search(self.extracted_text)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "title" in update_fields:
                update_fields.add("title_normalized")
            if "memo" in update_fields:
                update_fields.add("memo_normalized")
            if "extracted_text" in update_fields:
                update_fields.add("extracted_text_normalized")
            kwargs["update_fields"] = update_fields
        super().save(*args, **kwargs)
