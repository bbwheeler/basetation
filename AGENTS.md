# basetation — OpenCode Instructions

## Repo structure

- `gcs_gamepad.py` — single entry point. GCS gamepad controller that sends MAVLink RC_CHANNELS_OVERRIDE to a vehicle over UDP (WFB-NG relay). Runs FPV video capture via GStreamer.
- No build system, no tests, no config files. Pure script.

## Running

```bash
pip install pymavlink pygame pygobject   # pygobject optional (GStreamer bindings)
python gcs_gamepad.py --calibrate        # gamepad axis/button calibration tool
python gcs_gamepad.py --no-arm           # skip arm requirement (bench testing)
```

## Key constraints

- Requires a physical gamepad connected at startup.
- MAVLink connection uses `udpout:` format (not `udp:`) to send — see `gcs_gamepad.py:243`. Using `udp:` binds a listener which WFB-NG never sees.
- Default PWM range is 1000–2000 µs with centre at 1500 µs.
- RC overrides sent at 64 Hz; input timeout after 0.5s sends neutral sticks (when armed).

## Beginning Tasks
Before you begin a task, follow these steps:
1. Make sure all existing changes have been checked in; if there are existing changes, check them in.
2. Do a git fetch so that you have all of the latest changes.
3. Switch to a branch or create a branch appropriate for the changes that you will make

## Finishing Tasks
Once you complete any changes, additions, deletions, or modifications, follow these steps:
1. Check the code into a branch using git
2. Push the code to GitHub
3. Open a Pull Request for the changes you just pushed
4. Add me (bbwheeler) as a reviewer on the Pull Request

Your GitHub credentials can be found in the parent directory (../github.md)