from types import SimpleNamespace

import pytest

from app.tasks.detect import (
    LOUD_MIN_DUR,
    MAX_TOTAL_MOMENTS,
    MIN_LEN,
    SENT_GAP,
    SILENCE_EXTEND,
    SNAP_WINDOW,
    _build_annotated,
    _cap_section_lengths,
    _coverage_metrics,
    _dedup_overlap,
    _fmt_ts,
    _loud_spikes,
    _parse_ts,
    _script_windows,
    _sentence_boundaries,
    _slice_annotated,
    _snap_moment,
)


def _section(start, end, topic="topic"):
    return SimpleNamespace(start=start, end=end, topic=topic)


def _moment(start_sec, end_sec, final):
    return SimpleNamespace(scores={"final": final}, start_sec=start_sec, end_sec=end_sec)


# ---------------------------------------------------------------------------
# _fmt_ts
# ---------------------------------------------------------------------------

def test_fmt_ts_zero():
    assert _fmt_ts(0) == "0:00:00"


def test_fmt_ts_negative_clamped():
    assert _fmt_ts(-5) == "0:00:00"


def test_fmt_ts_truncates_not_rounds():
    assert _fmt_ts(59.9) == "0:00:59"


def test_fmt_ts_string_input():
    assert _fmt_ts("45") == "0:00:45"


def test_fmt_ts_minute_boundary():
    assert _fmt_ts(60) == "0:01:00"


def test_fmt_ts_hour_boundary():
    assert _fmt_ts(3600) == "1:00:00"


def test_fmt_ts_multi_hour():
    assert _fmt_ts(36661) == "10:11:01"


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

def test_parse_ts_hms():
    assert _parse_ts("0:00:00") == 0.0


def test_parse_ts_full():
    assert _parse_ts("1:02:03") == 3723.0


def test_parse_ts_ms():
    assert _parse_ts("2:03") == 123.0


def test_parse_ts_bare_seconds():
    assert _parse_ts("45") == 45.0


def test_parse_ts_extra_colon_levels():
    # generic base-60 fold-left: sec = ((1*60+2)*60+3)*60+4
    assert _parse_ts("1:2:3:4") == 223384.0


def test_parse_ts_malformed_raises():
    with pytest.raises(ValueError):
        _parse_ts("1:xx:00")


def test_parse_ts_empty_string_raises():
    with pytest.raises(ValueError):
        _parse_ts("")


def test_parse_ts_fmt_ts_roundtrip():
    for value in [0, 45, 123, 3723, 36661]:
        assert _parse_ts(_fmt_ts(value)) == float(value)


# ---------------------------------------------------------------------------
# _loud_spikes
# ---------------------------------------------------------------------------

def test_loud_spikes_empty():
    assert _loud_spikes([]) == []


def test_loud_spikes_all_below_threshold():
    rms = [{"t": 0.0, "rms_db": -40}, {"t": 0.5, "rms_db": -41}]
    assert _loud_spikes(rms) == []


def test_loud_spikes_isolated_single_reading_dropped():
    # median is -40 (only two points, one loud); duration of the spike is 0 (single
    # sample), which fails the LOUD_MIN_DUR check even though it's above threshold.
    rms = [{"t": 0.0, "rms_db": -40}, {"t": 0.5, "rms_db": 10}]
    assert _loud_spikes(rms) == []


def test_loud_spikes_run_exactly_min_dur_kept():
    rms = [
        {"t": 0.0, "rms_db": -40},
        {"t": 0.0, "rms_db": -40},
        {"t": 1.0, "rms_db": 10},
        {"t": 1.0 + LOUD_MIN_DUR, "rms_db": 10},
    ]
    spikes = _loud_spikes(rms)
    assert len(spikes) == 1
    assert spikes[0][0] == 1.0
    assert spikes[0][1] == 1.0 + LOUD_MIN_DUR


def test_loud_spikes_run_just_under_min_dur_dropped():
    rms = [
        {"t": 0.0, "rms_db": -40},
        {"t": 0.0, "rms_db": -40},
        {"t": 1.0, "rms_db": 10},
        {"t": 1.0 + LOUD_MIN_DUR - 0.1, "rms_db": 10},
    ]
    assert _loud_spikes(rms) == []


