from app.tasks.render import (
    ALLOWED_FORMATS,
    CAPTION_GAP_SEC,
    CAPTION_MAX_CHARS,
    CAPTION_MAX_SEC,
    CAPTION_STYLE,
    FORMATS,
    ORIGINAL_FORMAT,
    _group_into_cues,
    _parse_ffmpeg_stats,
    _should_end_cue,
    _srt_timestamp,
    _units,
    _video_filter,
    _words_in_window,
    _write_srt,
)


# ---------------------------------------------------------------------------
# _units
# ---------------------------------------------------------------------------

def test_units_zero():
    assert _units(0) == "0.0"


def test_units_typical():
    assert _units(0.05) == "14.4"


def test_units_half_rounding():
    # 288 * 0.02 = 5.76 -> rounds to 5.8, not truncated to 5.7
    assert _units(0.02) == "5.8"


def test_units_greater_than_one():
    assert _units(1.5) == "432.0"


# ---------------------------------------------------------------------------
# _srt_timestamp
# ---------------------------------------------------------------------------

def test_srt_timestamp_zero():
    assert _srt_timestamp(0) == "00:00:00,000"


def test_srt_timestamp_negative_clamped():
    assert _srt_timestamp(-5) == "00:00:00,000"


def test_srt_timestamp_submillisecond_rounds():
    # total_ms = int(round(seconds * 1000)); pin whatever IEEE-754 float rounding
    # actually produces for a value that isn't exactly representable in binary.
    expected_ms = int(round(1.9995 * 1000))
    assert expected_ms == 2000
    assert _srt_timestamp(1.9995) == "00:00:02,000"


def test_srt_timestamp_hour_boundary():
    assert _srt_timestamp(3600) == "01:00:00,000"


def test_srt_timestamp_minute_boundary():
    assert _srt_timestamp(60) == "00:01:00,000"


def test_srt_timestamp_multi_hour():
    assert _srt_timestamp(36661.234) == "10:11:01,234"


def test_srt_timestamp_ms_rolls_into_next_second():
    assert _srt_timestamp(0.9996) == "00:00:01,000"


# ---------------------------------------------------------------------------
# _words_in_window
# ---------------------------------------------------------------------------

def test_words_in_window_empty():
    assert _words_in_window([], 0, 10) == []


def test_words_in_window_word_fully_before():
    words = [{"word": "hi", "start": 0.0, "end": 1.0}]
    assert _words_in_window(words, 2.0, 5.0) == []


def test_words_in_window_word_fully_after():
    words = [{"word": "hi", "start": 6.0, "end": 7.0}]
    assert _words_in_window(words, 2.0, 5.0) == []


def test_words_in_window_word_ends_exactly_at_start_excluded():
    words = [{"word": "hi", "start": 1.0, "end": 2.0}]
    assert _words_in_window(words, 2.0, 5.0) == []


def test_words_in_window_word_starts_exactly_at_end_excluded():
    words = [{"word": "hi", "start": 5.0, "end": 6.0}]
    assert _words_in_window(words, 2.0, 5.0) == []


def test_words_in_window_word_starts_exactly_at_window_start():
    words = [{"word": "hi", "start": 2.0, "end": 3.0}]
    result = _words_in_window(words, 2.0, 5.0)
    assert result == [{"text": "hi", "start": 0.0, "end": 1.0}]


def test_words_in_window_word_ends_exactly_at_window_end():
    words = [{"word": "hi", "start": 4.0, "end": 5.0}]
    result = _words_in_window(words, 2.0, 5.0)
    assert result == [{"text": "hi", "start": 2.0, "end": 3.0}]


def test_words_in_window_straddles_start():
    words = [{"word": "hi", "start": 1.0, "end": 3.0}]
    result = _words_in_window(words, 2.0, 5.0)
    assert result == [{"text": "hi", "start": 0.0, "end": 1.0}]


def test_words_in_window_straddles_end():
    words = [{"word": "hi", "start": 4.0, "end": 6.0}]
    result = _words_in_window(words, 2.0, 5.0)
    assert result == [{"text": "hi", "start": 2.0, "end": 3.0}]


def test_words_in_window_fully_inside():
    words = [{"word": "hi", "start": 2.5, "end": 3.5}]
    result = _words_in_window(words, 2.0, 5.0)
    assert result == [{"text": "hi", "start": 0.5, "end": 1.5}]


def test_words_in_window_zero_width_window():
    words = [{"word": "hi", "start": 2.0, "end": 3.0}]
    assert _words_in_window(words, 3.0, 3.0) == []


