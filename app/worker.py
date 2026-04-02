from __future__ import annotations

import json as _json
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import settings
from .database import SessionLocal
from .models import ConversionJob, ConversionRequest, JobStatus, RequestStatus, RequestType

# Maps job_id → subprocess.Popen for running jobs so they can be cancelled.
_running_procs: dict[int, subprocess.Popen] = {}


def _strip_edition(stem: str) -> str:
    return re.sub(r'\s*\{edition-[^}]+\}', '', stem).rstrip()


def _get_setting(db, key: str) -> str:
    """Read a single app setting from the DB."""
    from . import app_settings
    return app_settings.get(db, key)


def _write_config_files(db, req: ConversionRequest | None = None) -> tuple[str, str, str]:
    """Write temp profanity.json, nudity.json, and violence.json from DB settings.

    Per-request overrides on *req* take precedence over global settings.
    Returns (prof_path, nud_path, viol_path).
    """
    from . import app_settings

    # Build profanity config: merge per-request extras on top of global lists
    words = _json.loads(app_settings.get(db, "profanity_words"))
    phrases = _json.loads(app_settings.get(db, "profanity_phrases"))
    if req and req.profanity_extra_words_json:
        extra = _json.loads(req.profanity_extra_words_json)
        words = list(dict.fromkeys(words + extra))  # deduplicate, preserve order
    if req and req.profanity_extra_phrases_json:
        extra = _json.loads(req.profanity_extra_phrases_json)
        phrases = list(dict.fromkeys(phrases + extra))

    prof = {
        "words": words,
        "phrases": phrases,
        "padding_ms": req.profanity_padding_ms if req and req.profanity_padding_ms is not None else int(app_settings.get(db, "profanity_padding_ms")),
        "whisper_model": req.whisper_model if req and req.whisper_model else app_settings.get(db, "whisper_model"),
    }

    # Build nudity config: per-request overrides win over global settings
    if req and req.nudity_categories_json is not None:
        categories = _json.loads(req.nudity_categories_json)
    else:
        categories = _json.loads(app_settings.get(db, "nudity_categories"))

    nud = {
        "enabled_categories": categories,
        "confidence_threshold": req.nudity_confidence if req and req.nudity_confidence is not None else float(app_settings.get(db, "nudity_confidence")),
        "sample_fps": req.nudity_sample_fps if req and req.nudity_sample_fps is not None else float(app_settings.get(db, "nudity_sample_fps")),
        "padding_ms": req.nudity_padding_ms if req and req.nudity_padding_ms is not None else int(app_settings.get(db, "nudity_padding_ms")),
        "scene_merge_gap_ms": req.nudity_scene_merge_gap_ms if req and req.nudity_scene_merge_gap_ms is not None else int(app_settings.get(db, "nudity_scene_merge_gap_ms")),
        "frame_width": 640,
        # Multi-model pipeline settings
        "detectors": _json.loads(req.nudity_detectors_json) if req and req.nudity_detectors_json else _json.loads(app_settings.get(db, "nudity_detectors")),
        "ensemble_strategy": req.nudity_ensemble_strategy if req and req.nudity_ensemble_strategy else app_settings.get(db, "nudity_ensemble_strategy"),
        "temporal_enabled": (req.nudity_temporal_enabled if req and req.nudity_temporal_enabled is not None else app_settings.get(db, "nudity_temporal_enabled").lower() == "true"),
        "temporal_window": req.nudity_temporal_window if req and req.nudity_temporal_window is not None else int(app_settings.get(db, "nudity_temporal_window")),
        "temporal_min_flagged": req.nudity_temporal_min_flagged if req and req.nudity_temporal_min_flagged is not None else int(app_settings.get(db, "nudity_temporal_min_flagged")),
        "extraction_mode": req.nudity_extraction_mode if req and req.nudity_extraction_mode else app_settings.get(db, "nudity_extraction_mode"),
        "device": app_settings.get(db, "nudity_device"),
    }
    prof_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="cleanarr_prof_", delete=False)
    prof_path.write(_json.dumps(prof))
    prof_path.close()
    nud_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="cleanarr_nud_", delete=False)
    nud_path.write(_json.dumps(nud))
    nud_path.close()

    # Build violence config
    if req and req.violence_categories_json is not None:
        viol_categories = _json.loads(req.violence_categories_json)
    else:
        viol_categories = _json.loads(app_settings.get(db, "violence_categories"))

    viol = {
        "enabled_categories": viol_categories,
        "confidence_threshold": req.violence_confidence if req and req.violence_confidence is not None else float(app_settings.get(db, "violence_confidence")),
        "sample_fps": req.violence_sample_fps if req and req.violence_sample_fps is not None else float(app_settings.get(db, "violence_sample_fps")),
        "padding_ms": req.violence_padding_ms if req and req.violence_padding_ms is not None else int(app_settings.get(db, "violence_padding_ms")),
        "scene_merge_gap_ms": req.violence_scene_merge_gap_ms if req and req.violence_scene_merge_gap_ms is not None else int(app_settings.get(db, "violence_scene_merge_gap_ms")),
        "frame_width": 640,
        "detectors": _json.loads(req.violence_detectors_json) if req and req.violence_detectors_json else _json.loads(app_settings.get(db, "violence_detectors")),
        "ensemble_strategy": req.violence_ensemble_strategy if req and req.violence_ensemble_strategy else app_settings.get(db, "violence_ensemble_strategy"),
        "temporal_enabled": (req.violence_temporal_enabled if req and req.violence_temporal_enabled is not None else app_settings.get(db, "violence_temporal_enabled").lower() == "true"),
        "temporal_window": req.violence_temporal_window if req and req.violence_temporal_window is not None else int(app_settings.get(db, "violence_temporal_window")),
        "temporal_min_flagged": req.violence_temporal_min_flagged if req and req.violence_temporal_min_flagged is not None else int(app_settings.get(db, "violence_temporal_min_flagged")),
        "extraction_mode": req.violence_extraction_mode if req and req.violence_extraction_mode else app_settings.get(db, "violence_extraction_mode"),
        "device": app_settings.get(db, "violence_device"),
    }
    viol_path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="cleanarr_viol_", delete=False)
    viol_path.write(_json.dumps(viol))
    viol_path.close()
    return prof_path.name, nud_path.name, viol_path.name