def test_loud_spikes_touching_first_sample():
    # Five -40dB baseline readings keep the median at -40 (threshold -32) regardless of
    # the loud pair, so the spike at the very start of the list still clears it.
    rms = [
        {"t": 0.0, "rms_db": 10},
        {"t": LOUD_MIN_DUR, "rms_db": 10},
        {"t": LOUD_MIN_DUR + 1, "rms_db": -40},
        {"t": LOUD_MIN_DUR + 2, "rms_db": -40},
        {"t": LOUD_MIN_DUR + 3, "rms_db": -40},
    ]
    spikes = _loud_spikes(rms)
    assert len(spikes) == 1
    assert spikes[0][0] == 0.0


def test_loud_spikes_touching_last_sample():
    rms = [
        {"t": 0.0, "rms_db": -40},
        {"t": 1.0, "rms_db": -40},
        {"t": 2.0, "rms_db": -40},
        {"t": 3.0, "rms_db": 10},
        {"t": 3.0 + LOUD_MIN_DUR, "rms_db": 10},
    ]
    spikes = _loud_spikes(rms)
    assert len(spikes) == 1
    assert spikes[0][1] == 3.0 + LOUD_MIN_DUR


def test_loud_spikes_two_separate_not_merged():
    # Baseline (-40dB) readings outnumber the loud ones, so the median stays at -40 and
    # both loud pairs clear the +8dB threshold; the baseline readings between them
    # (t=4,5) reset `cur` so the two spikes are not merged into one.
    rms = [
        {"t": 0.0, "rms_db": -40},
        {"t": 1.0, "rms_db": -40},
        {"t": 2.0, "rms_db": 10},
        {"t": 3.0, "rms_db": 10},
        {"t": 4.0, "rms_db": -40},
        {"t": 5.0, "rms_db": -40},
        {"t": 6.0, "rms_db": 10},
        {"t": 7.0, "rms_db": 10},
        {"t": 8.0, "rms_db": -40},
    ]
    spikes = _loud_spikes(rms)
    assert len(spikes) == 2
    assert (spikes[0][0], spikes[0][1]) == (2.0, 3.0)
    assert (spikes[1][0], spikes[1][1]) == (6.0, 7.0)


def test_loud_spikes_peak_db_rounded():
    rms = [
        {"t": 0.0, "rms_db": -40},
        {"t": 1.0, "rms_db": -40},
        {"t": 2.0, "rms_db": -40},
        {"t": 3.0, "rms_db": -31.94},
        {"t": 3.0 + LOUD_MIN_DUR, "rms_db": -31.94},
    ]
    spikes = _loud_spikes(rms)
    assert len(spikes) == 1
    assert spikes[0][2] == round(-31.94 - (-40), 1)


def test_loud_spikes_median_even_length():
    # 4 readings; median is the average of the two middle values.
    rms = [
        {"t": 0.0, "rms_db": -50},
        {"t": 0.5, "rms_db": -40},
        {"t": 1.0, "rms_db": -10},
        {"t": 1.0 + LOUD_MIN_DUR, "rms_db": -10},
    ]
    spikes = _loud_spikes(rms)
    # median of [-50, -40, -10, -10] = -25.0, threshold = -25.0 + 8.0 = -17.0
    assert len(spikes) == 1


def test_loud_spikes_all_above_threshold_relative_to_own_median():
    rms = [{"t": i * 1.0, "rms_db": -20} for i in range(5)]
    # median == -20, threshold = -20 + 8 = -12; none of the -20 readings qualify.
    assert _loud_spikes(rms) == []


# ---------------------------------------------------------------------------
# _script_windows
# ---------------------------------------------------------------------------

def test_script_windows_empty_string_yields_one_empty_window():
    assert _script_windows("", 100) == [""]


def test_script_windows_single_short_line():
    assert _script_windows("hello", 100) == ["hello"]


def test_script_windows_multiple_short_lines_combined():
    assert _script_windows("a\nb\nc", 100) == ["a\nb\nc"]


