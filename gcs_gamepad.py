#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
  GCS Gamepad Controller — MAVLink RC Override via Gamepad
  Sends RC_CHANNELS_OVERRIDE to vehicle over UDP (WFB-NG relay)
═══════════════════════════════════════════════════════════════

Dependencies:
    pip install pymavlink pygame

Usage:
    python gcs_gamepad.py [--host <vehicle_ip>] [--port <port>]

Controls (default gamepad layout):
    Steering: Left Stick
    Forward: Right Trigger
    Reverse/Brake: Left Trigger
    Arm/Start: Right Shoulder Button
    Disarm/Stop: Left Shoulder Button
    Emergency Stop: B
"""

import sys
import time
import argparse
import threading
import signal
import pygame
from pymavlink import mavutil

# ─── Configuration ────────────────────────────────────────────────────────────

DEFAULT_HOST        = "127.0.0.1"   # Vehicle IP (through WFB-NG relay)
DEFAULT_PORT        = 14550          # GCS-side WFB-NG port
HEARTBEAT_INTERVAL  = 1.0           # seconds between heartbeats
RC_SEND_INTERVAL    = 0.015625      # seconds between RC overrides (64 Hz)
RC_TIMEOUT          = 0.5           # seconds without input → send neutral
SYSTEM_ID           = 255           # GCS MAVLink system ID

# PWM range
MAV_MIN     = 1000
MAV_CENTRE  = 1500
MAV_MAX     = 2000

# Deadzone for analog sticks (0.0 – 1.0)
STICK_DEADZONE = 0.08

# Expo curve factor (0.0 = linear, 1.0 = full cubic expo)
STEERING_EXPO  = 0.0
THROTTLE_EXPO  = 0.0

# Axis / button indices
AXIS_STEER    = 0   # Left stick X
AXIS_FORWARD       = 4   # Right trigger  (trigger mode, forward)
AXIS_REVERSE       = 5   # Left trigger   (trigger mode, reverse)

BTN_ARM       = 7   # Right Shoulder
BTN_DISARM    = 6   # Left Shoulder
BTN_ESTOP     = 1   # B

# ─── ANSI colour helpers ──────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
WHITE  = "\033[37m"
GREY   = "\033[90m"

def clr(text, *codes): return "".join(codes) + str(text) + RESET

# ─── Utility functions ────────────────────────────────────────────────────────

def apply_deadzone(value: float, deadzone: float) -> float:
    """Remove stick drift within deadzone, rescale remaining range to 0–1."""
    if abs(value) < deadzone:
        return 0.0
    sign = 1 if value > 0 else -1
    return sign * (abs(value) - deadzone) / (1.0 - deadzone)

def apply_expo(value: float, expo: float) -> float:
    """Blend linear and cubic response. expo=0 → linear, expo=1 → full cubic."""
    return expo * (value ** 3) + (1.0 - expo) * value

def axis_to_mav(value: float, deadzone: float = STICK_DEADZONE,
                expo: float = 0.0, invert: bool = False) -> int:
    """Convert a normalised axis value (-1..+1) to a mavlink value."""
    v = apply_deadzone(value, deadzone)
    v = apply_expo(v, expo)
    if invert:
        v = -v
    mav = int(MAV_CENTRE + v * (MAV_MAX - MAV_CENTRE))
    return max(MAV_MIN, min(MAV_MAX, mav))

def trigger_to_mav(forward: float, reverse: float, expo: float = 0.0) -> int:
    """
    Convert two trigger axes (each 0..1 after normalisation) to a mavlink value.
    Forward  → above centre (1500–2000)
    Reverse  → below centre (1000–1500)
    """
    fwd = max(0.0, forward)
    rev = max(0.0, reverse)
    # Net value in -1..+1 (forward positive)
    net = fwd - rev
    net = apply_expo(net, expo)
    mav = int(MAV_CENTRE + net * (MAV_MAX - MAV_CENTRE))
    return max(MAV_MIN, min(MAV_MAX, mav))

def mav_bar(pwm: int, width: int = 20) -> str:
    """Render a visual bar for a MavLink value."""
    ratio = (pwm - MAV_MIN) / (MAV_MAX - MAV_MIN)
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"

# ─── Controller state ─────────────────────────────────────────────────────────

class ControllerState:
    def __init__(self):
        self.steering_mav  = MAV_CENTRE
        self.throttle_mav  = MAV_CENTRE
        self.armed         = False
        self.estop         = False
        self.last_input_ts = time.time()
        self.lock          = threading.Lock()

    def safe_neutral(self):
        with self.lock:
            self.steering_mav = MAV_CENTRE
            self.throttle_mav = MAV_CENTRE

# ─── MAVLink sender thread ────────────────────────────────────────────────────

class MAVLinkSender(threading.Thread):
    def __init__(self, connection_str: str, state: ControllerState, no_arm: bool = False):
        super().__init__(daemon=True)
        self.conn_str    = connection_str
        self.state       = state
        self.no_arm      = no_arm
        self.mav         = None
        self.connected   = False
        self._stop_event = threading.Event()

    def connect(self):
        print(clr(f"  Connecting to vehicle at {self.conn_str} …", CYAN))
        # ── FIX: use udpout: so pymavlink SENDS to the target rather than
        #         binding as a server.  "udp:" binds a listener; WFB-NG never
        #         sees anything.  "udpout:" is the correct client/sender form.
        self.mav = mavutil.mavlink_connection(
            self.conn_str,
            source_system=SYSTEM_ID,
            source_component=mavutil.mavlink.MAV_COMP_ID_MISSIONPLANNER,
        )
        self.connected = True
        print(clr("  MAVLink connection established.", GREEN))

    def send_heartbeat(self):
        self.mav.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0,
        )

    def send_rc_override(self, steer: int, throttle: int):
        self.mav.mav.rc_channels_override_send(
            0,          # target_system    (vehicle)
            0,          # target_component — 0 = broadcast; using 1 causes some
                        #                    FCs to silently discard the message
            steer,      # ch1  – steering
            0,          # ch2  – unused (pass-through)
            throttle,   # ch3  – throttle / ESC
            0,          # ch4  – unused
            0,          # ch5  – unused
            0,          # ch6  – unused
            0,          # ch7  – unused
            0,          # ch8  – unused
        )

    def run(self):
        self.connect()
        last_heartbeat = 0.0

        while not self._stop_event.is_set():
            now = time.time()

            # Heartbeat at 1 Hz
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                try:
                    self.send_heartbeat()
                except Exception as e:
                    print(clr(f"\n  Heartbeat error: {e}", RED))
                last_heartbeat = now

            # RC override at 20 Hz
            with self.state.lock:
                armed   = self.state.armed
                estop   = self.state.estop
                steer   = self.state.steering_mav
                thr     = self.state.throttle_mav
                last_in = self.state.last_input_ts

            # RC timeout watchdog → neutral
            # (not applied in no_arm mode — operator has accepted the risk)
            if armed and not self.no_arm and (now - last_in > RC_TIMEOUT):
                steer = MAV_CENTRE
                thr   = MAV_CENTRE

            if estop or not armed:
                steer = MAV_CENTRE
                thr   = MAV_CENTRE

            try:
                self.send_rc_override(steer, thr)
            except Exception as e:
                print(clr(f"\n  RC send error: {e}", RED))

            time.sleep(RC_SEND_INTERVAL)

    def stop(self):
        self._stop_event.set()
        # Send one final neutral before exit
        if self.mav:
            try:
                self.send_rc_override(MAV_CENTRE, MAV_CENTRE)
            except Exception:
                pass

# ─── Calibration helper ───────────────────────────────────────────────────────

def run_calibration():
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print(clr("  No gamepad found.", RED))
        return

    js = pygame.joystick.Joystick(0)
    js.init()
    print(clr(f"\n  Calibrating: {js.get_name()}", CYAN))
    print(clr(f"  Axes: {js.get_numaxes()}   Buttons: {js.get_numbuttons()}\n", GREY))
    print("  Move each axis / press each button. Press Ctrl+C to exit.\n")

    try:
        while True:
            pygame.event.pump()
            axes    = [round(js.get_axis(i), 3) for i in range(js.get_numaxes())]
            buttons = [js.get_button(i) for i in range(js.get_numbuttons())]
            line = (
                "  Axes: " + "  ".join(
                    clr(f"[{i}]={v:+.2f}", YELLOW if abs(v) > 0.1 else GREY)
                    for i, v in enumerate(axes)
                )
                + "\n  Btns: " + "  ".join(
                    clr(f"[{i}]", GREEN if b else GREY)
                    for i, b in enumerate(buttons)
                )
            )
            sys.stdout.write("\033[2A\033[J" + line + "\n")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n  Calibration done.")
    finally:
        pygame.quit()

# ─── HUD display ─────────────────────────────────────────────────────────────

def render_hud(state: ControllerState, js_name: str, conn_str: str, no_arm: bool = False):
    with state.lock:
        steer  = state.steering_mav
        thr    = state.throttle_mav
        armed  = state.armed
        estop  = state.estop

    if estop:
        status = clr(" ● ESTOP ", RED, BOLD)
    elif no_arm:
        status = clr(" ● ARMED (--no-arm) ", GREEN, BOLD)
    elif armed:
        status = clr(" ● ARMED ", GREEN, BOLD)
    else:
        status = clr(" ○ DISARMED — press START to arm! ", YELLOW, BOLD)

    lines = [
        "",
        clr("  ╔══════════════════════════════════════╗", CYAN),
        clr("  ║   GCS GAMEPAD CONTROLLER             ║", CYAN),
        clr("  ╚══════════════════════════════════════╝", CYAN),
        f"  {clr('Vehicle :', GREY)} {clr(conn_str, WHITE)}",
        f"  {clr('Gamepad :', GREY)} {clr(js_name, WHITE)}",
        f"  {clr('Status  :', GREY)} {status}",
        "",
        f"  {clr('Steering ', GREY)}CH1  {clr(f'{steer:4d}µs', YELLOW)}  {mav_bar(steer)}",
        f"  {clr('Throttle ', GREY)}CH3  {clr(f'{thr:4d}µs',   YELLOW)}  {mav_bar(thr)}",
        "",
        clr("  Controls:", GREY),
        clr("   Left stick X          → Steering", GREY),
        clr("   LT (reverse) / RT (forward) → Throttle", GREY),
        clr("   START / Options       → Arm", GREY),
        clr("   BACK  / Share         → Disarm", GREY),
        clr("   B / Circle            → Emergency STOP", GREY),
        clr("   Ctrl+C                → Quit", GREY),
        "",
    ]

    # Move cursor up to overwrite previous HUD
    sys.stdout.write(f"\033[{len(lines)}A\033[J")
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()

# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GCS Gamepad Controller")
    parser.add_argument("--host",      default=DEFAULT_HOST, help="Vehicle IP or hostname")
    parser.add_argument("--port",      default=DEFAULT_PORT, type=int, help="UDP port")
    parser.add_argument("--calibrate", action="store_true",  help="Run axis/button calibration tool")
    parser.add_argument("--no-arm",    action="store_true",  help="Skip arm requirement (bench testing only — sticks live immediately)")
    args = parser.parse_args()

    no_arm = args.no_arm

    if args.calibrate:
        run_calibration()
        return

    # ── Init pygame ──────────────────────────────────────────────────────────
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print(clr("\n  ERROR: No gamepad detected. Plug in a controller and retry.\n", RED))
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()
    js_name = js.get_name()
    print(clr(f"\n  Gamepad detected: {js_name}", GREEN))
    print(clr(f"  Axes: {js.get_numaxes()}   Buttons: {js.get_numbuttons()}\n", GREY))

    conn_str = f"udpout:{args.host}:{args.port}"

    # ── State & sender ───────────────────────────────────────────────────────
    state  = ControllerState()
    if no_arm:
        state.armed = True   # --no-arm: sticks live immediately, no button needed
    sender = MAVLinkSender(conn_str, state, no_arm=no_arm)

    def shutdown(sig=None, frame=None):
        print(clr("\n\n  Shutting down — sending neutral...", YELLOW))
        state.safe_neutral()
        sender.stop()
        pygame.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    sender.start()

    # Print blank lines that the HUD will overwrite
    print("\n" * 20)

    clock = pygame.time.Clock()

    while True:
        # ── Process pygame events ────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                shutdown()

            elif event.type == pygame.JOYBUTTONDOWN:
                if event.button == BTN_ESTOP:
                    with state.lock:
                        state.estop    = True
                        state.armed    = False
                        state.steering_mav = MAV_CENTRE
                        state.throttle_mav = MAV_CENTRE
                    print(clr("\n  ⚠  EMERGENCY STOP", RED, BOLD))

                elif event.button == BTN_ARM:
                    with state.lock:
                        state.armed = True
                        state.estop = False

                elif event.button == BTN_DISARM:
                    with state.lock:
                        state.armed = False
                        state.estop = False
                        state.steering_mav = MAV_CENTRE
                        state.throttle_mav = MAV_CENTRE

        # ── Read axes ────────────────────────────────────────────────────────
        pygame.event.pump()

        raw_steer = js.get_axis(AXIS_STEER) if js.get_numaxes() >= AXIS_STEER else 0.0

        # Triggers typically report -1 (released) to +1 (fully pressed)
        # Normalise to 0..1
        raw_rt = js.get_axis(AXIS_FORWARD) if js.get_numaxes() >= AXIS_FORWARD else -1.0
        raw_lt = js.get_axis(AXIS_REVERSE) if js.get_numaxes() >= AXIS_REVERSE else -1.0
        fwd = (raw_rt + 1.0) / 2.0   # 0 (released) → 1 (floored)
        rev = (raw_lt + 1.0) / 2.0
        thr_mav = trigger_to_mav(fwd, rev, expo=THROTTLE_EXPO)

        steer_mav = axis_to_mav(raw_steer, expo=STEERING_EXPO)

        with state.lock:
            state.steering_mav = steer_mav
            state.throttle_mav = thr_mav

            stick_active = (
                abs(apply_deadzone(raw_steer, STICK_DEADZONE)) > 0
                or thr_mav != MAV_CENTRE
            )
            if stick_active:
                state.last_input_ts = time.time()

        # ── Refresh HUD ──────────────────────────────────────────────────────
        render_hud(state, js_name, conn_str, no_arm=no_arm)

        clock.tick(60)  # 60 fps UI refresh

# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()