"""Stills fired on the camera's own shutter land in the roll like a Scan's.

The camera announces a file it took by itself; nothing tells NegPy a shot was coming.
"""

from __future__ import annotations

import os
import time

import pytest

from negpy.desktop.workers.capture_worker import CaptureRequest, CaptureWorker
from negpy.infrastructure.capture.gphoto import GphotoCamera
from negpy.infrastructure.simulated.gphoto import SimGphoto
from negpy.services.capture.service import CaptureError, last_frame_number, save_body_capture

_RAW = b"\x00" * (9 * 1024 * 1024)


@pytest.fixture
def sim():
    return SimGphoto()


@pytest.fixture
def camera(sim, tmp_path):
    collected: list[tuple[str, bytes]] = []
    saves: list[bool] = [True]  # what the save reports back; tests flip it to refuse

    def _on_body_capture(name: str, data: bytes) -> bool:
        collected.append((name, data))
        return saves[0]

    cam = GphotoCamera(
        gp_module=sim,
        jpeg_path=str(tmp_path / "live.jpg"),
        settings_path=str(tmp_path / "live.json"),
        on_body_capture=_on_body_capture,
    )
    cam.open()
    cam.collected = collected  # ty: ignore[unresolved-attribute]
    cam.saves = saves  # ty: ignore[unresolved-attribute]
    yield cam
    cam.close()


def _streaming(camera) -> None:
    camera.watch_body_captures(True)
    camera.start()
    assert _wait(lambda: os.path.exists(camera.jpeg_path)), "the preview never streamed"


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_a_shot_fired_on_the_body_is_downloaded_then_deleted(camera, sim):
    _streaming(camera)

    sim.fire_body_shot()

    assert _wait(lambda: camera.collected), "the body's own shot was never collected"
    name, data = camera.collected[0]
    assert name.lower().endswith(".dng")
    assert data[:2] in (b"II", b"MM")  # a TIFF-based RAW, not the preview JPEG
    assert _wait(lambda: sim.deleted == ["DSC00001.DNG"]), "the saved shot was left on the camera"


def test_a_failed_save_leaves_the_shot_on_the_camera(camera, sim):
    _streaming(camera)
    camera.saves[0] = False

    sim.fire_body_shot()

    assert _wait(lambda: camera.collected), "the body's own shot was never collected"
    time.sleep(0.3)
    assert sim.deleted == []


def test_a_raw_plus_jpeg_body_keeps_its_jpeg(camera, sim):
    """Both files are announced; the JPEG is not a scan and stays where the operator put it."""
    _streaming(camera)

    sim.fire_body_shot("DSC00001.JPG")
    sim.fire_body_shot("DSC00001.DNG")

    assert _wait(lambda: camera.collected), "the RAW was never collected"
    assert [name for name, _ in camera.collected] == ["DSC00001.DNG"]
    assert _wait(lambda: sim.deleted == ["DSC00001.DNG"])


def test_a_chatty_body_does_not_bury_its_shot(camera, sim):
    """Property-change events queue ahead of the file; one poll per frame reads past them."""
    _streaming(camera)
    sim.noise_events = 40
    sim.fire_body_shot()

    assert _wait(lambda: camera.collected), "the shot sat behind the chatter"


def test_a_shot_fired_during_a_scan_is_collected_after_its_drain(camera, sim, tmp_path):
    """The post-shot drain reads the body's file-added event; it is kept, not discarded."""
    _streaming(camera)

    sim.fire_body_shot("DSC00002.DNG")  # queued ahead of the scan's own events
    camera.capture(str(tmp_path / "scan.raw"))

    assert _wait(lambda: camera.collected), "the drain swallowed the body's shot"
    assert camera.collected[0][0] == "DSC00002.DNG"


def test_canon_is_left_out_of_the_poll(camera, sim):
    from dataclasses import replace

    camera._capabilities = replace(camera._capabilities, driver_model="Canon EOS M6")
    _streaming(camera)

    sim.fire_body_shot()
    time.sleep(0.5)

    assert camera.collected == []
    assert sim.body_shots == 1