def test_script_windows_oversized_line_followed_by_more_isolated():
    long_line = "x" * 50
    result = _script_windows(f"{long_line}\nshort", 10)
    assert result[0] == long_line
    assert result[1] == "short"


def test_script_windows_oversized_line_as_last_line_isolated():
    long_line = "x" * 50
    result = _script_windows(f"short\n{long_line}", 10)
    assert result[-1] == long_line


def test_script_windows_boundary_no_split_when_equal():
    # "ab" (len 2) then "\n" -> add=3 for first line; budget chosen so cur_len+add==budget exactly
    result = _script_windows("ab\ncd", 6)
    # "ab" -> add=3, cur_len=3; "cd" -> add=3, cur_len+add=6 == budget -> no split (uses >)
    assert result == ["ab\ncd"]


def test_script_windows_boundary_splits_when_over():
    result = _script_windows("ab\ncd", 5)
    # "ab" -> add=3, cur_len=3; "cd" -> add=3, 3+3=6 > 5 -> split
    assert result == ["ab", "cd"]


def test_script_windows_rejoin_reconstructs_lines():
    text = "line1\nline2\nline3"
    windows = _script_windows(text, 1000)
    assert "\n".join(windows) == text


# ---------------------------------------------------------------------------
# _cap_section_lengths
# ---------------------------------------------------------------------------

def test_cap_section_lengths_empty():
    assert _cap_section_lengths([], 100) == []


def test_cap_section_lengths_span_exactly_max_unchanged():
    sec = _section(_fmt_ts(0), _fmt_ts(100))
    result = _cap_section_lengths([sec], 100)
    assert result == [sec]


def test_cap_section_lengths_oversized_splits():
    sec = _section(_fmt_ts(0), _fmt_ts(250))
    result = _cap_section_lengths([sec], 100)
    # ceil(250/100) = 3 sub-sections
    assert len(result) == 3


def test_cap_section_lengths_evenly_divisible_even_step():
    sec = _section(_fmt_ts(0), _fmt_ts(200))
    result = _cap_section_lengths([sec], 100)
    assert len(result) == 2
    assert _parse_ts(result[0].start) == 0.0
    assert _parse_ts(result[0].end) == 100.0
    assert _parse_ts(result[1].start) == 100.0
    assert _parse_ts(result[1].end) == 200.0


def test_cap_section_lengths_last_subwindow_ends_at_original_end():
    sec = _section(_fmt_ts(0), _fmt_ts(250))
    result = _cap_section_lengths([sec], 100)
    assert _parse_ts(result[-1].end) == 250.0


def test_cap_section_lengths_topic_preserved():
    sec = _section(_fmt_ts(0), _fmt_ts(250), topic="my topic")
    result = _cap_section_lengths([sec], 100)
    assert all(s.topic == "my topic" for s in result)


def test_cap_section_lengths_multiple_sections_independent():
    sec1 = _section(_fmt_ts(0), _fmt_ts(250), topic="a")
    sec2 = _section(_fmt_ts(300), _fmt_ts(320), topic="b")
    result = _cap_section_lengths([sec1, sec2], 100)
    assert len(result) == 4  # 3 splits for sec1 + 1 unchanged for sec2
    assert result[-1].topic == "b"


def test_cap_section_lengths_subwindows_tile_continuously():
    sec = _section(_fmt_ts(0), _fmt_ts(250), topic="a")
    result = _cap_section_lengths([sec], 100)
    for prev, nxt in zip(result, result[1:]):
        assert prev.end == nxt.start


# ---------------------------------------------------------------------------
# _slice_annotated / _build_annotated
# ---------------------------------------------------------------------------

def test_slice_annotated_boundary_inclusive():
    segments = [
        {"start": 5.0, "text": "in bounds start"},
        {"start": 10.0, "text": "in bounds end"},
        {"start": 4.9, "text": "excluded before"},
        {"start": 10.1, "text": "excluded after"},
    ]
    features = {"silences": [], "rms": []}
    result = _slice_annotated(segments, features, 5.0, 10.0)
    assert "in bounds start" in result
    assert "in bounds end" in result
    assert "excluded before" not in result
    assert "excluded after" not in result


