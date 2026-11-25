import argparse
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
import statistics
import sys
import time
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (
    CAMERA_INDEX,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    GESTURE_STABILIZATION,
    MODEL_PATH,
    SEQUENCE_TIMEOUT,
    GestureStabilizer,
)
from vision_engine.gesture_classifier import GestureClassifier
from vision_engine.gesture_command_controller import GestureCommandController
from vision_engine.gesture_recognition import GestureRecognition
from vision_engine.hand_tracker import HandTracker
from vision_engine.pinch_calibrator import PinchCalibrationConfig, PinchCalibrator
from vision_engine.virtual_interface import CursorSmoother, VirtualAppDock


def percentile(values, pct):
    """Compute linear-interpolated percentile (e.g., 95 for P95)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    return float(sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f))


def _make_scripted_landmarks(gesture_name):
    """Build deterministic 21-landmark dict list for synthetic pipeline benchmarking."""
    pts = [{"x": 0.5, "y": 0.8} for _ in range(21)]
    pts[0] = {"x": 0.50, "y": 0.82}
    pts[17] = {"x": 0.70, "y": 0.70}
    pts[2] = {"x": 0.36, "y": 0.70}
    pts[3] = {"x": 0.30, "y": 0.64}
    pts[4] = {"x": 0.55, "y": 0.72}

    up_map = {
        "OPEN_PALM": (True, True, True, True, True),
        "FIST": (False, False, False, False, False),
        "PEACE": (True, True, False, False, False),
        "POINTING": (True, False, False, False, False),
        "PINCH": (True, True, True, True, False),
        "THUMBS_UP": (False, False, False, False, True),
    }
    i_up, m_up, r_up, p_up, t_out = up_map.get(
        gesture_name, (False, False, False, False, False)
    )
    if t_out:
        pts[4] = {"x": 0.22, "y": 0.56}

    specs = (
        (5, 6, 7, 8, 0.42, i_up),
        (9, 10, 11, 12, 0.50, m_up),
        (13, 14, 15, 16, 0.58, r_up),
        (17, 18, 19, 20, 0.70, p_up),
    )
    for mcp, pip, dip, tip, x_pos, is_up in specs:
        pts[mcp] = {"x": x_pos, "y": 0.70}
        pts[pip] = {"x": x_pos, "y": 0.52}
        pts[dip] = {"x": x_pos, "y": 0.36 if is_up else 0.66}
        pts[tip] = {"x": x_pos, "y": 0.24 if is_up else 0.74}

    if gesture_name == "PINCH":
        pts[4] = {"x": 0.43, "y": 0.25}
        pts[8] = {"x": 0.42, "y": 0.24}
    elif gesture_name == "TRANSIENT_SPIKE":
        # Brief pinch dip (only 1 frame) to test false activation rejection
        pts[4] = {"x": 0.43, "y": 0.25}
        pts[8] = {"x": 0.42, "y": 0.24}
    return pts


def compute_summary_metrics(
    mode,
    frame_records,
    transition_latencies_ms,
    pinch_calibrator,
    pinch_attempts,
    pinch_dock_successes,
    resolution,
    total_wall_seconds,
):
    """Aggregate all 10 required metrics + separated component latencies."""
    e2e_ms = [r["end_to_end_ms"] for r in frame_records]
    capture_ms = [r["capture_ms"] for r in frame_records]
    tracking_ms = [r["tracking_ms"] for r in frame_records]
    classify_ms = [r["classification_ms"] for r in frame_records]
    fps_samples = [r["instant_fps"] for r in frame_records if r["instant_fps"] > 0]

    total_frames = len(frame_records)
    lost_frames = sum(1 for r in frame_records if r["hands_count"] == 0)
    loss_rate_pct = (lost_frames / total_frames * 100.0) if total_frames else 0.0

    avg_fps = (total_frames / total_wall_seconds) if total_wall_seconds > 0 else 0.0
    min_fps = min(fps_samples) if fps_samples else 0.0
    max_fps = max(fps_samples) if fps_samples else 0.0

    avg_proc_ms = statistics.mean(e2e_ms) if e2e_ms else 0.0
    median_ms = statistics.median(e2e_ms) if e2e_ms else 0.0
    p95_ms = percentile(e2e_ms, 95)

    avg_transition_ms = (
        round(statistics.mean(transition_latencies_ms), 3)
        if transition_latencies_ms
        else None
    )

    pinch_rate_pct = (
        round((pinch_dock_successes / pinch_attempts) * 100.0, 2)
        if pinch_attempts > 0
        else None
    )

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "resolution": resolution,
        "frames": total_frames,
        "wall_seconds": round(total_wall_seconds, 3),
        "average_fps": round(avg_fps, 2),
        "minimum_fps": round(min_fps, 2),
        "maximum_fps": round(max_fps, 2),
        "avg_capture_latency_ms": round(statistics.mean(capture_ms), 3) if capture_ms else 0.0,
        "avg_hand_tracking_latency_ms": round(statistics.mean(tracking_ms), 3) if tracking_ms else 0.0,
        "avg_classification_latency_ms": round(statistics.mean(classify_ms), 3) if classify_ms else 0.0,
        "avg_frame_processing_time_ms": round(avg_proc_ms, 3),
        "median_latency_ms": round(median_ms, 3),
        "p95_latency_ms": round(p95_ms, 3),
        "hand_tracking_loss_rate_pct": round(loss_rate_pct, 2),
        "avg_gesture_transition_latency_ms": avg_transition_ms if avg_transition_ms is not None else "N/A",
        "false_activation_count": pinch_calibrator.false_activations,
        "successful_pinch_selection_rate_pct": pinch_rate_pct if pinch_rate_pct is not None else "N/A",
        "pinch_attempts": pinch_attempts,
        "pinch_successes": pinch_dock_successes,
        "enter_ratio": pinch_calibrator.config.enter_ratio,
        "exit_ratio": pinch_calibrator.config.exit_ratio,
    }


def _save_benchmark_csvs(summary, frame_records, output_dir):
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    frames_csv = out_dir / f"benchmark_frames_{summary['mode']}_{ts}.csv"
    if frame_records:
        with frames_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(frame_records[0].keys()))
            writer.writeheader()
            writer.writerows(frame_records)

    sessions_csv = out_dir / "benchmark_sessions.csv"
    write_header = not sessions_csv.exists()
    with sessions_csv.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(summary)

    return sessions_csv, frames_csv


def run_benchmark(
    mode="synthetic",
    max_frames=90,
    camera_index=CAMERA_INDEX,
    show_window=False,
    output_dir="results/benchmark",
):
    """Run reproducible webcam or synthetic pipeline benchmark."""
    tracker = None
    camera = None
    frame_records = []
    transition_latencies_ms = []

    try:
        tracker = HandTracker(model_path=MODEL_PATH)
        recognizer = GestureRecognition()
        classifier = GestureClassifier()
        stabilizer = GestureStabilizer(GESTURE_STABILIZATION)
        controller = GestureCommandController(sequence_timeout=SEQUENCE_TIMEOUT)
        cursor_smoother = CursorSmoother(alpha=0.38, deadzone_px=1.5)
        virtual_dock = VirtualAppDock(dwell_seconds=1.0, cooldown_seconds=0.5)
        pinch_calibrator = PinchCalibrator(
            PinchCalibrationConfig(
                enter_ratio=0.30,
                exit_ratio=0.42,
                cooldown_seconds=0.5,
                min_confirm_frames=2,
            )
        )

        pinch_attempts = 0
        pinch_dock_successes = 0
        pending_transition_raw = None
        pending_transition_start = None
        prev_stable = stabilizer.stable_gesture

        if mode == "webcam":
            camera = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
            if not camera.isOpened():
                raise RuntimeError(f"Could not open webcam at index {camera_index}")
            camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
            camera.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
            camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            actual_w = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_h = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
            resolution = f"{actual_w}x{actual_h}"
        elif mode == "synthetic":
            resolution = "640x480_synthetic"
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            scripted_cycle = (
                ["POINTING"] * 4
                + ["PINCH"] * 4
                + ["POINTING"] * 4
                + ["TRANSIENT_SPIKE"] * 1
                + ["POINTING"] * 3
                + ["OPEN_PALM"] * 4
                + ["FIST"] * 4
                + ["NO_HAND"] * 4
                + ["PEACE"] * 4
            )
        else:
            raise ValueError("mode must be 'webcam' or 'synthetic'")

        dock_rects = virtual_dock.compute_button_rects(
            int(resolution.split("x")[0]) if mode == "webcam" else 640
        )
        vx1, vy1, vx2, vy2 = dock_rects["vscode"]
        target_dock_px = ((vx1 + vx2) // 2, (vy1 + vy2) // 2)

        bench_start = time.perf_counter()
        prev_frame_ts = bench_start

        for idx in range(max_frames):
            t0 = time.perf_counter()

            # Stage 1: Capture
            if mode == "webcam":
                ok, frame = camera.read()
                if not ok:
                    break
                frame = cv2.flip(frame, 1)
            else:
                frame = blank_frame.copy()
                # Pace synthetic loop gently (~25ms per tick) so time-based stabilizer evaluates transitions realistically
                time.sleep(0.022)
            t1 = time.perf_counter()

            # Stage 2: Hand Tracking
            timestamp_ms = int((t1 - bench_start) * 1000)
            annotated, result = tracker.process(frame, timestamp_ms)
            t2 = time.perf_counter()

            # Stage 3: Gesture Classification + Stabilization + Pinch Calibration
            if mode == "webcam":
                hands_count = len(result.hand_landmarks) if result.hand_landmarks else 0
                if hands_count > 0:
                    primary_hand = result.hand_landmarks[0]
                    rec = recognizer.recognize(primary_hand)
                    raw_gesture = rec["gesture"]
                    other_open = any(
                        rec.get("finger_states", {}).get(k, False)
                        for k in ("middle", "ring", "pinky")
                    )
                    idx_tip = primary_hand[8]
                    raw_ptr = (
                        int(idx_tip.x * frame.shape[1]),
                        int(idx_tip.y * frame.shape[0]),
                    )
                    cal_landmarks = primary_hand
                else:
                    raw_gesture = "UNKNOWN"
                    other_open = False
                    raw_ptr = None
                    cal_landmarks = None
            else:
                step_name = scripted_cycle[idx % len(scripted_cycle)]
                if step_name == "NO_HAND":
                    hands_count = 0
                    raw_gesture = "UNKNOWN"
                    other_open = False
                    raw_ptr = None
                    cal_landmarks = None
                else:
                    hands_count = 1
                    cal_landmarks = _make_scripted_landmarks(step_name)
                    rec = classifier.classify(cal_landmarks)
                    raw_gesture = rec["gesture"]
                    other_open = any(
                        rec.get("finger_states", {}).get(k, False)
                        for k in ("middle", "ring", "pinky")
                    )
                    raw_ptr = target_dock_px

            pointer_xy = cursor_smoother.update(raw_ptr)
            stab = stabilizer.update(raw_gesture, t2)
            stable_gesture = stab["stable_gesture"]

            if raw_gesture != prev_stable and pending_transition_raw != raw_gesture:
                pending_transition_raw = raw_gesture
                pending_transition_start = t2

            if stab["changed"]:
                controller.process(stable_gesture, now=t2)
                if pending_transition_start is not None and stable_gesture == pending_transition_raw:
                    transition_latencies_ms.append((t2 - pending_transition_start) * 1000.0)
                    pending_transition_raw = None
                    pending_transition_start = None
                prev_stable = stable_gesture

            prev_pinch = pinch_calibrator.is_pinching
            pinch_eval = pinch_calibrator.update(
                cal_landmarks,
                now=t2,
                can_click=True,
                other_fingers_open=other_open,
            )
            if not prev_pinch and pinch_eval["is_pinching"]:
                pinch_attempts += 1

            t3 = time.perf_counter()

            # Stage 4: Virtual Dock + Rendering (End-to-End Interaction)
            is_pointing = stable_gesture == "POINTING"
            is_pinching = pinch_eval["is_pinching"] or stable_gesture == "PINCH"
            dock_res = virtual_dock.update(
                pointer_xy=pointer_xy,
                is_pointing=is_pointing,
                frame_width=annotated.shape[1],
                is_pinching=is_pinching,
                now=t3,
            )
            if dock_res["triggered"] and dock_res["trigger_mode"] == "PINCH":
                pinch_dock_successes += 1

            virtual_dock.draw(
                annotated,
                pointer_xy=pointer_xy,
                is_pointing=is_pointing,
                is_pinching=is_pinching,
                hud_info={
                    "hands_count": hands_count,
                    "fps": 0.0,
                    "display_gesture": stable_gesture,
                    "raw_gesture": raw_gesture,
                    "stability_text": f"{stab['candidate_count']}/{stab['required_frames']}",
                    "confidence": 0.0,
                    "controller_message": "BENCHMARK",
                    "last_command_message": mode,
                },
                now=t3,
            )

            if show_window and mode == "webcam":
                cv2.imshow("AirTouch Benchmark", annotated)
                if (cv2.waitKey(1) & 0xFF) in (ord("q"), 27):
                    break

            t4 = time.perf_counter()

            # Note: compute processing latency excluding any synthetic sleep
            capture_ms = (t1 - t0) * 1000.0 if mode == "webcam" else 0.0
            tracking_ms = (t2 - t1) * 1000.0
            classify_ms = (t3 - t2) * 1000.0
            dock_render_ms = (t4 - t3) * 1000.0
            e2e_ms = capture_ms + tracking_ms + classify_ms + dock_render_ms

            frame_delta = t4 - prev_frame_ts
            instant_fps = (1.0 / frame_delta) if idx > 0 and frame_delta > 0 else 0.0
            prev_frame_ts = t4

            frame_records.append(
                {
                    "frame_index": idx,
                    "capture_ms": round(capture_ms, 3),
                    "tracking_ms": round(tracking_ms, 3),
                    "classification_ms": round(classify_ms, 3),
                    "dock_render_ms": round(dock_render_ms, 3),
                    "end_to_end_ms": round(e2e_ms, 3),
                    "instant_fps": round(instant_fps, 2),
                    "hands_count": hands_count,
                    "raw_gesture": raw_gesture,
                    "stable_gesture": stable_gesture,
                    "pinch_state": pinch_eval["state"],
                }
            )

        total_wall_seconds = time.perf_counter() - bench_start

        summary = compute_summary_metrics(
            mode=mode,
            frame_records=frame_records,
            transition_latencies_ms=transition_latencies_ms,
            pinch_calibrator=pinch_calibrator,
            pinch_attempts=pinch_attempts,
            pinch_dock_successes=pinch_dock_successes,
            resolution=resolution,
            total_wall_seconds=total_wall_seconds,
        )

        sessions_csv, frames_csv = _save_benchmark_csvs(
            summary, frame_records, output_dir
        )

        return summary, sessions_csv, frames_csv

    finally:
        if camera is not None:
            camera.release()
        if tracker is not None:
            tracker.close()
        if show_window:
            cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="AirTouch Performance Benchmark Tool")
    parser.add_argument(
        "--mode",
        choices=["synthetic", "webcam"],
        default="synthetic",
        help="Run deterministic synthetic pipeline or live webcam benchmark",
    )
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--camera", type=int, default=CAMERA_INDEX)
    parser.add_argument("--show", action="store_true", help="Display OpenCV window in webcam mode")
    parser.add_argument("--output-dir", type=str, default="results/benchmark")
    args = parser.parse_args()

    summary, sessions_csv, frames_csv = run_benchmark(
        mode=args.mode,
        max_frames=args.frames,
        camera_index=args.camera,
        show_window=args.show,
        output_dir=args.output_dir,
    )

    print("=== BENCHMARK SUMMARY ===")
    for key, val in summary.items():
        print(f"{key:38}: {val}")
    print(f"Sessions CSV: {sessions_csv}")
    print(f"Frames CSV  : {frames_csv}")


if __name__ == "__main__":
    main()
