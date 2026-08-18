# Unified UI Design — FPV Display + Controller Status Overlay

## Goal

Replace the two separate output paths (terminal HUD via ANSI codes, standalone
GStreamer video window) with a single GUI window that shows:

1. The live FPV video feed as the background / main canvas.
2. A controller status overlay drawn on top of the video feed.

---

## Current State

| Component | Implementation | Problem |
|-----------|---------------|---------|
| FPV video | GStreamer pipeline → `autovideosink` | Creates its own X11 window,不受 pygame control |
| HUD       | Terminal output with ANSI escape codes | Cannot overlay on video; scrolls and flickers |
| Gamepad   | pygame (input only) | Pygame never creates a display surface |

The three subsystems run in parallel threads but have no shared visual context.

---

## Target Architecture

```
┌──────────────────────────────────────────┐
│              GUI Window                  │
│  ┌────────────────────────────────────┐  │
│  │        FPV Video Feed              │  │
│  │    (GStreamer → appsink)           │  │
│  │                                    │  │
│  │  ┌──────────────────────────┐      │  │
│  │  │   Controller Overlay     │      │  │
│  │  │   · Armed / Disarmed     │      │  │
│  │  │   · Steering bar         │      │  │
│  │  │   · Throttle bar         │      │  │
│  │  │   · ESTOP status         │      │  │
│  │  │   · Recording indicator  │      │  │
│  │  └──────────────────────────┘      │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

---

## Required Changes

### 1. Choose a display framework

**Option A — GTK4 + GstGL (Recommended)**
- Use GTK4 as the window container, draw the GStreamer sink into a `GtkVideo` or
  `GstGLSink` widget, and render the HUD overlay using Cairo drawing in a GTK
  drawing area layered on top.
- Pros: Native GStreamer integration, no frame copying, efficient GPU path.
- Cons: New dependency (`gtk4`, `gstreamer1.0-gl`). Requires rewriting video
  pipeline to use `glimagesink` or `autovideosink` with a GTK widget parent.

**Option B — OpenCV**
- Route GStreamer frames through `appsink` → numpy arrays → `cv2.imshow()`.
  Draw HUD with `cv2.putText()` / `cv2.rectangle()`.
- Pros: Simple, well-documented, single window.
- Cons: Added latency from frame copying; OpenCV window is not easily
  embeddable or positionable.

**Option C — Pygame surface**
- Route GStreamer frames through `appsink` → numpy → pygame surface blit.
  Draw HUD with pygame drawing primitives.
- Pros: Already a dependency; no new libraries.
- Cons: Must decode every frame to RGB in Python (CPU heavy); pygame surface
  updates at high resolution are slow; no hardware acceleration.

### 2. Change GStreamer pipeline sink

Current pipe ends with `autovideosink`. Replace with the framework-appropriate sink:

| Option | New sink element | Notes |
|--------|-----------------|-------|
| A (GTK4) | `gtkglsink` or `glimagesink` with window-xid set | Needs X11 window ID from GTK widget |
| B (OpenCV) | `appsink` with `emit-signals=true`, `caps=video/x-raw` | Pull frames via `pull_sample()` |
| C (Pygame) | `appsink` same as above | Same mechanism, blit to pygame surface instead |

The GStreamer pipeline string in `VideoManager.__init__` (line 142) must be updated.

### 3. Create the main window and video widget

Replace the terminal-based HUD loop with an event-driven GUI main loop:

- Create a top-level window (~1280×720 or match stream resolution).
- Embed the video sink widget as a child.
- Add an overlay drawing area positioned in one corner (e.g., bottom-left).

### 4. Redesign HUD rendering

The `render_hud()` function (lines 357-423) currently writes ANSI codes to stdout.
Replace with framework-native drawing:

| HUD element | Drawing primitive |
|-------------|-------------------|
| Title box / border | Rectangle + text render |
| Vehicle IP, gamepad name | Text labels |
| Armed/disarmed status | Colored text (green = armed, yellow = disarmed) |
| Steering bar | Filled rectangle proportional to PWM value |
| Throttle bar | Same as steering |
| ESTOP warning | Red bold text or flashing indicator |
| Recording timestamp + filename | Text label with timer |

A redraw should be triggered at ~10-30 Hz (no need for 60 Hz — controller state
doesn't change that fast visually).

### 5. Thread safety and data sharing

The `ControllerState` class already uses a lock. The new UI thread needs to read
from it without blocking:

- Keep the existing `ControllerState` structure.
- Add a `ui_refresh_event` (threading.Event) — the gamepoll loop sets it when
  state changes, the UI thread drains and redraws on wake.
- Alternatively, poll `ControllerState` at fixed intervals from the GUI idle
  callback (simpler, less responsive).

The MAVLink sender thread is unchanged.

### 6. Handle window lifecycle

Currently shutdown is triggered via SIGINT/SIGTERM handlers and pygame quit.
With a GUI window:

- Wire the window's close button to call `shutdown()`.
- Keep Ctrl+C handler as fallback.
- Ensure GStreamer pipeline, MAVLink connection, and gamepad are cleaned up in
  the right order (same as current `shutdown()` function).

### 7. Remove or replace pygame dependency (if using GTK4/OpenCV)

If Option A or B is chosen, pygame is only needed for gamepad input. Consider:

- Keeping pygame solely for joystick handling (minimal, works fine).
- Or replacing with SDL2 via PySDL2, or libevdev/uinput for raw input.

Recommendation: Keep pygame for joystick — it works and removing it adds risk.

---

## Incremental Implementation Plan

### Phase 1 — Video in a window (proof of concept)
1. Change GStreamer sink to `appsink`.
2. Pull frames in a worker thread, display via chosen framework.
3. Verify video renders with acceptable latency (<500 ms end-to-end).

### Phase 2 — Overlay rendering
1. Implement the HUD drawing primitives in the new framework.
2. Wire `ControllerState` reads to the overlay redraw loop.
3. Test that bars, status text, and recording indicator update correctly.

### Phase 3 — Integration and polish
1. Replace terminal output with the window as the sole display.
2. Handle window close and graceful shutdown.
3. Remove ANSI HUD code from `gcs_gamepad.py`.
4. Add configurable overlay position, opacity, and font size via CLI flags or
   config file.

### Phase 4 — Optional enhancements
- Telemetry receive: Use `udp:` (bidirectional) MAVLink connection to display
  vehicle telemetry (battery, GPS, mode) in the overlay.
- On-screen controls for arm/disarm/estop toggles.
- Configurable layout presets (e.g., compact overlay for max screen real estate).

---

## File Structure After Changes

```
gcs_gamepad.py          # Main entry, arg parsing, threading, gamepoll loop
ui/video_sink.py        # GStreamer appsink wrapper, frame queue
ui/overlay.py           # HUD drawing, status rendering
ui/window.py            # Top-level window, event loop, lifecycle
config.py               # Extracted constants and CLI defaults (optional)
```

Whether to split into modules depends on team preference. The script is 543 lines
now — a single-file approach may still be viable if the UI code stays compact.