def test_slice_annotated_empty_inputs():
    assert _slice_annotated([], {}, 0.0, 10.0) == ""


def test_build_annotated_empty():
    assert _build_annotated([], {}) == ""


def test_build_annotated_skips_empty_text_segment():
    segments = [{"start": 1.0, "text": "   "}]
    assert _build_annotated(segments, {}) == ""


def test_build_annotated_renders_speech_line():
    segments = [{"start": 5.0, "text": "hello world"}]
    result = _build_annotated(segments, {})
    assert result == f"[{_fmt_ts(5.0)}] hello world"


def test_build_annotated_silence_under_one_sec_skipped():
    features = {"silences": [{"silence_start": 1.0, "silence_end": 1.5}]}
    assert _build_annotated([], features) == ""


def test_build_annotated_silence_exactly_one_sec_included():
    features = {"silences": [{"silence_start": 1.0, "silence_end": 2.0}]}
    result = _build_annotated([], features)
    assert "<SILENCE 1.0s>" in result


def test_build_annotated_silence_over_one_sec_formatted():
    features = {"silences": [{"silence_start": 1.0, "silence_end": 3.5}]}
    result = _build_annotated([], features)
    assert "<SILENCE 2.5s>" in result


def test_build_annotated_loud_spike_rendered():
    rms = [
        {"t": 0.0, "rms_db": -40},
        {"t": 1.0, "rms_db": -40},
        {"t": 2.0, "rms_db": -40},
        {"t": 3.0, "rms_db": 10},
        {"t": 3.0 + LOUD_MIN_DUR, "rms_db": 10},
    ]
    features = {"silences": [], "rms": rms}
    result = _build_annotated([], features)
    assert result.startswith("<LOUD +")


def test_build_annotated_tie_break_energy_before_speech():
    segments = [{"start": 2.0, "text": "hello"}]
    features = {"silences": [{"silence_start": 2.0, "silence_end": 3.5}]}
    result = _build_annotated(segments, features)
    lines = result.split("\n")
    assert lines[0].startswith("<SILENCE")
    assert lines[1].startswith("[")


def test_build_annotated_chronological_order():
    segments = [{"start": 10.0, "text": "second"}, {"start": 1.0, "text": "first"}]
    result = _build_annotated(segments, {})
    lines = result.split("\n")
    assert "first" in lines[0]
    assert "second" in lines[1]


# ---------------------------------------------------------------------------
# _sentence_boundaries
# ---------------------------------------------------------------------------

def test_sentence_boundaries_empty():
    assert _sentence_boundaries([]) == []


def test_sentence_boundaries_single_word():
    words = [{"start": 3.0, "end": 3.5}]
    assert _sentence_boundaries(words) == [3.0]


def test_sentence_boundaries_gap_exactly_at_threshold_included():
    words = [{"start": 0.0, "end": 1.0}, {"start": 1.0 + SENT_GAP, "end": 2.0}]
    assert _sentence_boundaries(words) == [0.0, 1.0 + SENT_GAP]


def test_sentence_boundaries_gap_just_under_threshold_excluded():
    words = [{"start": 0.0, "end": 1.0}, {"start": 1.0 + SENT_GAP - 0.01, "end": 2.0}]
    assert _sentence_boundaries(words) == [0.0]


def test_sentence_boundaries_overlapping_words_excluded():
    words = [{"start": 0.0, "end": 2.0}, {"start": 1.0, "end": 3.0}]
    assert _sentence_boundaries(words) == [0.0]


def test_sentence_boundaries_mixed_gaps():
    words = [
        {"start": 0.0, "end": 1.0},
        {"start": 1.1, "end": 1.5},  # small gap, not a boundary
        {"start": 1.5 + SENT_GAP, "end": 2.0},  # qualifies
    ]
    assert _sentence_boundaries(words) == [0.0, 1.5 + SENT_GAP]


# ---------------------------------------------------------------------------
# _snap_moment
# ---------------------------------------------------------------------------

def test_snap_moment_no_boundaries_falls_back_to_raw():
    start, end = _snap_moment(10.0, 40.0, [], [])
    # cushion applies on top of raw when nothing snaps, unless MIN_LEN check fails
    dur = end - start
    assert dur >= 30.0  # at least the raw span, possibly with cushion