def _build_command(
    job: ConversionJob,
    req: ConversionRequest,
    prof_cfg: str,
    nud_cfg: str,
    viol_cfg: str,
    cleanmedia_bin: str,
    resume: bool = False,
) -> list[str]:
    cmd = [cleanmedia_bin, "process", job.input_file]
    cmd.extend(["--config", prof_cfg])
    if req.use_whisper:
        cmd.append("--whisper")
    if req.use_bleep:
        cmd.append("--bleep")
    if req.filter_nudity:
        cmd.extend(["--nudity", "--nudity-config", nud_cfg])
    if req.filter_violence:
        cmd.extend(["--violence", "--violence-config", viol_cfg])
    if not req.filter_profanity:
        cmd.append("--no-profanity")
    if req.audio_stream_index is not None:
        cmd.extend(["--audio-track", str(req.audio_stream_index)])
    if resume:
        cmd.append("--resume")
    cmd.extend(["--output", job.output_file])
    return cmd


def _build_output_path(input_path: str) -> str:
    p = Path(input_path)
    clean_stem = _strip_edition(p.stem)
    return str(p.parent / (clean_stem + " {edition-Clean}" + p.suffix))


def _mask_word(word: str) -> str:
    if len(word) <= 2:
        return word[0] + '*' if len(word) == 2 else '*'
    return word[0] + '*' * (len(word) - 2) + word[-1]


_NUDITY_LABELS: dict[str, str] = {
    "FEMALE_BREAST_EXPOSED": "Female breast exposed",
    "FEMALE_GENITALIA_EXPOSED": "Female genitalia exposed",
    "MALE_GENITALIA_EXPOSED": "Male genitalia exposed",
    "ANUS_EXPOSED": "Anus exposed",
    "BUTTOCKS_EXPOSED": "Buttocks exposed",
}