def test_words_in_window_strips_whitespace():
    words = [{"word": "  hi  ", "start": 2.0, "end": 3.0}]
    result = _words_in_window(words, 0.0, 5.0)
    assert result[0]["text"] == "hi"


def test_words_in_window_preserves_order():
    words = [
        {"word": "a", "start": 1.0, "end": 1.5},
        {"word": "b", "start": 2.0, "end": 2.5},
        {"word": "c", "start": 3.0, "end": 3.5},
    ]
    result = _words_in_window(words, 0.0, 10.0)
    assert [w["text"] for w in result] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# _should_end_cue
# ---------------------------------------------------------------------------

def test_should_end_cue_chars_exactly_at_limit_no_break():
    current = [{"text": "x" * (CAPTION_MAX_CHARS - 2), "start": 0.0, "end": 0.5}]
    word = {"text": "y", "start": 0.6, "end": 0.7}
    # pending = current_text + " " + word -> length == CAPTION_MAX_CHARS
    assert len(current[0]["text"]) + 1 + len(word["text"]) == CAPTION_MAX_CHARS
    assert _should_end_cue(current, word) is False


def test_should_end_cue_chars_over_limit_breaks():
    current = [{"text": "x" * (CAPTION_MAX_CHARS - 1), "start": 0.0, "end": 0.5}]
    word = {"text": "y", "start": 0.6, "end": 0.7}
    assert len(current[0]["text"]) + 1 + len(word["text"]) == CAPTION_MAX_CHARS + 1
    assert _should_end_cue(current, word) is True


def test_should_end_cue_duration_exactly_at_limit_no_break():
    # current[-1]["end"] kept close to word["start"] so the gap check doesn't also fire;
    # only the duration check (word["end"] - current[0]["start"]) is exercised here.
    current = [{"text": "hi", "start": 0.0, "end": CAPTION_MAX_SEC - 0.5}]
    word = {"text": "yo", "start": CAPTION_MAX_SEC - 0.1, "end": CAPTION_MAX_SEC}
    assert _should_end_cue(current, word) is False


def test_should_end_cue_duration_over_limit_breaks():
    current = [{"text": "hi", "start": 0.0, "end": 0.1}]
    word = {"text": "yo", "start": CAPTION_MAX_SEC, "end": CAPTION_MAX_SEC + 0.1}
    assert _should_end_cue(current, word) is True


def test_should_end_cue_gap_exactly_at_limit_breaks():
    current = [{"text": "hi", "start": 0.0, "end": 1.0}]
    word = {"text": "yo", "start": 1.0 + CAPTION_GAP_SEC, "end": 1.5 + CAPTION_GAP_SEC}
    assert _should_end_cue(current, word) is True


def test_should_end_cue_gap_just_under_limit_no_break():
    current = [{"text": "hi", "start": 0.0, "end": 1.0}]
    word = {"text": "yo", "start": 1.0 + CAPTION_GAP_SEC - 0.01, "end": 1.5}
    assert _should_end_cue(current, word) is False


def test_should_end_cue_no_condition_met():
    current = [{"text": "hi", "start": 0.0, "end": 0.3}]
    word = {"text": "yo", "start": 0.35, "end": 0.6}
    assert _should_end_cue(current, word) is False


def test_should_end_cue_multiple_conditions_still_true():
    current = [{"text": "x" * CAPTION_MAX_CHARS, "start": 0.0, "end": CAPTION_MAX_SEC + 1}]
    word = {"text": "y", "start": CAPTION_MAX_SEC + 5, "end": CAPTION_MAX_SEC + 5.5}
    assert _should_end_cue(current, word) is True


# ---------------------------------------------------------------------------
# _group_into_cues
# ---------------------------------------------------------------------------

def test_group_into_cues_empty():
    assert _group_into_cues([]) == []


def test_group_into_cues_single_word():
    words = [{"text": "hi", "start": 0.0, "end": 0.5}]
    assert _group_into_cues(words) == [words]


def test_group_into_cues_merges_when_no_break():
    words = [
        {"text": "hi", "start": 0.0, "end": 0.5},
        {"text": "there", "start": 0.6, "end": 1.0},
    ]
    assert _group_into_cues(words) == [words]


def test_group_into_cues_breaks_on_chars():
    words = [
        {"text": "x" * (CAPTION_MAX_CHARS - 2), "start": 0.0, "end": 0.5},
        {"text": "yy", "start": 0.6, "end": 0.7},
    ]
    result = _group_into_cues(words)
    assert len(result) == 2
    assert result[0] == [words[0]]
    assert result[1] == [words[1]]


