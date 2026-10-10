from types import SimpleNamespace
from unittest.mock import MagicMock

from negpy.desktop.view.widgets.granular_settings_dialog import open_paste_dialog
from negpy.domain.models import WorkspaceConfig


def _controller(clipboard, rows=None):
    state = SimpleNamespace(current_file_hash="h", clipboard=clipboard, clipboard_rows=rows)
    return SimpleNamespace(session=MagicMock(state=state), set_status=MagicMock())


def test_an_empty_clipboard_says_so():
    controller = _controller(None)
    open_paste_dialog(None, controller)
    controller.set_status.assert_called_once_with("Nothing to paste", 2000)
    controller.session.apply_pasted_fields.assert_not_called()


def test_a_card_copy_pastes_its_rows_with_no_picker():
    rows = [object()]
    controller = _controller(WorkspaceConfig(), rows)
    open_paste_dialog(None, controller)
    controller.session.apply_pasted_fields.assert_called_once_with(rows, include_bounds=False)