_VIOLENCE_LABELS: dict[str, str] = {
    "GORE_BLOODSHED": "Gore / bloodshed",
    "VIOLENCE_FIGHTING": "Violence / fighting",
}


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _build_content_report(input_path: str) -> str | None:
    sidecar = Path(input_path).with_suffix(".cleanmedia.json")
    if not sidecar.exists():
        return None
    try:
        data = _json.loads(sidecar.read_text())
    except Exception:
        return None
    entries: list[dict] = []
    for iv in data.get("intervals", []):
        words = iv.get("matched_words", [])
        entries.append({
            "start": iv["start"],
            "time": _fmt_ts(iv["start"]),
            "type": "profanity",
            "description": ", ".join(_mask_word(w) for w in words),
        })
    for iv in data.get("nudity_intervals", []):
        labels = iv.get("matched_words", [])
        entries.append({
            "start": iv["start"],
            "time": _fmt_ts(iv["start"]),
            "type": "nudity",
            "description": ", ".join(_NUDITY_LABELS.get(l, l) for l in labels),
        })
    for iv in data.get("violence_intervals", []):
        labels = iv.get("matched_words", [])
        entries.append({
            "start": iv["start"],
            "time": _fmt_ts(iv["start"]),
            "type": "violence",
            "description": ", ".join(_VIOLENCE_LABELS.get(l, l) for l in labels),
        })
    entries.sort(key=lambda e: e["start"])
    for e in entries:
        del e["start"]
    return _json.dumps(entries)


_TQDM_PCT_RE = re.compile(r"(\d+)%\|")
_INTERVAL_RE = re.compile(r"^\s+\[(\d+\.\d+)s\s*[–-]\s*(\d+\.\d+)s\]\s+(.+)$")


def _initial_progress() -> dict:
    return {
        "phase": "starting",
        "profanity": {"status": "pending", "pct": 0},
        "nudity": {"status": "pending", "current": 0, "total": 0, "pct": 0, "detail": ""},
        "violence": {"status": "pending", "current": 0, "total": 0, "pct": 0, "detail": ""},
        "render": {"status": "pending", "pct": 0},
    }


