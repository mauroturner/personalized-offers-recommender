"""The charts the design draws its previews with (U16): every label is escaped, an empty chart says there is no data and a value that is not a number is not drawn."""

from __future__ import annotations

from personaloffers.dashboard import svg


def test_every_chart_escapes_its_labels_and_says_there_is_no_data_when_it_has_none():
    for chart in (svg.bar_chart([], 300, 100, "T"), svg.grouped_bar_chart([], 300, 100, "T"), svg.line_chart({}, 300, 100, "T")):
        assert "Sin datos" in chart and chart.startswith("<svg")
    bars = svg.bar_chart([("<b>a</b>", 3.0), ("b", float("nan")), ("c", 1.0)], 400, 120, "Barras <x>", unit="%")
    assert "&lt;b&gt;a&lt;/b&gt;" in bars and "<b>" not in bars and "Barras &lt;x&gt;" in bars and bars.count("<path") == 2 and "<script" not in bars
    grouped = svg.grouped_bar_chart([("lunes", {"cargadas <solas>": 10.0, "a revisión": 4.0}), ("martes", {"cargadas <solas>": 12.0, "a revisión": 3.0})], 400, 160, "Por día")
    assert "cargadas &lt;solas&gt;" in grouped and "<solas>" not in grouped and "var(--series-1)" in grouped and "var(--series-2)" in grouped


def test_a_line_with_a_missing_point_is_drawn_without_it_and_a_dashed_series_is_dashed():
    chart = svg.line_chart({"a": [(0.0, 1.0), (1.0, float("nan")), (2.0, 3.0)], "b": [(0.0, 2.0), (2.0, 2.5)]}, 400, 150, "Líneas", dashed=["b"])
    assert "stroke-dasharray" in chart and "nan" not in chart.lower() and chart.count("<polyline") == 1 and chart.count('r="3"') == 2, "the series with a missing value breaks its line into two lone points"
