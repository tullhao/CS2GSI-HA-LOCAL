# Install: Local PC RGB only

## 1. Requirements
- Windows PC
- Python installed
- OpenRGB installed
- OpenRGB SDK server enabled
- CS2 installed on the same PC

## 2. Files
Use everything in `local_pc/`

## 3. Config
Pick the local-only example:

- copy `local_pc/config.local_only.example.json`
- rename it to `local_pc/config.json`

You can keep:
- `enable_forward_to_ha: false`

because this mode does not use HA.

## 4. Python requirements
From inside `local_pc/`:

```powershell
py -m pip install -r .\requirements.txt
```

## 5. CS2 cfg
Copy:
- `local_pc/gamestate_integration_local_bridge.cfg`

into the CS2 cfg folder.

## 6. First start
Use:
- `local_pc/start_cs2_led_everything.bat`

For debugging use:
- `local_pc/start_visible_bridge.bat`

## 7. OpenRGB devices
By default the local bridge filters for:

```json
"openrgb_device_name_contains": ["Commander Pro"]
```

If you want **everything OpenRGB sees**, set:

```json
"openrgb_device_name_contains": []
```

in `config.json`.

## 8. Important
Local-only mode does **not** create HA entities.
It drives OpenRGB directly on the PC.