def test_group_into_cues_breaks_on_duration():
    words = [
        {"text": "hi", "start": 0.0, "end": 0.1},
        {"text": "yo", "start": CAPTION_MAX_SEC + 1, "end": CAPTION_MAX_SEC + 1.5},
    ]
    result = _group_into_cues(words)
    assert len(result) == 2


def test_group_into_cues_breaks_on_gap():
    words = [
        {"text": "hi", "start": 0.0, "end": 1.0},
        {"text": "yo", "start": 1.0 + CAPTION_GAP_SEC, "end": 2.0 + CAPTION_GAP_SEC},
    ]
    result = _group_into_cues(words)
    assert len(result) == 2


def test_group_into_cues_multiple_groups():
    words = [
        {"text": "a", "start": 0.0, "end": 0.2},
        {"text": "b", "start": 0.3, "end": 0.5},
        {"text": "c", "start": 0.5 + CAPTION_GAP_SEC, "end": 1.0 + CAPTION_GAP_SEC},
        {"text": "d", "start": 1.1 + CAPTION_GAP_SEC, "end": 1.3 + CAPTION_GAP_SEC},
        {"text": "e", "start": 1.3 + 2 * CAPTION_GAP_SEC, "end": 1.5 + 2 * CAPTION_GAP_SEC},
    ]
    result = _group_into_cues(words)
    assert len(result) == 3
    assert [w["text"] for w in result[0]] == ["a", "b"]
    assert [w["text"] for w in result[1]] == ["c", "d"]
    assert [w["text"] for w in result[2]] == ["e"]


def test_group_into_cues_trailing_partial_group_appended():
    words = [
        {"text": "a", "start": 0.0, "end": 0.2},
        {"text": "b", "start": 0.3, "end": 0.5},
        {"text": "c", "start": 0.5 + CAPTION_GAP_SEC, "end": 1.0 + CAPTION_GAP_SEC},
    ]
    result = _group_into_cues(words)
    assert result[-1] == [words[2]]


# ---------------------------------------------------------------------------
# _write_srt
# ---------------------------------------------------------------------------

def test_write_srt_single_cue(tmp_path):
    cues = [[{"text": "hello", "start": 0.0, "end": 1.5}]]
    path = tmp_path / "out.srt"
    _write_srt(cues, str(path))
    content = path.read_text(encoding="utf-8")
    assert content == "1\n00:00:00,000 --> 00:00:01,500\nhello\n"


def test_write_srt_multiple_cues_sequential_indices(tmp_path):
    cues = [
        [{"text": "one", "start": 0.0, "end": 1.0}],
        [{"text": "two", "start": 1.5, "end": 2.5}],
    ]
    path = tmp_path / "out.srt"
    _write_srt(cues, str(path))
    content = path.read_text(encoding="utf-8")
    blocks = content.split("\n\n")
    assert blocks[0].startswith("1\n")
    assert blocks[1].startswith("2\n")


def test_write_srt_cue_text_joined_with_spaces(tmp_path):
    cues = [[
        {"text": "hello", "start": 0.0, "end": 0.5},
        {"text": "world", "start": 0.5, "end": 1.0},
    ]]
    path = tmp_path / "out.srt"
    _write_srt(cues, str(path))
    content = path.read_text(encoding="utf-8")
    assert "hello world" in content


def test_write_srt_blocks_separated_by_one_blank_line(tmp_path):
    cues = [
        [{"text": "one", "start": 0.0, "end": 1.0}],
        [{"text": "two", "start": 1.5, "end": 2.5}],
    ]
    path = tmp_path / "out.srt"
    _write_srt(cues, str(path))
    content = path.read_text(encoding="utf-8")
    expected = (
        "1\n00:00:00,000 --> 00:00:01,000\none\n"
        "\n"
        "2\n00:00:01,500 --> 00:00:02,500\ntwo\n"
    )
    assert content == expected


def test_write_srt_non_ascii_roundtrips(tmp_path):
    cues = [[{"text": "café — naïve", "start": 0.0, "end": 1.0}]]
    path = tmp_path / "out.srt"
    _write_srt(cues, str(path))
    content = path.read_text(encoding="utf-8")
    assert "café — naïve" in content


# ---------------------------------------------------------------------------
# _video_filter
# ---------------------------------------------------------------------------

def test_video_filter_original_format_no_captions():
    result = _video_filter(None, None, ORIGINAL_FORMAT)
    assert result == "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def test_video_filter_9_16():
    width, height = FORMATS["9:16"]
    result = _video_filter(None, None, "9:16")
    assert result == (
        f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})',"
        f"scale={width}:{height}"
    )


