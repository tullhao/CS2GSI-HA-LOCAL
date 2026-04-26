# CS2GSI-HA-LOCAL v0.3.15

Combined Home Assistant + Local OpenRGB package for HA-only, local-only, and hybrid setups.

Complete bundle for:

1. **Home Assistant only**
2. **Local PC RGB only** with OpenRGB
3. **Hybrid**: local PC RGB **plus** Home Assistant at the same time

This bundle keeps both systems separated:

- **HA-only** users can ignore the `local_pc/` folder completely.
- **Local-only** users can ignore the `home_assistant/` and `cs2_gsi_bridge_py/` folders completely.
- **Hybrid** users point CS2 to the **local bridge**, and the local bridge forwards the same GSI payloads to Home Assistant.

## What is included

- `cs2_gsi_bridge_py/`  
  Updated HA add-on files, including:
  - bomb blink based on `bomb.countdown` when available
  - round-end winner color exposed through full raw state topics

- `home_assistant/packages/cs2_led_packages.yaml`  
  Recommended one-file HA install using a light group called `light.cs2gsi`

- `home_assistant/manual/scripts.yaml`
- `home_assistant/manual/automations.yaml`  
  Manual HA install if you prefer separate YAML files

- `local_pc/pc_local_bridge.py`  
  Local OpenRGB controller with:
  - bomb blink
  - exploded red hold
  - defused blue blink
  - round-end winner hold (CT blue / T green)
  - freeze/live team colors
  - flash overlay
  - damage boost
  - burning flicker
  - smoke dimming
  - low HP / critical HP

- `local_pc/start_*` / `stop_*` / `restart_*` launchers
- `local_pc/install_autostart_shortcut.ps1`  
  Creates a Startup shortcut for the hidden launcher

- `cs2/cfg/*.cfg`  
  CS2 Game State Integration files

## Important separation

### Home Assistant entities
The HA add-on publishes MQTT entities. Search for them in:
- **Settings -> Devices & services -> MQTT**
- **Developer Tools -> States**
- search for: `cs2_gsi_bridge`

### Local OpenRGB devices
The local OpenRGB bridge **does not create new HA entities by itself**.  
It controls OpenRGB directly on the PC. If you want your OpenRGB devices to appear in HA as entities, install the separate HA OpenRGB integration.

## Light group required for HA

Create a Home Assistant **light group** called:

```text
light.cs2gsi
```

Even if it contains only one light.

## Best install path

- **HA-only** -> use the add-on + HA package/manual YAML
- **Local-only** -> use only `local_pc/`
- **Hybrid** -> use local bridge + add-on together, but point CS2 only to the local bridge

Read the docs in `docs/` in this order:

1. `docs/CHECKLIST.md`
2. `docs/INSTALL_HA_ONLY.md`
3. `docs/INSTALL_LOCAL_ONLY.md`
4. `docs/INSTALL_HYBRID.md`
5. `docs/AUTOSTART_WINDOWS.md`
6. `docs/GITHUB_UPDATE.md`


## Package mode note
If you use package mode, edit Home Assistant logic only in `/homeassistant/packages/cs2_led_packages.yaml`. Do not use the UI “Migrate” button for package-managed scripts or automations.


## Cleanup old HA logic first
Before enabling the package, disable or remove older `TVLED` / previous `CS2 Bridge` UI automations and scripts, otherwise you can get duplicate triggers and wrong colors.