def _update_progress(line: str, progress: dict, captured_intervals: dict | None = None) -> bool:
    """Update progress dict from a log line. Returns True if changed.

    If *captured_intervals* is provided, profanity/nudity intervals parsed from
    the log are appended to it as a backup in case the sidecar fails to write.
    """
    # Capture interval lines like "    [12.300s – 13.100s]  fuck, damn"
    if captured_intervals is not None:
        m = _INTERVAL_RE.match(line)
        if m:
            phase = progress.get("phase", "")
            bucket = "intervals" if phase == "profanity" else "nudity_intervals" if phase == "nudity" else "violence_intervals" if phase == "violence" else None
            if bucket:
                captured_intervals.setdefault(bucket, [])
                captured_intervals[bucket].append({
                    "start": float(m.group(1)),
                    "end": float(m.group(2)),
                    "matched_text": "",
                    "matched_words": [w.strip() for w in m.group(3).split(",")],
                })

    if "--- Profanity scan ---" in line:
        progress["phase"] = "profanity"
        progress["profanity"]["status"] = "running"
    elif "--- Profanity scan skipped" in line:
        progress["profanity"]["status"] = "skipped"
    elif "Final profanity intervals" in line:
        progress["profanity"]["status"] = "complete"
    elif "--- Nudity scan ---" in line:
        progress["phase"] = "nudity"
        progress["nudity"]["status"] = "running"
    elif "Final blackout intervals after padding" in line:
        phase = progress.get("phase", "")
        if phase == "violence":
            progress["violence"]["status"] = "complete"
        else:
            progress["nudity"]["status"] = "complete"
    elif line.startswith("PROGRESS:nudity_extract:"):
        parts = line[len("PROGRESS:nudity_extract:"):].split("/")
        if len(parts) == 2 and parts[0].isdigit() and progress["nudity"]["status"] != "complete":
            new_pct = int(parts[0]) // 2  # extraction = 0–50%
            progress["nudity"]["pct"] = max(progress["nudity"].get("pct", 0), new_pct)
            progress["nudity"]["detail"] = "extracting frames"
            progress["nudity"]["status"] = "running"
    elif line.startswith("PROGRESS:nudity:"):
        parts = line[len("PROGRESS:nudity:"):].split("/")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and progress["nudity"]["status"] != "complete":
            progress["nudity"]["current"] = int(parts[0])
            progress["nudity"]["total"] = int(parts[1])
            analysis_pct = int(int(parts[0]) / int(parts[1]) * 50) if int(parts[1]) > 0 else 0
            new_pct = 50 + analysis_pct  # analysis = 50–100%
            progress["nudity"]["pct"] = max(progress["nudity"].get("pct", 0), new_pct)
            progress["nudity"]["detail"] = "analysing frames"
            progress["nudity"]["status"] = "running"
    elif "--- Violence scan ---" in line:
        progress["phase"] = "violence"
        progress["violence"]["status"] = "running"
    elif "--- Violence scan skipped" in line:
        progress["violence"]["status"] = "skipped"
    elif line.startswith("PROGRESS:violence_extract:"):
        parts = line[len("PROGRESS:violence_extract:"):].split("/")
        if len(parts) == 2 and parts[0].isdigit() and progress["violence"]["status"] != "complete":
            new_pct = int(parts[0]) // 2
            progress["violence"]["pct"] = max(progress["violence"].get("pct", 0), new_pct)
            progress["violence"]["detail"] = "extracting frames"
            progress["violence"]["status"] = "running"
    elif line.startswith("PROGRESS:violence:"):
        parts = line[len("PROGRESS:violence:"):].split("/")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() and progress["violence"]["status"] != "complete":
            progress["violence"]["current"] = int(parts[0])
            progress["violence"]["total"] = int(parts[1])
            analysis_pct = int(int(parts[0]) / int(parts[1]) * 50) if int(parts[1]) > 0 else 0
            new_pct = 50 + analysis_pct
            progress["violence"]["pct"] = max(progress["violence"].get("pct", 0), new_pct)
            progress["violence"]["detail"] = "analysing frames"
            progress["violence"]["status"] = "running"
    elif "Rendering " in line and "→" in line:
        progress["phase"] = "render"
        if progress["profanity"]["status"] == "pending":
            progress["profanity"]["status"] = "skipped"
        if progress["nudity"]["status"] == "pending":
            progress["nudity"]["status"] = "skipped"
        if progress["violence"]["status"] == "pending":
            progress["violence"]["status"] = "skipped"
        progress["render"]["status"] = "running"
    elif line.startswith("PROGRESS:render:"):
        parts = line[len("PROGRESS:render:"):].split("/")
        if len(parts) == 2 and parts[0].isdigit():
            progress["render"]["pct"] = int(parts[0])
            progress["render"]["status"] = "running"
    elif line.strip() == "Done." or line.startswith("\nDone."):
        progress["phase"] = "done"
        progress["render"]["status"] = "complete"
        progress["render"]["pct"] = 100
    else:
        return False
    return True


def _rollup_request(db, request_id: int) -> None:
    req = db.query(ConversionRequest).filter(ConversionRequest.id == request_id).first()
    if not req:
        return
    statuses = {j.status for j in req.jobs}
    if JobStatus.running in statuses or JobStatus.queued in statuses:
        req.status = RequestStatus.queued
    elif all(s in (JobStatus.completed, JobStatus.already_exists) for s in statuses):
        req.status = RequestStatus.complete
    elif JobStatus.completed in statuses or JobStatus.already_exists in statuses:
        req.status = RequestStatus.partially_complete
    else:
        req.status = RequestStatus.failed
    db.commit()


def _is_cancelled(job_id: int) -> bool:
    """Check if a running job was marked for cancellation (status set to skipped).

    Uses a separate DB session to avoid interfering with the main session.
    """
    check_db = SessionLocal()
    try:
        job = check_db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
        return job is not None and job.status == JobStatus.skipped
    finally:
        check_db.close()


