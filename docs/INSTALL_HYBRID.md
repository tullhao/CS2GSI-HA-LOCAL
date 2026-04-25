# Install: Hybrid (Local PC RGB + Home Assistant)

This is the most powerful setup.

## Architecture

```text
CS2 -> local_pc bridge -> OpenRGB on the PC
                     -> forward same GSI payload to HA add-on
```

## 1. Configure the HA side
Follow `docs/INSTALL_HA_ONLY.md` for:
- add-on update
- light group
- HA package/manual YAML

## 2. Configure the local side
Copy:

- `local_pc/config.hybrid.example.json` -> `local_pc/config.json`

Then replace:

```text
YOUR_HOME_ASSISTANT_IP
```

with your HA IP.

Example:

```json
"ha_forward_url": "http://192.168.178.111:3001/"
```

## 3. CS2 cfg for hybrid
Use **only**:

- `local_pc/gamestate_integration_local_bridge.cfg`

Do **not** keep the direct HA cfg active at the same time, otherwise HA may receive duplicate events.

## 4. Start
Use one of:
- `local_pc/start_cs2_led_everything.bat`
- `local_pc/start_cs2_led_everything_hidden.vbs`

## 5. Verify
- local RGB reacts in OpenRGB devices
- HA still updates `cs2_gsi_bridge` sensors
- round win hold appears in both systems