def test_the_body_is_not_polled_unless_someone_collects(camera, sim):
    camera.start()
    assert _wait(lambda: os.path.exists(camera.jpeg_path)), "the preview never streamed"

    sim.fire_body_shot()
    time.sleep(0.5)

    assert camera.collected == []
    assert sim.body_shots == 1  # still queued on the body, unread


def test_stopping_the_preview_stops_collecting(camera, sim):
    """The poll lives in the preview loop, so the worker re-applies it on every start."""
    _streaming(camera)
    camera.stop()

    sim.fire_body_shot()
    camera.start()
    time.sleep(0.5)

    assert camera.collected == []


def test_a_restarted_preview_collects_again(camera, sim):
    camera.start()
    camera.stop()
    camera.watch_body_captures(True)
    camera.start()
    assert _wait(lambda: os.path.exists(camera.jpeg_path)), "the preview never streamed"

    sim.fire_body_shot()

    assert _wait(lambda: camera.collected), "the restarted stream never collected the shot"


def test_save_body_capture_numbers_the_next_frame(tmp_path):
    (tmp_path / "Roll1_Frame007.ARW").write_bytes(b"x")

    path = save_body_capture(
        _RAW,
        roll_name="Roll1",
        frame_number=last_frame_number(str(tmp_path), "Roll1") + 1,
        output_folder=str(tmp_path),
        suffix=".ARW",
    )

    assert os.path.basename(path) == "Roll1_Frame008.ARW"
    assert os.path.getsize(path) == len(_RAW)


def test_an_implausible_raw_leaves_no_file_behind(tmp_path):
    with pytest.raises(CaptureError):
        save_body_capture(b"too small", roll_name="Roll1", frame_number=1, output_folder=str(tmp_path), suffix=".ARW")

    assert os.listdir(tmp_path) == []


def _armed_worker(folder: str) -> CaptureWorker:
    worker = CaptureWorker()
    worker.set_body_capture_target(
        CaptureRequest(roll_name="Roll1", frame_number=0, output_folder=folder, levels=(0, 0, 0), rgb_mode=False)
    )
    return worker


def test_the_worker_reports_the_saved_shot_as_a_finished_capture(qapp, tmp_path):
    (tmp_path / "Roll1_Frame003.ARW").write_bytes(b"x")
    worker = _armed_worker(str(tmp_path))
    done: list[tuple] = []
    statuses: list[str] = []
    worker.finished.connect(lambda paths, req: done.append((paths, req)))
    worker.status.connect(statuses.append)

    assert worker._on_body_capture("DSC00001.ARW", _RAW) is True

    assert statuses == []
    paths, req = done[0]
    assert [os.path.basename(p) for p in paths] == ["Roll1_Frame004.ARW"]
    assert req.frame_number == 4  # the placeholder the target was armed with never reaches the import
    assert req.rgb_mode is False


def test_a_shot_with_nowhere_to_go_is_dropped(qapp, tmp_path):
    worker = CaptureWorker()
    done: list[tuple] = []
    worker.finished.connect(lambda paths, req: done.append((paths, req)))

    assert worker._on_body_capture("DSC00001.ARW", _RAW) is False

    assert done == []


def test_a_shot_that_cannot_be_saved_is_reported_and_kept(qapp, tmp_path):
    """A status line, not an error: an error closes Live View, and the session is fine."""
    worker = _armed_worker(str(tmp_path))
    statuses: list[str] = []
    errors: list[str] = []
    worker.status.connect(statuses.append)
    worker.error.connect(errors.append)

    assert worker._on_body_capture("DSC00001.ARW", b"too small") is False

    assert errors == []
    assert len(statuses) == 1 and "stays on the camera" in statuses[0]
    assert os.listdir(tmp_path) == []


