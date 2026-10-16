"""Dmax, Dmed and Dmin above the clear base: read in the rebate, shown on the Negative row's hover."""

from __future__ import annotations

import numpy as np

from negpy.domain.interfaces import PipelineContext
from negpy.domain.models import WorkspaceConfig
from negpy.features.exposure.normalization import LogNegativeBounds, density_above_base, measure_base_log
from negpy.features.exposure.processor import NormalizationProcessor
from negpy.features.exposure.stats import StatRow, negative_statistics
from negpy.features.process.models import ProcessMode
from negpy.infrastructure.simulated.images import film


def _negative() -> np.ndarray:
    """The simulated scan: a picture inside a clear-base band, as the camera sees it."""
    return np.ascontiguousarray(film(600, 900, 3, 24)[0], dtype=np.float32)


def test_the_base_is_the_rebate_of_the_simulated_scan():
    img = _negative()

    base = measure_base_log(img)

    assert base is not None
    assert all(v <= 0.0 for v in base)  # log10 of a transmittance
    picture = img[150:450, 225:675].reshape(-1, 3).mean(axis=1)
    assert 10 ** np.mean(base) > float(np.median(picture))  # a negative's base is its thinnest film


def test_the_base_is_the_rings_plateau_not_its_median():
    """A narrow ring that is mostly perforations: the median is bare light, the plateau is base."""
    from negpy.features.exposure.normalization import _plateau

    rng = np.random.default_rng(0)
    holes = np.full((600, 3), 0.95, dtype=np.float32) + rng.normal(0, 0.03, (600, 3)).astype(np.float32)
    base = np.full((400, 3), 0.60, dtype=np.float32) + rng.normal(0, 0.003, (400, 3)).astype(np.float32)
    ring = np.vstack([holes, base])

    plateau = _plateau(ring)

    assert abs(float(np.median(plateau)) - 0.60) < 0.02
    assert abs(float(np.median(ring)) - 0.95) < 0.05  # what a median would have read


def test_an_export_does_not_measure_the_base():
    context = PipelineContext(scale_factor=1.0, original_size=(900, 600), process_mode=ProcessMode.C41, cache_stages=False)

    NormalizationProcessor(WorkspaceConfig().process).process(_negative(), context)

    assert context.metrics["density_above_base"] is None


def test_a_frame_with_no_film_box_has_no_base():
    assert measure_base_log(np.full((600, 900, 3), 0.5, dtype=np.float32)) is None


def test_the_three_densities_read_above_the_base():
    base = (-0.1, -0.1, -0.1)
    bounds = LogNegativeBounds(floors=(-1.5, -1.5, -1.5), ceils=(-0.3, -0.3, -0.3))
    prefiltered = np.full((50, 3), -0.8, dtype=np.float32)

    dmin, dmed, dmax = density_above_base(base, bounds, prefiltered)

    assert abs(dmin - 0.2) < 1e-6
    assert abs(dmed - 0.7) < 1e-6
    assert abs(dmax - 1.4) < 1e-6
    assert density_above_base(None, bounds, prefiltered) is None


def test_the_base_stage_records_the_metric():
    context = PipelineContext(scale_factor=1.0, original_size=(900, 600), process_mode=ProcessMode.C41)

    NormalizationProcessor(WorkspaceConfig().process).process(_negative(), context)

    dmin, dmed, dmax = context.metrics["density_above_base"]
    assert -0.1 < dmin < dmed < dmax
    assert dmax > 0.5


def test_the_negative_row_carries_the_densities_on_hover():
    rows = negative_statistics(1.26, 0.5, 0.0, 0.0, density_above_base=(0.22, 0.71, 1.42))

    assert rows[0].name == "Negative"
    assert rows[0].value == "1.26 · normal"
    assert "Dmax 1.42 · Dmed 0.71 · Dmin 0.22" in rows[0].detail


def test_a_scan_with_no_base_says_so():
    rows = negative_statistics(1.26, 0.5, 0.0, 0.0, density_above_base=None)

    assert rows[0].detail == "Dmax, Dmed and Dmin need a negative with its clear base beside the picture."


def test_the_hover_shows_the_detail_under_the_fixed_text(qapp):
    from negpy.desktop.view.widgets.stats import NegativeStatsWidget

    widget = NegativeStatsWidget()
    widget.update_stats([StatRow("Negative", "1.26 · normal", detail="Above the clear base: Dmax 1.42 · Dmed 0.71 · Dmin 0.22.")])

    tip = widget._values[0].toolTip()
    assert tip.index("development character") < tip.index("Dmax 1.42")


def test_both_engines_record_the_same_densities():
    from negpy.infrastructure.gpu.device import GPUDevice

    if not GPUDevice.get().is_available:
        import pytest

        pytest.skip("GPU not available")
    from negpy.services.rendering.engine import DarkroomEngine
    from negpy.services.rendering.gpu_engine import GPUEngine

    img = _negative()
    cfg = WorkspaceConfig()
    engine = GPUEngine()
    try:
        _tex, gpu_metrics = engine.process_to_texture(
            img, cfg, scale_factor=1.0, apply_layout=False, readback_metrics=True, source_hash="density", analysis_source_hash="density"
        )
    finally:
        engine.destroy_all()
    context = PipelineContext(scale_factor=1.0, original_size=(900, 600), process_mode=ProcessMode.C41)
    DarkroomEngine().process(img, cfg, "density", context=context)

    cpu, gpu = context.metrics["density_above_base"], gpu_metrics["density_above_base"]
    assert gpu is not None and cpu is not None
    assert all(abs(c - g) < 0.02 for c, g in zip(cpu, gpu)), (cpu, gpu)


def test_a_creative_slider_render_keeps_the_densities():
    """The second render fills its analysis from the cache and skips the meter grid; the
    densities ride that cache instead of dropping to None."""
    from dataclasses import replace

    from negpy.infrastructure.gpu.device import GPUDevice

    if not GPUDevice.get().is_available:
        import pytest

        pytest.skip("GPU not available")
    from negpy.services.rendering.gpu_engine import GPUEngine

    img = _negative()
    cfg = WorkspaceConfig()
    engine = GPUEngine()
    try:
        _tex, first = engine.process_to_texture(
            img, cfg, scale_factor=1.0, apply_layout=False, readback_metrics=True, source_hash="cache", analysis_source_hash="cache"
        )
        darker = replace(cfg, exposure=replace(cfg.exposure, density=cfg.exposure.density + 0.3))
        _tex, second = engine.process_to_texture(
            img, darker, scale_factor=1.0, apply_layout=False, readback_metrics=True, source_hash="cache", analysis_source_hash="cache"
        )
    finally:
        engine.destroy_all()

    assert first["density_above_base"] is not None
    assert second["density_above_base"] == first["density_above_base"]
