# GitHub update notes

If you want to update your GitHub repo / HA add-on repo with this bundle, replace these files:

## Add-on
- `cs2_gsi_bridge_py/app/main.py`
- `cs2_gsi_bridge_py/config.yaml`

## Home Assistant package
- `home_assistant/packages/cs2_led_packages.yaml`

## Manual HA YAML
- `home_assistant/manual/scripts.yaml`
- `home_assistant/manual/automations.yaml`

## CS2 cfg examples
- `cs2/cfg/gamestate_integration_homeassistant.cfg`

## Local PC bundle
- everything in `local_pc/`

## Notes
- This bundle assumes a light group called `light.cs2gsi`
- The HA package/manual YAML includes round-end winner hold
- The add-on uses `bomb.countdown` when available for more precise bomb timing