def test_a_body_shot_during_a_scan_numbers_after_it(qapp, tmp_path):
    """A scan's file is invisible to the folder until it is promoted, so the body's shot waits."""
    import threading

    worker = _armed_worker(str(tmp_path))
    done: list[tuple] = []
    worker.finished.connect(lambda paths, req: done.append((paths, req)))

    def _scan() -> None:
        with worker._frame_lock:  # what run_capture holds for the whole scan
            time.sleep(0.3)
            (tmp_path / "Roll1_Frame001.ARW").write_bytes(b"x")

    scan = threading.Thread(target=_scan)
    scan.start()
    time.sleep(0.05)
    worker._on_body_capture("DSC00001.ARW", _RAW)
    scan.join()

    assert [os.path.basename(p) for p in done[0][0]] == ["Roll1_Frame002.ARW"]


def test_a_fresh_scan_takes_the_number_a_body_shot_took(tmp_path):
    """The sidebar numbers a scan before the worker runs it; a body shot may land in between."""
    from negpy.desktop.workers import capture_worker as module

    (tmp_path / "Roll1_Frame001.ARW").write_bytes(b"x")  # the body's shot, after the sidebar said "1"
    seen: list[int] = []

    def _capture_single(camera, *, roll_name, frame_number, output_folder, shutter, cancel):
        seen.append(frame_number)
        return os.path.join(output_folder, f"{roll_name}_Frame{frame_number:03d}.ARW")

    worker = CaptureWorker()
    worker._acquire_camera = lambda: object()  # ty: ignore[invalid-assignment]
    worker._holds_camera = lambda: True  # ty: ignore[invalid-assignment]
    done: list[tuple] = []
    worker.finished.connect(lambda paths, req: done.append((paths, req)))
    original = module.capture_single
    module.capture_single = _capture_single
    try:
        worker.run_capture(CaptureRequest(roll_name="Roll1", frame_number=1, output_folder=str(tmp_path), levels=(0, 0, 0), rgb_mode=False))
    finally:
        module.capture_single = original

    assert seen == [2]
    assert done[0][1].frame_number == 2


def test_opening_a_body_starts_it_unwatched(camera):
    camera.watch_body_captures(True)
    camera.close()
    camera.open()

    assert not camera._watch_body.is_set()


def _non_rgb_sidebar(monkeypatch, folder: str):
    from unittest.mock import MagicMock

    from negpy.desktop.view.sidebar.scanlight import ScanlightSidebar

    ctrl = MagicMock()
    ctrl.session.repo.get_global_setting.return_value = {}
    sidebar = ScanlightSidebar(ctrl)
    monkeypatch.setattr(sidebar.output, "folder", lambda: folder)
    monkeypatch.setattr(sidebar.output, "target_folder", lambda: folder)
    monkeypatch.setattr(sidebar.output, "roll_name", lambda: "Roll1")
    sidebar._camera_verified = True
    sidebar._set_rgb_mode(False)
    return sidebar, ctrl


def test_the_sidebar_arms_a_fresh_roll_whose_folder_does_not_exist_yet(qapp, monkeypatch, tmp_path):
    sidebar, ctrl = _non_rgb_sidebar(monkeypatch, str(tmp_path))
    monkeypatch.setattr(sidebar.output, "target_folder", lambda: str(tmp_path / "Roll1"))

    sidebar.lv_btn.setChecked(True)

    assert ctrl.arm_body_capture.call_args[0][0].output_folder == str(tmp_path / "Roll1")


def test_the_sidebar_arms_only_while_the_live_view_is_open(qapp, monkeypatch, tmp_path):
    sidebar, ctrl = _non_rgb_sidebar(monkeypatch, str(tmp_path))

    sidebar.lv_btn.setChecked(True)
    armed = ctrl.arm_body_capture.call_args[0][0]
    sidebar.lv_btn.setChecked(False)

    assert armed.roll_name == "Roll1"
    assert armed.output_folder == str(tmp_path)
    assert armed.rgb_mode is False
    assert ctrl.arm_body_capture.call_args[0][0] is None


def test_a_scanlight_preset_never_arms(qapp, monkeypatch, tmp_path):
    sidebar, ctrl = _non_rgb_sidebar(monkeypatch, str(tmp_path))
    sidebar._set_rgb_mode(True)

    sidebar.lv_btn.setChecked(True)

    assert all(call[0][0] is None for call in ctrl.arm_body_capture.call_args_list)
