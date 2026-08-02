# basetation — OpenCode Instructions

## Repo structure

- `gcs_gamepad.py` — single entry point. GCS gamepad controller that sends MAVLink RC_CHANNELS_OVERRIDE to a vehicle over UDP (WFB-NG relay). Runs FPV video capture via GStreamer.
- No build system, no tests, no config files. Pure script.

## Running

```bash
pip install pymavlink pygame pygobject   # pygobject optional (GStreamer bindings)
python gcs_gamepad.py --host <vehicle_ip> --port <port>
python gcs_gamepad.py --calibrate        # gamepad axis/button calibration tool
python gcs_gamepad.py --no-arm           # skip arm requirement (bench testing)
```

## Key constraints

- Requires a physical gamepad connected at startup.
- MAVLink connection uses `udpout:` format (not `udp:`) to send — see `gcs_gamepad.py:243`. Using `udp:` binds a listener which WFB-NG never sees.
- Default PWM range is 1000–2000 µs with centre at 1500 µs.
- RC overrides sent at 64 Hz; input timeout after 0.5s sends neutral sticks (when armed).