def test_snap_moment_start_snaps_to_closest_boundary_below():
    boundaries = [5.0, 8.0, 100.0]
    start, end = _snap_moment(10.0, 40.0, boundaries, [])
    # nearest boundary <= raw_start within SNAP_WINDOW is 8.0 (closest, max of candidates)
    assert start <= 8.0 + 0.001


def test_snap_moment_end_snaps_to_closest_boundary_above():
    boundaries = [45.0, 60.0]
    start, end = _snap_moment(10.0, 42.0, [], [])
    # no boundaries near start (none provided within SNAP_WINDOW of 10.0) -> raw start used
    start2, end2 = _snap_moment(10.0, 42.0, boundaries, [])
    assert end2 >= 45.0 - 0.001


def test_snap_moment_silence_extends_end_within_tolerance():
    silences = [{"silence_start": 40.2, "silence_end": 43.0}]
    start, end = _snap_moment(10.0, 40.0, [], silences)
    # end (40.0) within 0.5 of silence_start (40.2) -> extend by SILENCE_EXTEND, capped
    assert end >= 40.0


def test_snap_moment_silence_outside_tolerance_no_extend():
    silences = [{"silence_start": 45.0, "silence_end": 48.0}]
    start_a, end_a = _snap_moment(10.0, 40.0, [], [])
    start_b, end_b = _snap_moment(10.0, 40.0, [], silences)
    assert end_a == end_b


def test_snap_moment_only_first_matching_silence_applies():
    silences = [
        {"silence_start": 40.1, "silence_end": 41.0},
        {"silence_start": 40.1, "silence_end": 100.0},
    ]
    start, end = _snap_moment(10.0, 40.0, [], silences)
    # Only the first silence in the list is checked (loop `break`): end extends to
    # min(40+SILENCE_EXTEND, 41.0) == 41.0, not capped by the second silence's larger
    # silence_end. CUSHION (5.0) is then added on both sides: start 10-5=5, end 41+5=46.
    assert (start, end) == (5.0, 46.0)


def test_snap_moment_room_negative_cushion_zero():
    # end - start already exceeds MAX_LEN, so room clamps to 0 and cushion is 0.
    start, end = _snap_moment(0.0, 130.0, [], [])
    assert (end - start) == 130.0


def test_snap_moment_video_end_clamp():
    start, end = _snap_moment(10.0, 20.0, [], [], video_end=22.0)
    assert end <= 22.0


def test_snap_moment_video_end_none_no_clamp():
    start, end = _snap_moment(10.0, 20.0, [], [], video_end=None)
    assert end > 20.0  # cushion still applied, no clamp


def test_snap_moment_final_length_exactly_min_len_kept():
    # Construct so padded span lands exactly at MIN_LEN with a huge video that won't clamp.
    raw_start, raw_end = 10.0, 10.0 + (MIN_LEN - 2)
    start, end = _snap_moment(raw_start, raw_end, [], [], video_end=1_000_000.0)
    assert (end - start) >= MIN_LEN - 1e-9


def test_snap_moment_below_min_len_falls_back_to_raw():
    raw_start, raw_end = 10.0, 10.5  # tiny span, cushion capped by room but still short
    start, end = _snap_moment(raw_start, raw_end, [], [], video_end=raw_end)
    # video_end clamp keeps padded_end <= raw_end, so padded span can't reach MIN_LEN
    assert (start, end) == (raw_start, raw_end)


# ---------------------------------------------------------------------------
# _dedup_overlap
# ---------------------------------------------------------------------------

def test_dedup_overlap_empty():
    assert _dedup_overlap([], 0.4) == ([], 0)


def test_dedup_overlap_single_kept():
    m = [_moment(0.0, 10.0, 0.9)]
    kept, dropped = _dedup_overlap(m, 0.4)
    assert kept == m
    assert dropped == 0


def test_dedup_overlap_non_overlapping_both_kept():
    m = [_moment(0.0, 10.0, 0.9), _moment(20.0, 30.0, 0.5)]
    kept, dropped = _dedup_overlap(m, 0.4)
    assert len(kept) == 2
    assert dropped == 0


