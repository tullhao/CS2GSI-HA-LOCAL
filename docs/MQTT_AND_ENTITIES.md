# MQTT entities and where to search

## HA add-on entities
The HA add-on publishes MQTT topics and Home Assistant entities.

Search in:
- Settings -> Devices & services -> MQTT
- Developer Tools -> States

Search term:

```text
cs2_gsi_bridge
```

## Local bridge entities
The local OpenRGB bridge does **not** add HA MQTT entities by itself.

If you are only using:
- `local_pc/pc_local_bridge.py`

then your Commander Pro / OpenRGB devices are controlled locally and will **not** appear in HA unless you separately add the HA OpenRGB integration.

## Why entity count may not increase
If you already had around 101 MQTT entities, installing the local bridge alone will not add more. That is expected.
