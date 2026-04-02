from __future__ import annotations

import json
import os
from pathlib import Path

from app.models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    RequestStatus,
    RequestType,
    User,
)
from app.worker import (
    _build_command,
    _build_content_report,
    _build_output_path,
    _fmt_ts,
    _initial_progress,
    _mask_word,
    _rollup_request,
    _strip_edition,
    _update_progress,
    _write_config_files,
)


# ── _strip_edition ──────────────────────────────────────────────────────────


def test_strip_edition_removes_tag():
    assert _strip_edition("Movie {edition-Directors}") == "Movie"


def test_strip_edition_no_tag():
    assert _strip_edition("Movie") == "Movie"


# ── _build_output_path ──────────────────────────────────────────────────────


def test_build_output_path_simple():
    result = _build_output_path("/mnt/media/Movie.mkv")
    assert result == "/mnt/media/Movie {edition-Clean}.mkv"


def test_build_output_path_existing_edition():
    result = _build_output_path("/mnt/media/Movie {edition-Directors}.mkv")
    assert result == "/mnt/media/Movie {edition-Clean}.mkv"


def test_build_output_path_preserves_extension():
    result = _build_output_path("/mnt/media/Video.mp4")
    assert result.endswith(".mp4")
    assert "{edition-Clean}" in result


# ── _mask_word ──────────────────────────────────────────────────────────────


def test_mask_word_single_char():
    assert _mask_word("a") == "*"


def test_mask_word_two_chars():
    assert _mask_word("ab") == "a*"


def test_mask_word_normal():
    assert _mask_word("fuck") == "f**k"


def test_mask_word_longer():
    assert _mask_word("bullshit") == "b******t"


# ── _fmt_ts ─────────────────────────────────────────────────────────────────


def test_fmt_ts_seconds():
    assert _fmt_ts(90) == "1:30"


def test_fmt_ts_minutes():
    assert _fmt_ts(61) == "1:01"


def test_fmt_ts_hours():
    assert _fmt_ts(3661) == "1:01:01"


def test_fmt_ts_zero():
    assert _fmt_ts(0) == "0:00"


# ── _build_command ──────────────────────────────────────────────────────────


def _make_job(**kw):
    defaults = dict(
        id=1,
        request_id=1,
        plex_key="/library/metadata/1",
        title="Test",
        input_file="/mnt/media/movie.mkv",
        output_file="/mnt/media/movie {edition-Clean}.mkv",
    )
    defaults.update(kw)
    return ConversionJob(**defaults)


def _make_req(**kw):
    defaults = dict(
        id=1,
        title="Test",
        request_type=RequestType.movie,
        filter_profanity=True,
        filter_nudity=False,
        filter_violence=False,
        use_whisper=False,
        use_bleep=True,
    )
    defaults.update(kw)
    return ConversionRequest(**defaults)


def test_build_command_profanity_only():
    job = _make_job()
    req = _make_req()
    cmd = _build_command(
        job, req, "/tmp/prof.json", "/tmp/nud.json", "/tmp/viol.json", "cleanmedia"
    )
    assert cmd[0] == "cleanmedia"
    assert cmd[1] == "process"
    assert "--config" in cmd
    assert "--nudity" not in cmd
    assert "--violence" not in cmd
    assert "--no-profanity" not in cmd
    assert "--bleep" in cmd


def test_build_command_nudity_enabled():
    job = _make_job()
    req = _make_req(filter_nudity=True)
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia"
    )
    assert "--nudity" in cmd
    assert "--nudity-config" in cmd


def test_build_command_violence_enabled():
    job = _make_job()
    req = _make_req(filter_violence=True)
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia"
    )
    assert "--violence" in cmd
    assert "--violence-config" in cmd


def test_build_command_no_profanity():
    job = _make_job()
    req = _make_req(filter_profanity=False)
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia"
    )
    assert "--no-profanity" in cmd


def test_build_command_whisper():
    job = _make_job()
    req = _make_req(use_whisper=True)
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia"
    )
    assert "--whisper" in cmd


def test_build_command_audio_track():
    job = _make_job()
    req = _make_req(audio_stream_index=2)
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia"
    )
    assert "--audio-track" in cmd
    idx = cmd.index("--audio-track")
    assert cmd[idx + 1] == "2"


