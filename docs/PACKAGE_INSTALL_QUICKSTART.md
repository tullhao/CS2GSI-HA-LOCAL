# Package install quickstart

Use this if you want the Home Assistant side to be managed as one package file.

## 1. Install a file editor first
If you do not have **Studio Code Server**, install the **File editor** add-on in Home Assistant and show it in the sidebar.

## 2. Enable packages
Open `/homeassistant/configuration.yaml` and make sure it contains:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

If `homeassistant:` already exists, only add the `packages:` line inside that block.

## 3. Create the packages folder
Create:

```text
/homeassistant/packages
```

## 4. Copy the package file
Copy:

```text
home_assistant/packages/cs2_led_packages.yaml
```

to:

```text
/homeassistant/packages/cs2_led_packages.yaml
```

## 5. Clean up old UI logic first
Before restarting, disable or remove old **TVLED** / older **CS2 Bridge** UI automations and scripts, so that only the new package logic is active.

## 6. Restart Home Assistant
Do a full Home Assistant restart.

## 7. Important
Once you use package mode, edit the logic only in:

```text
/homeassistant/packages/cs2_led_packages.yaml
```

Do **not** use “Migrate” in the UI for these package scripts/automations.