def _cancel_watcher(job_id: int, proc: subprocess.Popen, stop_event: threading.Event) -> None:
    """Background thread that polls for cancellation and kills the process."""
    while not stop_event.is_set():
        stop_event.wait(timeout=3)  # check every 3 seconds
        if stop_event.is_set():
            return
        try:
            if _is_cancelled(job_id):
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return
        except Exception:
            pass


def _cleanup_job_files(job: ConversionJob) -> list[str]:
    """Remove output file and sidecar created by a cancelled/failed job. Returns list of removed paths."""
    removed: list[str] = []
    if job.output_file:
        out = Path(job.output_file)
        if out.exists():
            out.unlink()
            removed.append(str(out))
    # Remove cleanmedia sidecar (.cleanmedia.json) next to the input file
    sidecar = Path(job.input_file).with_suffix(".cleanmedia.json")
    if sidecar.exists():
        sidecar.unlink()
        removed.append(str(sidecar))
    return removed


def _run_job(job_id: int) -> None:
    db = SessionLocal()
    proc: subprocess.Popen | None = None
    cancelled = False
    prof_cfg_path: str | None = None
    nud_cfg_path: str | None = None
    viol_cfg_path: str | None = None
    try:
        job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
        if not job:
            return

        req = job.request

        # Determine output path
        output_path = _build_output_path(job.input_file)
        job.output_file = output_path

        # Already exists check
        if Path(output_path).exists():
            job.status = JobStatus.already_exists
            job.finished_at = datetime.utcnow()
            db.commit()
            _rollup_request(db, job.request_id)
            return

        job.status = JobStatus.running
        job.started_at = datetime.utcnow()
        job.log_output = ""
        job.progress_json = _json.dumps(_initial_progress())
        db.commit()

        # Write config files from DB settings for this job (per-request overrides apply)
        cleanmedia_bin = _get_setting(db, "cleanmedia_bin")
        prof_cfg_path, nud_cfg_path, viol_cfg_path = _write_config_files(db, req)

        # Check if we can resume from a previous partial run (sidecar exists)
        sidecar = Path(job.input_file).with_suffix(".cleanmedia.json")
        can_resume = sidecar.exists()
        if can_resume:
            print(f"  Resuming job {job_id} — sidecar found from previous run", flush=True)

        cmd = _build_command(job, req, prof_cfg_path, nud_cfg_path, viol_cfg_path, cleanmedia_bin, resume=can_resume)
        log_lines: list[str] = []
        flush_counter = 0
        progress = _initial_progress()
        captured_intervals: dict = {}  # backup of intervals parsed from log output
        stop_event = threading.Event()

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _running_procs[job_id] = proc

            # Start background thread that checks for cancellation every 3s
            watcher = threading.Thread(
                target=_cancel_watcher, args=(job_id, proc, stop_event), daemon=True
            )
            watcher.start()

            for line in proc.stdout:  # type: ignore[union-attr]
                clean = line.rstrip()
                # tqdm progress bars: parse percentage for progress, but don't store in log
                is_tqdm = "\r" in clean or ("|" in clean and "%" in clean and ("frames/s" in clean or "it/s" in clean))
                if is_tqdm:
                    m = _TQDM_PCT_RE.search(clean)
                    if m and progress["phase"] == "profanity":
                        progress["profanity"]["pct"] = int(m.group(1))
                        progress["profanity"]["status"] = "running"
                        job.progress_json = _json.dumps(progress)
                        db.commit()
                    continue
                # PROGRESS: lines drive the progress bar UI — update progress
                # but don't store them in the log output to keep it readable
                is_progress = clean.startswith("PROGRESS:")
                if is_progress:
                    _update_progress(clean, progress, captured_intervals)
                    job.progress_json = _json.dumps(progress)
                    db.commit()
                    continue
                log_lines.append(clean)
                changed = _update_progress(clean, progress, captured_intervals)
                flush_counter += 1
                if flush_counter >= 5 or changed:
                    job.log_output = "\n".join(log_lines)
                    job.progress_json = _json.dumps(progress)
                    db.commit()
                    flush_counter = 0

            proc.wait()
            stop_event.set()  # tell the watcher to stop

            # Check if the process was killed by the cancel watcher
            cancelled = _is_cancelled(job_id)

            job.log_output = "\n".join(log_lines)

            if cancelled:
                job.status = JobStatus.skipped
                job.error_message = "Cancelled by user."
            elif proc.returncode == 0:
                job.status = JobStatus.completed
            else:
                job.status = JobStatus.failed
                job.error_message = f"Process exited with code {proc.returncode}"

        except Exception as exc:
            job.status = JobStatus.failed
            job.error_message = str(exc)
            job.log_output = "\n".join(log_lines)

        job.finished_at = datetime.utcnow()

        # If the job failed/cancelled but we captured intervals from the log,
        # write a backup sidecar so the next retry can resume.
        if job.status in (JobStatus.failed, JobStatus.skipped) and captured_intervals:
            sidecar_path = Path(job.input_file).with_suffix(".cleanmedia.json")
            if not sidecar_path.exists():
                try:
                    backup = {
                        "input_file": job.input_file,
                        "input_hash": "",
                        "duration_seconds": 0,
                        "analysis_source": "worker_backup",
                        "intervals": captured_intervals.get("intervals", []),
                        "nudity_intervals": captured_intervals.get("nudity_intervals", []),
                        "nudity_source": "",
                        "violence_intervals": captured_intervals.get("violence_intervals", []),
                        "violence_source": "",
                    }
                    sidecar_path.write_text(_json.dumps(backup, indent=2))
                except Exception:
                    pass  # best-effort

        # Clean up files for cancelled or failed jobs
        if cancelled:
            removed = _cleanup_job_files(job)
            if removed:
                job.error_message = f"Cancelled by user. Cleaned up: {', '.join(Path(p).name for p in removed)}"

        if job.status == JobStatus.completed:
            job.content_report = _build_content_report(job.input_file)

            # Trigger Plex library refresh so editions/versions appear immediately
            # (skip for user uploads — they don't go back to Plex)
            if req.source != "upload":
                try:
                    from .plex.client import PlexClient
                    plex = PlexClient(db)
                    section_id = plex.get_section_id_for_item(job.plex_key)
                    if section_id:
                        plex.refresh_section(section_id)
                except Exception:
                    pass  # best-effort, don't fail the job

        db.commit()
        _rollup_request(db, job.request_id)

    finally:
        _running_procs.pop(job_id, None)
        # Clean up temp config files
        for p in (prof_cfg_path, nud_cfg_path, viol_cfg_path):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
        db.close()