def test_build_command_resume():
    job = _make_job()
    req = _make_req()
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia", resume=True
    )
    assert "--resume" in cmd


def test_build_command_output():
    job = _make_job()
    req = _make_req()
    cmd = _build_command(
        job, req, "/tmp/p.json", "/tmp/n.json", "/tmp/v.json", "cleanmedia"
    )
    assert cmd[-2] == "--output"
    assert cmd[-1] == job.output_file


# ── _write_config_files ─────────────────────────────────────────────────────


def test_write_config_files_global_defaults(db_session):
    prof_path, nud_path, viol_path = _write_config_files(db_session)
    try:
        prof = json.loads(Path(prof_path).read_text())
        assert "words" in prof
        assert "fuck" in prof["words"]
        assert prof["padding_ms"] == 200

        nud = json.loads(Path(nud_path).read_text())
        assert nud["confidence_threshold"] == 0.7
        assert "FEMALE_BREAST_EXPOSED" in nud["enabled_categories"]

        viol = json.loads(Path(viol_path).read_text())
        assert viol["confidence_threshold"] == 0.5
    finally:
        os.unlink(prof_path)
        os.unlink(nud_path)
        os.unlink(viol_path)


def test_write_config_files_per_request_overrides(db_session):
    req = ConversionRequest(
        title="Override Test",
        request_type=RequestType.movie,
        nudity_confidence=0.9,
        profanity_padding_ms=500,
        violence_confidence=0.8,
    )
    prof_path, nud_path, viol_path = _write_config_files(db_session, req)
    try:
        prof = json.loads(Path(prof_path).read_text())
        assert prof["padding_ms"] == 500

        nud = json.loads(Path(nud_path).read_text())
        assert nud["confidence_threshold"] == 0.9

        viol = json.loads(Path(viol_path).read_text())
        assert viol["confidence_threshold"] == 0.8
    finally:
        os.unlink(prof_path)
        os.unlink(nud_path)
        os.unlink(viol_path)


def test_write_config_files_extra_words_merged(db_session):
    req = ConversionRequest(
        title="Merge Test",
        request_type=RequestType.movie,
        profanity_extra_words_json=json.dumps(["heck", "dang"]),
    )
    prof_path, nud_path, viol_path = _write_config_files(db_session, req)
    try:
        prof = json.loads(Path(prof_path).read_text())
        assert "heck" in prof["words"]
        assert "dang" in prof["words"]
        assert "fuck" in prof["words"]  # global words still present
    finally:
        os.unlink(prof_path)
        os.unlink(nud_path)
        os.unlink(viol_path)


# ── _update_progress ────────────────────────────────────────────────────────


def test_update_progress_profanity_scan():
    progress = _initial_progress()
    changed = _update_progress("--- Profanity scan ---", progress)
    assert changed is True
    assert progress["phase"] == "profanity"
    assert progress["profanity"]["status"] == "running"


def test_update_progress_nudity_scan():
    progress = _initial_progress()
    changed = _update_progress("--- Nudity scan ---", progress)
    assert changed is True
    assert progress["phase"] == "nudity"


def test_update_progress_violence_scan():
    progress = _initial_progress()
    changed = _update_progress("--- Violence scan ---", progress)
    assert changed is True
    assert progress["phase"] == "violence"


def test_update_progress_render():
    progress = _initial_progress()
    changed = _update_progress("Rendering output.mkv → clean.mkv", progress)
    assert changed is True
    assert progress["phase"] == "render"
    assert progress["render"]["status"] == "running"


def test_update_progress_done():
    progress = _initial_progress()
    changed = _update_progress("Done.", progress)
    assert changed is True
    assert progress["phase"] == "done"
    assert progress["render"]["pct"] == 100


def test_update_progress_nudity_extract():
    progress = _initial_progress()
    progress["nudity"]["status"] = "running"
    changed = _update_progress("PROGRESS:nudity_extract:50/100", progress)
    assert changed is True
    assert progress["nudity"]["pct"] == 25  # 50//2


