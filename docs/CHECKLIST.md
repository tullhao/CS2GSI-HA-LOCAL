# Checklist

## Before anything
- [ ] Decide your mode:
  - HA-only
  - Local-only
  - Hybrid
- [ ] Do **not** keep multiple active CS2 GSI cfg files pointing at different receivers unless you really want duplicate events.
- [ ] If using HA, create a light group called `light.cs2gsi`.
- [ ] If using local PC RGB, make sure OpenRGB sees your devices and the SDK server works.

## HA-only
- [ ] Install / update the add-on from `cs2_gsi_bridge_py/`
- [ ] Copy `home_assistant/packages/cs2_led_packages.yaml` to `/config/packages/`
  OR use `home_assistant/manual/scripts.yaml` and `home_assistant/manual/automations.yaml`
- [ ] Place `cs2/cfg/gamestate_integration_homeassistant.cfg` in the CS2 cfg folder
- [ ] Replace `YOUR_HOME_ASSISTANT_IP`
- [ ] Restart HA
- [ ] Verify states in Developer Tools -> States by searching `cs2_gsi_bridge`

## Local-only
- [ ] Install Python
- [ ] Install OpenRGB
- [ ] Enable OpenRGB SDK server
- [ ] Copy `local_pc/config.local_only.example.json` to `config.json`
- [ ] Install `local_pc/requirements.txt`
- [ ] Place `local_pc/gamestate_integration_local_bridge.cfg` in the CS2 cfg folder
- [ ] Start with `local_pc/start_cs2_led_everything.bat` or the hidden VBS

## Hybrid
- [ ] Configure the HA add-on
- [ ] Configure the HA package/manual YAML
- [ ] Copy `local_pc/config.hybrid.example.json` to `local_pc/config.json`
- [ ] Replace `YOUR_HOME_ASSISTANT_IP`
- [ ] Use **only** `local_pc/gamestate_integration_local_bridge.cfg` in CS2
- [ ] Start the local bridge
- [ ] Verify that HA still receives MQTT updates


## Package mode note
If you use package mode, edit Home Assistant logic only in `/homeassistant/packages/cs2_led_packages.yaml`. Do not use the UI “Migrate” button for package-managed scripts or automations.


## Cleanup old HA logic first
Before enabling the package, disable or remove older `TVLED` / previous `CS2 Bridge` UI automations and scripts, otherwise you can get duplicate triggers and wrong colors.