def _recover_stale_jobs() -> None:
    """On startup, reset any 'running' jobs back to 'queued' — they were orphaned by a restart.

    Preserves progress info so the worker can resume with --resume flag.
    Only cleans up the partial output file (not the sidecar, which holds resumable scan data).
    """
    db = SessionLocal()
    try:
        stale = db.query(ConversionJob).filter(ConversionJob.status == JobStatus.running).all()
        for job in stale:
            # Clean up partial output file only (keep sidecar for resume)
            if job.output_file:
                out = Path(job.output_file)
                if out.exists():
                    out.unlink()
            job.status = JobStatus.queued
            job.error_message = "Recovered after worker restart"
            # Keep progress_json so _run_job knows this is resumable
        if stale:
            db.commit()
            print(f"Recovered {len(stale)} stale running job(s) back to queued.", flush=True)
    finally:
        db.close()


def worker_loop() -> None:
    _recover_stale_jobs()
    while True:
        try:
            db = SessionLocal()
            try:
                job = (
                    db.query(ConversionJob)
                    .filter(ConversionJob.status == JobStatus.queued)
                    .order_by(ConversionJob.priority.asc(), ConversionJob.created_at.asc())
                    .limit(1)
                    .first()
                )
                job_id = job.id if job else None
            finally:
                db.close()

            if job_id is not None:
                _run_job(job_id)
            else:
                time.sleep(settings.WORKER_POLL_INTERVAL_SEC)

        except Exception:
            time.sleep(settings.WORKER_POLL_INTERVAL_SEC)


def start_worker() -> None:
    t = threading.Thread(target=worker_loop, daemon=True, name="cleanarr-worker")
    t.start()