def test_update_progress_render_percent():
    progress = _initial_progress()
    progress["render"]["status"] = "running"
    changed = _update_progress("PROGRESS:render:75/100", progress)
    assert changed is True
    assert progress["render"]["pct"] == 75


def test_update_progress_captures_interval():
    progress = _initial_progress()
    progress["phase"] = "profanity"
    captured = {}
    _update_progress("    [12.300s – 13.100s]  fuck, damn", progress, captured)
    assert "intervals" in captured
    assert len(captured["intervals"]) == 1
    assert captured["intervals"][0]["start"] == 12.3
    assert "fuck" in captured["intervals"][0]["matched_words"]


def test_update_progress_no_change():
    progress = _initial_progress()
    changed = _update_progress("some random log line", progress)
    assert changed is False


# ── _build_content_report ───────────────────────────────────────────────────


def test_build_content_report_no_sidecar(tmp_path):
    result = _build_content_report(str(tmp_path / "movie.mkv"))
    assert result is None


def test_build_content_report_with_data(tmp_path):
    input_file = tmp_path / "movie.mkv"
    input_file.touch()
    sidecar = tmp_path / "movie.cleanmedia.json"
    sidecar.write_text(
        json.dumps(
            {
                "intervals": [
                    {
                        "start": 5.0,
                        "end": 5.5,
                        "matched_text": "",
                        "matched_words": ["damn"],
                    },
                    {
                        "start": 1.0,
                        "end": 1.5,
                        "matched_text": "",
                        "matched_words": ["shit"],
                    },
                ],
                "nudity_intervals": [
                    {
                        "start": 3.0,
                        "end": 4.0,
                        "matched_words": ["FEMALE_BREAST_EXPOSED"],
                    },
                ],
                "violence_intervals": [
                    {"start": 10.0, "end": 11.0, "matched_words": ["GORE_BLOODSHED"]},
                ],
            }
        )
    )
    result = _build_content_report(str(input_file))
    assert result is not None
    entries = json.loads(result)
    assert len(entries) == 4
    # Should be sorted by start time (1.0, 3.0, 5.0, 10.0)
    types = [e["type"] for e in entries]
    assert types == ["profanity", "nudity", "profanity", "violence"]


# ── _rollup_request ────────────────────────────────────────────────────────


def _make_request_with_jobs(db_session, job_statuses):
    user = User(username=f"rollup_user_{id(job_statuses)}", is_approved=True)
    db_session.add(user)
    db_session.flush()
    req = ConversionRequest(
        user_id=user.id,
        title="Rollup Test",
        request_type=RequestType.season,
    )
    db_session.add(req)
    db_session.flush()
    for i, st in enumerate(job_statuses):
        job = ConversionJob(
            request_id=req.id,
            plex_key=f"/library/metadata/{i}",
            title=f"Episode {i}",
            input_file=f"/mnt/media/ep{i}.mkv",
            status=st,
        )
        db_session.add(job)
    db_session.flush()
    return req


def test_rollup_request_all_completed(db_session):
    req = _make_request_with_jobs(
        db_session, [JobStatus.completed, JobStatus.completed]
    )
    _rollup_request(db_session, req.id)
    db_session.refresh(req)
    assert req.status == RequestStatus.complete


def test_rollup_request_some_completed(db_session):
    req = _make_request_with_jobs(db_session, [JobStatus.completed, JobStatus.failed])
    _rollup_request(db_session, req.id)
    db_session.refresh(req)
    assert req.status == RequestStatus.partially_complete


def test_rollup_request_all_failed(db_session):
    req = _make_request_with_jobs(db_session, [JobStatus.failed, JobStatus.skipped])
    _rollup_request(db_session, req.id)
    db_session.refresh(req)
    assert req.status == RequestStatus.failed


def test_rollup_request_some_queued(db_session):
    req = _make_request_with_jobs(db_session, [JobStatus.completed, JobStatus.queued])
    _rollup_request(db_session, req.id)
    db_session.refresh(req)
    assert req.status == RequestStatus.queued


def test_rollup_request_already_exists_counts_as_complete(db_session):
    req = _make_request_with_jobs(
        db_session, [JobStatus.already_exists, JobStatus.completed]
    )
    _rollup_request(db_session, req.id)
    db_session.refresh(req)
    assert req.status == RequestStatus.complete
