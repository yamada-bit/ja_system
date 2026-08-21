import shutil
import tempfile
from pathlib import Path

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class IsolatedMediaTestRunner(DiscoverRunner):
    """テスト実行中だけ`settings.MEDIA_ROOT`を一時ディレクトリへ差し替えるテストランナー。

    core/documents/contractsの各tests.pyはSimpleUploadedFile等で実際にファイルI/O
    （一時アップロード領域への保存、storage_pathsへの登録等）を行うが、MEDIA_ROOTを
    差し替えずに実行すると本番相当のストレージ（`../storage/media/`）に直接書き込まれ、
    多くのテストはassert対象ではない副産物のため後片付けもされない。2026-08-13、
    `python manage.py test`の反復実行により storage/media 配下に実データ（DB参照あり
    50件）の100倍近い数のテスト残骸が蓄積していたことが発覚し、個々のtests.pyを直す
    のではなくテスト実行全体を一時ディレクトリで包むことで、将来追加されるテストが
    同じ問題を再発させないようにした。

    `config.settings.base`の`TEST_RUNNER`で指定し、`manage.py test`実行時のみ使われる
    （通常の`runserver`等では従来通りMEDIA_ROOTを使う）。
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media_root_tmp = tempfile.mkdtemp(prefix="ja_pj_test_media_")
        # settings.MEDIA_ROOTは通常Path型（config/settings/base.py）のため、差し替え後も型を
        # 揃える（str型のままだと`settings.MEDIA_ROOT / "sub_dir"`のようなPath演算子を使う
        # 呼び出し側コードがTypeErrorになる）。
        self._media_root_override = override_settings(MEDIA_ROOT=Path(self._media_root_tmp))
        self._media_root_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._media_root_override.disable()
        shutil.rmtree(self._media_root_tmp, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
