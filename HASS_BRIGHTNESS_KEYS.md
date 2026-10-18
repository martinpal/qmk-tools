# Home Assistant Brightness Key Combinations

Configured in `config.yaml` under `home_assistant.brightness_keys`. All bindings
are on **layer 4 (Adjust)** — hold Lower + Raise together to reach it. Each key
steps brightness by 10% per tap; holding repeats every 0.2s. See the
[Brightness Control Keys](README.md#brightness-control-keys-optional) section
of the README for how the feature works in general.

| Keys (up / down) | Controls |
|---|---|
| **Y / H** | All three lights together: Martin's Ceiling Light, Server Room Ceiling Light, IKEA bulb |
| **R / F** | Martin's Ceiling Light only |
| **T / G** | Server Room Ceiling Light only |

Pressing any of these first snaps the light back to its normal color if it was
tinted by the layer-color-sync automation, so the brightness change is visible
immediately instead of adjusting the tinted color.