def test_video_filter_1_1():
    width, height = FORMATS["1:1"]
    result = _video_filter(None, None, "1:1")
    assert result == (
        f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})',"
        f"scale={width}:{height}"
    )


def test_video_filter_16_9():
    width, height = FORMATS["16:9"]
    result = _video_filter(None, None, "16:9")
    assert result == (
        f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})',"
        f"scale={width}:{height}"
    )


def test_video_filter_unknown_format_raises():
    try:
        _video_filter(None, None, "4:3")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "4:3" in str(e)
        for fmt in sorted(ALLOWED_FORMATS):
            assert fmt in str(e)


def test_video_filter_with_captions_appends_subtitles_stage():
    result = _video_filter(None, "captions.srt", ORIGINAL_FORMAT)
    assert result == (
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        f"subtitles=captions.srt:fontsdir=.:force_style='{CAPTION_STYLE}'"
    )


def test_video_filter_without_captions_no_subtitles_stage():
    result = _video_filter(None, None, ORIGINAL_FORMAT)
    assert "subtitles=" not in result


def test_video_filter_crop_param_is_ignored():
    # NOTE: `_video_filter` accepts a `crop` argument and its docstring claims "An
    # explicit `crop` from the editor wins", but the function body never reads `crop` —
    # it's a silent no-op today. This test pins the current (buggy) behavior rather
    # than the documented one; a manual crop from the editor has no effect on output.
    with_crop = _video_filter({"x": 10, "y": 20, "w": 100, "h": 100}, None, "9:16")
    without_crop = _video_filter(None, None, "9:16")
    assert with_crop == without_crop


# ---------------------------------------------------------------------------
# _parse_ffmpeg_stats
# ---------------------------------------------------------------------------

def test_parse_ffmpeg_stats_empty():
    assert _parse_ffmpeg_stats("") == {}


def test_parse_ffmpeg_stats_speed_only():
    stats = _parse_ffmpeg_stats("frame=100 speed=1.23x")
    assert stats == {"encode_speed": 1.23}


def test_parse_ffmpeg_stats_speed_last_wins():
    stats = _parse_ffmpeg_stats("speed=1.0x ... speed=2.5x")
    assert stats["encode_speed"] == 2.5


def test_parse_ffmpeg_stats_fps_only():
    stats = _parse_ffmpeg_stats("fps=30.0 frame=1")
    assert stats == {"encode_fps": 30.0}


def test_parse_ffmpeg_stats_fps_last_wins():
    stats = _parse_ffmpeg_stats("fps=30.0 ... fps=59.9")
    assert stats["encode_fps"] == 59.9


def test_parse_ffmpeg_stats_benchmark_full():
    stderr = "bench: utime=1.500s stime=0.500s rtime=2.000s"
    stats = _parse_ffmpeg_stats(stderr)
    assert stats["ffmpeg_cpu_s"] == 2.0
    assert stats["ffmpeg_wall_s"] == 2.0
    assert stats["cpu_fraction"] == 1.0


def test_parse_ffmpeg_stats_benchmark_rtime_zero_no_cpu_fraction():
    stderr = "bench: utime=0.000s stime=0.000s rtime=0.000s"
    stats = _parse_ffmpeg_stats(stderr)
    assert "cpu_fraction" not in stats
    assert stats["ffmpeg_cpu_s"] == 0.0
    assert stats["ffmpeg_wall_s"] == 0.0


def test_parse_ffmpeg_stats_benchmark_malformed_no_match():
    stderr = "bench: utime=1.5s stime=0.5s"  # missing rtime
    stats = _parse_ffmpeg_stats(stderr)
    assert "ffmpeg_cpu_s" not in stats
    assert "ffmpeg_wall_s" not in stats
    assert "cpu_fraction" not in stats


def test_parse_ffmpeg_stats_all_signals_present():
    stderr = "frame=100 fps=30.0 speed=1.5x\nbench: utime=1.0s stime=1.0s rtime=2.0s"
    stats = _parse_ffmpeg_stats(stderr)
    assert stats == {
        "encode_speed": 1.5,
        "encode_fps": 30.0,
        "ffmpeg_cpu_s": 2.0,
        "ffmpeg_wall_s": 2.0,
        "cpu_fraction": 1.0,
    }


def test_parse_ffmpeg_stats_unrelated_noise():
    assert _parse_ffmpeg_stats("some random ffmpeg log line with no stats") == {}
