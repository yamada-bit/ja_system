import logging

from django import forms
from django.forms.utils import flatatt
from django.forms.widgets import Widget
from django.utils.html import escape
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)


class PopupSelectWidget(Widget):
    """popup-select（部署/分類/年/カテゴリー選択ポップアップ、core/static/js/common.js参照）用の
    ウィジェット。「表示用readonly text input」「送信用hidden input」「選択ボタン」の3点セットを
    描画する。原本HTMLの`<input readonly><button onclick="openPopupPopup(...)">選択</button>`構造を
    Django Widgetとして再現したもの。

    `multi=True`の場合（screen-searchの検索条件）はカンマ区切りの複数値を扱う
    （`value_from_datadict`がリストを返す＝ModelMultipleChoiceField/MultipleChoiceFieldと組み合わせる）。
    `multi=False`の場合（screen-storage2の保管先入力）は単一値
    （ModelChoiceField/TypedChoiceFieldと組み合わせる）。
    """

    def __init__(
        self, *, popup_type, mode, api_url, queryset=None, label_func=str, attrs=None, multi=False, extra_query=None,
        display_attrs=None, display_multiline=False,
    ):
        self.popup_type = popup_type
        self.mode = mode
        self.api_url = api_url
        # display_multiline: 表示用要素を1行の<input type="text">ではなく複数行の<textarea>で描画する。
        # 原本の大半のpopup-selectは1行inputだが、権限管理編集（簡易設計指示書 Rev1.3 権限管理!AI89
        # 「画面変更」、埋め込みスクショが唯一の一次情報源）では文書管理-分類-表示／契約書-部門間閲覧設定／
        # 契約書-分類-表示の3欄が、選択した分類・部署がカンマ区切りで長くなっても全件見えるよう
        # 複数行のtextareaに変更された。共通ウィジェットのためフラグで切り替え、他画面の見た目は変えない。
        self.display_multiline = display_multiline
        # display_attrs: 表示用inputのHTML属性文字列を個別上書きする。mode="search"は本来
        # JS側の選択方式（チェックボックス複数選択）を切り替えるためのフラグであり、CSS幅とは
        # 無関係の概念。しかし原本では大半のsearch系popup-selectが250px固定だったため、当初は
        # modeから幅を導出していた。原本には同じmode="search"でも幅が異なる箇所（部署管理の
        # 統合・分割対象選択=幅指定無し、権限管理のdoc_visible_groups/contract_visible_groups
        # =200px）があるため、個別に上書きできるようにする。未指定時は従来通りmodeから導出する。
        self.display_attrs = display_attrs
        # extra_query（例: permissions.AuthorityEditFormのdoc_kbn）はrender()内でのみ文字列結合する。
        # api_urlは`reverse_lazy()`を想定しており、フォームクラス定義時点（インポート時）に
        # f-string等で早期にstr()化するとURLconf未ロードでエラーになりうるため、遅延させる。
        self.extra_query = extra_query or {}
        self.queryset = queryset
        self.label_func = label_func
        self.multi = multi
        super().__init__(attrs)

    def value_from_datadict(self, data, files, name):
        raw = data.get(name, "")
        if self.multi:
            return [v for v in raw.split(",") if v] if raw else []
        return raw or None

    def format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        raw_value = self.format_value(value)
        final_attrs = self.build_attrs(self.attrs, attrs)
        hidden_id = final_attrs.get("id", f"id_{name}")
        display_id = f"{hidden_id}_display"
        # フィールドがdisabled（権限管理で権限が"管理者"でないユーザーの部署欄等）の場合は、
        # 画面を問わず行自体は残したまま「選択」ボタンだけ非表示にし、自部署を読み取り専用表示する
        # （検索画面はindex.html search-button-dept.style.display切り替え、保管画面２は
        # xlsx 保管!B79-82「選択ボタンが表示されず自部署に固定される」に準拠）。
        is_disabled = bool(final_attrs.get("disabled"))

        labels = []
        if raw_value:
            raw_list = [v for v in raw_value.split(",") if v]
            if self.queryset is not None:
                # raw_listはvalue_from_datadict()経由でPOSTの生データがそのまま渡ってくる。
                # フォームの別フィールドがバリデーションエラーで再表示される場合、このrender()は
                # Djangoのフィールド側clean()（ModelChoiceField等が持つpk変換の例外処理）を経由
                # せずに直接呼ばれるため、数値に変換できない改ざん値（例: "abc"）が混入していると
                # queryset.filter(pk__in=raw_list)実行時に無防備な`ValueError`が送出され、
                # フォーム再表示全体を巻き込んで500になってしまう。全画面共通の基盤ウィジェット
                # であるため、ここで自前に防御する：整数変換できる値だけをqueryset検索に渡し、
                # 変換できない値は改ざんの兆候としてlogger.warningに残した上で表示ラベルからは
                # 黙って除外する（表示用の補助情報に過ぎず、ここで例外を送出してフォーム全体の
                # 再表示を止める必要は無いという設計判断）。
                valid_pks = []
                invalid_values = []
                for v in raw_list:
                    try:
                        int(v)
                    except (TypeError, ValueError):
                        invalid_values.append(v)
                    else:
                        valid_pks.append(v)
                if invalid_values:
                    logger.warning(
                        "PopupSelectWidgetに非数値の選択値が渡されました（改ざんの可能性）: "
                        "popup_type=%s, values=%s",
                        self.popup_type, invalid_values,
                    )
                try:
                    obj_map = {str(o.pk): self.label_func(o) for o in self.queryset.filter(pk__in=valid_pks)}
                except (ValueError, TypeError):
                    # pkが将来UUID等の非整数型に変わった場合等、上のint()フィルタでは防ぎきれない
                    # ケースに備えた保険（多重防御）。ここでも例外は投げず、表示ラベルを諦めて
                    # 空扱いにするだけに留める。
                    logger.warning(
                        "PopupSelectWidgetのqueryset.filter(pk__in=...)で予期しない値エラー"
                        "（改ざんの可能性）: popup_type=%s",
                        self.popup_type,
                    )
                    obj_map = {}
                labels = [obj_map.get(v, v) for v in raw_list]
            else:
                labels = [self.label_func(v) for v in raw_list]
        display_value = ", ".join(labels)

        hidden_attrs = dict(final_attrs)
        hidden_attrs.pop("class", None)
        hidden_attrs.update(
            {"type": "hidden", "name": name, "id": hidden_id, "data-display": display_id, "value": raw_value}
        )

        # 表示用inputの見た目は原本準拠：保管画面（storage）は`input-fixed-200`クラス（200px）、
        # 検索画面（search）はインラインstyleで250px（screen-search.htmlの#search-dept等を参照）。
        # display_attrsが明示的に指定されていればそちらを優先する（上のコメント参照）。
        if self.display_attrs is not None:
            display_attrs = self.display_attrs
        elif self.mode == "search":
            display_attrs = 'style="width:250px; display:inline-block;"'
        else:
            display_attrs = 'class="input-fixed-200"'

        api_url = str(self.api_url)
        if self.extra_query:
            from urllib.parse import urlencode

            api_url = f"{api_url}?{urlencode(self.extra_query)}"

        button_html = ""
        if not is_disabled:
            button_html = (
                f" <button type=\"button\" onclick=\"openPopupPopup(this, '{escape(self.popup_type)}', "
                f"'{escape(self.mode)}', '{escape(api_url)}')\">選択</button>"
            )
        if self.display_multiline:
            # textareaは値を属性ではなくタグ内容として持つ。原本 index.html html5（Rev1.3で画面変更、
            # Rev1.4時点のマークアップ）では rows="5" ＋リサイズ可（ブラウザ既定のresize）。
            # 選択ボタンを上端に揃えるvertical-align:top等は呼び出し側のdisplay_attrsに含める
            # （ここでstyle属性を二重に出さない）。
            display_html = (
                f'<textarea id="{escape(display_id)}" rows="5" {display_attrs} '
                f'placeholder="選択ボタンより選択" readonly>{escape(display_value)}</textarea>'
            )
        else:
            display_html = (
                f'<input type="text" id="{escape(display_id)}" {display_attrs} '
                f'value="{escape(display_value)}" placeholder="選択ボタンより選択" readonly>'
            )
        html = (
            f"{display_html}"
            f"<input{flatatt(hidden_attrs)}>"
            f"{button_html}"
        )
        return mark_safe(html)


