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


def test_the_diptych_view_refuses_canvas_tools_and_edits():
    """Both halves are on screen, each with its own edit, so a canvas point names neither."""
    from negpy.desktop.session import AppState, ToolMode

    ctrl = MagicMock()
    ctrl.state = AppState()
    ctrl.active_diptych.return_value = ({"hash": "h"}, (WorkspaceConfig(), WorkspaceConfig()))
    ctrl._diptych_blocks_canvas = lambda: AppController._diptych_blocks_canvas(ctrl)

    AppController.set_active_tool(ctrl, ToolMode.CLONE)
    AppController.handle_canvas_clicked(ctrl, 0.5, 0.5)
    AppController.handle_local_mask_created(ctrl, "polygon", [(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)])

    assert ctrl.state.active_tool == ToolMode.NONE
    ctrl.session.update_config.assert_not_called()
    ctrl._handle_wb_pick.assert_not_called()


def test_load_file_drops_the_left_frames_geometry_grid():
    import numpy as np

    from negpy.desktop.session import AppState

    ctrl = MagicMock()
    ctrl._prefetch_gen = 0
    ctrl.state = AppState()
    ctrl.state.last_metrics["uv_grid"] = np.zeros((2, 2, 2), np.float32)
    ctrl.state.last_metrics["active_roi"] = (0, 2, 0, 2)
    ctrl._render_memo.get.return_value = None
    ctrl._retain_displayed_texture.return_value = None

    AppController.load_file(ctrl, "/p/b.tif")

    assert "uv_grid" not in ctrl.state.last_metrics
    assert "active_roi" not in ctrl.state.last_metrics
