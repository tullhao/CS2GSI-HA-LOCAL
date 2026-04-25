# Windows autostart

## Recommended file
Use:

- `local_pc/start_cs2_led_everything_hidden.vbs`

This starts OpenRGB minimized, waits, then starts the local bridge hidden.

## Manual install
Press:

```text
Win + R
```

Type:

```text
shell:startup
```

Then create a shortcut to:

```text
local_pc/start_cs2_led_everything_hidden.vbs
```

## Automatic shortcut creation
Run in PowerShell:

```powershell
.\install_autostart_shortcut.ps1
```

inside `local_pc/`

## Remove autostart
Run:

```powershell
.\uninstall_autostart_shortcut.ps1
```

## Stop / restart
- stop hidden bridge: `local_pc/stop_hidden_bridge.bat`
- restart hidden bridge: `local_pc/restart_hidden_bridge.bat`

## Visible debugging
If you need a visible terminal:
- stop the hidden bridge
- run `local_pc/start_visible_bridge.bat`
