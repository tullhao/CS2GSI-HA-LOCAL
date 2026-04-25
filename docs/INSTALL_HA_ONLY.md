# Install: Home Assistant only

## 1. Add-on files
Use the files in:
- `cs2_gsi_bridge_py/app/main.py`
- `cs2_gsi_bridge_py/config.yaml`

If you maintain a GitHub repo / HA add-on repo, replace those files there and bump the version.

## 2. Create the light group
In Home Assistant:
- Settings -> Devices & services -> Helpers
- Create helper -> Group -> Light group
- Name it so the entity becomes:

```text
light.cs2gsi
```

Put one or more lights into that group.

## 3. Install the HA logic

### Recommended: package install
Copy:
- `home_assistant/packages/cs2_led_packages.yaml`

to:
- `/config/packages/cs2_led_packages.yaml`

Make sure your HA config contains:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

### Alternative: manual YAML install
Use:
- `home_assistant/manual/scripts.yaml`
- `home_assistant/manual/automations.yaml`

These are for file-based YAML setups. They are not a one-click UI import format.

## 4. CS2 GSI cfg
Copy:
- `cs2/cfg/gamestate_integration_homeassistant.cfg`

to your CS2 cfg folder and replace:

```text
YOUR_HOME_ASSISTANT_IP
```

with your HA IP, for example:

```text
192.168.178.111
```

## 5. Restart HA
After restart:
- go to Developer Tools -> States
- search for `cs2_gsi_bridge`

You should see many MQTT-backed sensors and binary sensors.

## 6. Winner hold in HA
This bundle already includes:
- CT round win -> blue 100%
- T round win -> green 100%
- until freezetime resets the context

It uses the winner information from the raw MQTT state if the corresponding winner sensor exists.
