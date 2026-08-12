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
Before you begin, follow these steps:
1. Do a `git fetch` so that you have all of the latest changes.
2. Make sure all existing changes have been committed to your own branch (branch off `main` if not already on one).
3. Rebase or merge any incoming changes from `origin/main` into your branch before starting work.

## Finishing Tasks — Always Required
For **every change** you make (no exceptions), follow these steps in order:
1. Ensure your local branch has the latest `origin/main`: `git fetch && git rebase origin/main`
2. Commit your changes on your feature branch with a concise, descriptive message.
3. Push to remote: `git push origin <your-branch-name>`
4. Create a PR to merge into `main` using GitLab's API or web UI (the `gh` CLI is not available, and git.wheeli.ca is GitLab).
5. Add `brian` as a reviewer on the Pull Request.

## Credentials
Your credentials for git.wheeli.ca can be found in the parent directory (../credentials.md)