def test_dedup_overlap_identical_spans_lower_score_dropped():
    high = _moment(0.0, 10.0, 0.9)
    low = _moment(0.0, 10.0, 0.5)
    kept, dropped = _dedup_overlap([low, high], 0.4)
    assert kept == [high]
    assert dropped == 1


def test_dedup_overlap_ratio_exactly_at_threshold_kept():
    a = _moment(0.0, 10.0, 0.9)
    # shared 4s over shorter (10s) = 0.4 == ratio, not > ratio -> kept
    b = _moment(6.0, 16.0, 0.5)
    kept, dropped = _dedup_overlap([a, b], 0.4)
    assert len(kept) == 2
    assert dropped == 0


def test_dedup_overlap_ratio_just_above_threshold_dropped():
    a = _moment(0.0, 10.0, 0.9)
    b = _moment(5.9, 15.9, 0.5)  # shared 4.1s / 10s = 0.41 > 0.4
    kept, dropped = _dedup_overlap([a, b], 0.4)
    assert len(kept) == 1
    assert dropped == 1


def test_dedup_overlap_zero_length_moment_not_flagged_duplicate():
    a = _moment(0.0, 10.0, 0.9)
    zero = _moment(5.0, 5.0, 0.5)
    kept, dropped = _dedup_overlap([a, zero], 0.4)
    assert len(kept) == 2
    assert dropped == 0


def test_dedup_overlap_cap_at_max_total_moments():
    moments = [_moment(i * 1000.0, i * 1000.0 + 10.0, 1.0 - i * 0.001) for i in range(MAX_TOTAL_MOMENTS + 5)]
    kept, dropped = _dedup_overlap(moments, 0.4)
    assert len(kept) == MAX_TOTAL_MOMENTS
    assert dropped == 5


# ---------------------------------------------------------------------------
# _coverage_metrics
# ---------------------------------------------------------------------------

def test_coverage_metrics_no_moments():
    assert _coverage_metrics([], 100.0) == (0.0, 100.0)


def test_coverage_metrics_duration_none():
    assert _coverage_metrics([_moment(0, 10, 1.0)], None) == (0.0, 0.0)


def test_coverage_metrics_duration_zero():
    assert _coverage_metrics([_moment(0, 10, 1.0)], 0) == (0.0, 0.0)


def test_coverage_metrics_single_moment_full_duration():
    result = _coverage_metrics([_moment(0.0, 100.0, 1.0)], 100.0)
    assert result == (100.0, 0.0)


def test_coverage_metrics_single_moment_partial():
    coverage, gap = _coverage_metrics([_moment(10.0, 20.0, 1.0)], 100.0)
    assert coverage == 10.0
    assert gap == 80.0  # tail gap (80) larger than head gap (10)


def test_coverage_metrics_two_non_overlapping():
    coverage, gap = _coverage_metrics([_moment(0.0, 10.0, 1.0), _moment(50.0, 60.0, 1.0)], 100.0)
    assert coverage == 20.0
    assert gap == 40.0  # tail gap (40) > between-gap (40)... verify exact largest


def test_coverage_metrics_two_overlapping_merged():
    coverage, gap = _coverage_metrics([_moment(0.0, 10.0, 1.0), _moment(5.0, 15.0, 1.0)], 100.0)
    assert coverage == 15.0  # merged span [0,15], not 20
    assert gap == 85.0


def test_coverage_metrics_no_head_gap_when_starts_at_zero():
    coverage, gap = _coverage_metrics([_moment(0.0, 50.0, 1.0)], 100.0)
    assert gap == 50.0  # only tail gap


def test_coverage_metrics_no_tail_gap_when_ends_at_duration():
    coverage, gap = _coverage_metrics([_moment(50.0, 100.0, 1.0)], 100.0)
    assert gap == 50.0  # only head gap


def test_coverage_metrics_rounds_to_one_decimal():
    coverage, gap = _coverage_metrics([_moment(0.0, 33.333, 1.0)], 100.0)
    assert coverage == round(100 * 33.333 / 100.0, 1)