class InlineRadioSelect(forms.RadioSelect):
    """検索フォームの「いずれかを含む／すべて含む」「保存日／保存満了日」ラジオ用。

    Djangoの既定`RadioSelect`は選択肢ごとに`<div>`で囲み、CSS（`django_widgets.css`の
    `margin-right:10px`）で間隔を取る。原本index.html:383,387,395は
    `<input> いずれかを含む　<input> すべて含む`のようにラップ要素を挟まず全角スペース1文字で
    区切るフラットな構造のため、実測（`getBoundingClientRect()`）で2番目以降の選択肢が
    3〜7px原本より左にズレていた（全角スペースの実寸とCSS固定10pxが一致しないため）。
    テンプレート経由だと選択肢間に余分な空白テキストノードが入り込みやすくpx単位の一致が
    崩れるため、`PopupSelectWidget`と同様に`render()`で直接HTML文字列を組み立てる。
    """

    def render(self, name, value, attrs=None, renderer=None):
        if value is None:
            value = []
        elif not isinstance(value, (list, tuple)):
            value = [value]
        value = {str(v) for v in value}

        final_attrs = self.build_attrs(self.attrs, attrs)
        widget_id = final_attrs.pop("id", None)
        final_attrs.pop("name", None)
        extra_attrs = flatatt(final_attrs) if final_attrs else ""

        parts = []
        for i, (option_value, option_label) in enumerate(self.choices):
            option_value = str(option_value)
            option_id = f"{widget_id}_{i}" if widget_id else None
            id_attr = f' id="{escape(option_id)}"' if option_id else ""
            for_attr = f' for="{escape(option_id)}"' if option_id else ""
            checked = " checked" if option_value in value else ""
            parts.append(
                f'<label{for_attr}><input type="radio" name="{escape(name)}" '
                f'value="{escape(option_value)}"{id_attr}{extra_attrs}{checked}> '
                f"{escape(option_label)}</label>"
            )
        wrapper_id = f' id="{escape(widget_id)}"' if widget_id else ""
        return mark_safe(f"<span{wrapper_id}>" + "　".join(parts) + "</span>")
