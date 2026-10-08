"""State tied to the frame being left does not carry over to the next one."""

from unittest.mock import MagicMock

from negpy.desktop.controller import AppController
from negpy.domain.models import WorkspaceConfig


def test_load_file_drops_marked_keystone_lines_and_the_flat_peek():
    ctrl = MagicMock()
    ctrl._prefetch_gen = 0
    ctrl._keystone_lines = {"left": ((0.1, 0.1), (0.1, 0.9)), "right": ((0.9, 0.1), (0.9, 0.9))}
    ctrl.state.flat_peek = True
    ctrl.state.config = WorkspaceConfig()
    ctrl._render_memo.get.return_value = None

    AppController.load_file(ctrl, "/p/b.tif")

    assert ctrl._keystone_lines == {}
    ctrl.keystone_lines_cleared.emit.assert_called_once()
    assert ctrl.state.flat_peek is False
    ctrl.flat_peek_changed.emit.assert_called_once_with(False)
