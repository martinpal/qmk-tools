# Handover: Mouse wheel/button remap driven by keyboard layer

## Goal

When a specific QMK keyboard layer is held (first use case: layer **2**,
named `"Lower"`), the Corsair M65 RGB Ultra mouse's scroll wheel should act
as a volume control instead of scrolling. Releasing the layer key restores
normal scrolling immediately. The mapping must be configurable in
`config.yaml`, following this project's existing config conventions, and
generalize to future per-layer remaps of mouse buttons (not just the wheel)
without a config schema change.

**Scope of this change: `qmk-tools` only.** No changes are needed in the
`ckb-m65-rgb-ultra` daemon repo — the mechanism this relies on
(`bind`) already ships in the currently-running daemon. Do not go looking
for daemon-side work; there isn't any.

## Prerequisites (environment, not code)

- `ckb-next-daemon` must be running with the M65 RGB Ultra connected. Verify:
  `cat /dev/input/ckb*/productid` — the mouse shows as `1b9e`.
- `cat /dev/input/ckbN/features` must contain `bind` (it does on the
  M65 Ultra; this is a compile-time daemon feature flag, not something to
  code around).
- The daemon's `/dev/input/ckbN/cmd` fifo must be writable by the user
  running `keyboard_overlay_gui.py` (it's a named pipe created by the
  daemon; permissions depend on the daemon's configured group — on Martin's
  machine it's world-writable, `prw-rw-rw-`). If writes fail with a
  permission error, that's an environment/daemon-config issue, not a bug in
  this feature.

## The mechanism (already proven working)

ckb-next's daemon supports a live rebind command, independent of anything
QMK-related: writing a line to `/dev/input/ckbN/cmd` changes what a physical
input produces, in real time, without touching the mouse's stored profile.

```
active
bind wheelup:volup wheeldn:voldn
```

- `active` puts the device in software-controlled mode (idempotent, safe to
  send every time).
- `bind <src>:<dst> <src2>:<dst2> ...` rewrites the live binding for each
  `<src>` key to send `<dst>` instead. To revert, bind each key back to
  itself: `bind wheelup:wheelup wheeldn:wheeldn`.

Key names (from `src/daemon/keymap.c` in the `ckb-m65-rgb-ultra` repo):
`wheelup` / `wheeldn` (physical scroll wheel), `volup` / `voldn`
(`KEY_VOLUMEUP` / `KEY_VOLUMEDOWN`), and for future button remaps:
`mouse1`..`mouse5`, `mouse6`..`mouse8`, `dpiup`, `dpidn`, `sniper`.

### ⚠️ The one gotcha that will silently break this if you get it wrong

**Multiple `key:target` pairs in one `bind` command MUST be separated by a
space, never a comma.**

The daemon's parser (`src/daemon/command.c`, `readcmd()`, the "split the
parameter at the colon" block around line 319) splits each
*whitespace*-separated word on its **first** colon only. A comma is only
meaningful on the *left* side of a single pair (e.g. `mouse1,mouse2:volup`
binds both keys to the same target). If you write:

```
bind wheelup:volup,wheeldn:voldn      # WRONG
```

...the parser reads `left = "wheelup"`, `right = "volup,wheeldn:voldn"`.
`right` doesn't match any known key name, so the daemon **silently no-ops**
— no error, nothing printed, `wheelup`'s binding is simply never touched,
and `wheeldn:voldn` is never even seen as a separate token. This is exactly
what happened during prototyping and cost a full debugging cycle (tracing
through uinput keybits, the M65 Ultra's HID translate function, and the
bind→scancode lookup) before the actual one-line bug was found. Correct
form:

```
bind wheelup:volup wheeldn:voldn      # CORRECT — space between pairs
```

A working end-to-end proof of concept already exists at
`~/source/qmk-tools/wheel_volume_test.py` — it rebinds the wheel for a fixed
duration then restores it. Use it as a sanity check if anything seems not
to be taking effect: run it, scroll during the window, confirm volume
changes, confirm scroll is normal again after.

## Device discovery

`corsair_mouse_monitor.py` currently hardcodes `device_path='/dev/input/ckb1'`
as a constructor default. Don't rely on that — the ckb device index isn't
guaranteed stable. Instead, find the mouse by USB product id:

```python
import glob

M65_ULTRA_PRODUCT_ID = "1b9e"

def find_m65_ultra_device():
    for path in glob.glob('/dev/input/ckb*'):
        try:
            with open(f'{path}/productid') as f:
                if f.read().strip().lower() == M65_ULTRA_PRODUCT_ID:
                    return path
        except FileNotFoundError:
            continue  # ckb0 is the root control node, has no productid
    return None
```

## Where the QMK layer state already lives

**Don't build new layer-polling logic.** `keyboard_overlay_gui.py` already
polls the keyboard's matrix via VIA raw HID and resolves the current layer
in real time (`KeyboardMonitor.run()`, in this same file). On every real
layer transition it emits a Qt signal that lands in
`KeyboardOverlay.on_layer_changed(self, layer_num, layer_stack, default_layer)`
(around line 783). This single method is already the hook point for every
other "do something when the layer changes" feature in this file: GNOME
top-bar indicator, Home Assistant light color sync (`ha_color_enabled`
block, lines 804-822 — structurally the closest existing analog to what
you're building: "entering non-base layer → apply, returning to base →
restore"), and MQTT layer-state publishing. Follow that same pattern.

Important existing simplification to preserve, not "fix": `current_layer` is
a single resolved integer, not the full held-key stack. If two layer keys
are held at once, `current_layer` is whichever has priority (see the MO-key
handling in `KeyboardMonitor.run()` — `max(active_layer_stack.keys())`).
`brightness_keys`, `ha_color`, and MQTT publishing all already key off this
same resolved value and ignore the stack. Do the same — don't add stack
awareness for this feature; it would behave inconsistently with everything
else in the file.

`layer_info` (in `KeyboardOverlay.__init__`, ~line 173) already has
`2: {"name": "Lower", ...}` — confirms layer 2 is the right layer for the
stated use case.

## Config schema

New top-level section, following the existing style (see `brightness_keys`
under `home_assistant` in `config.sample.yaml` for the closest precedent —
same "list of layer-scoped bindings" shape).

Add to **`config.sample.yaml`** (documented, commented out, at the end of
the file):

```yaml
# -----------------------------------------------------------------------------
# Mouse layer remap - Corsair M65 RGB Ultra wheel/button remapping per layer
# -----------------------------------------------------------------------------
# Live-rebinds the mouse's scroll wheel (or buttons) via ckb-next while a
# specific keyboard layer is active, reverting as soon as any other layer
# becomes active. Requires ckb-next-daemon running with the M65 RGB Ultra
# connected (see ckb-m65-rgb-ultra repo - no daemon changes needed).
mouse_remap:
  # Enable mouse layer remap
  # enabled: false

  # Explicit ckb-next device directory, e.g. /dev/input/ckb1.
  # Omit to auto-detect the M65 RGB Ultra by USB product id (1b9e).
  # device: /dev/input/ckb1

  # List of per-layer remaps. Each entry applies 'remap' while the given
  # layer is the active layer, and restores every remapped key to its
  # identity (unremapped) binding as soon as a different layer becomes
  # active.
  #
  # Key names come from ckb-next's keymap (src/daemon/keymap.c in the
  # ckb-m65-rgb-ultra repo): wheelup/wheeldn (scroll wheel), volup/voldn
  # (system volume), mouse1..mouse8, dpiup, dpidn, sniper.
  #
  # layers:
  #   - layer: 2                 # "Lower" layer
  #     remap:
  #       wheelup: volup
  #       wheeldn: voldn
```

Add the live, active version to Martin's **`config.yaml`** (uncommented,
matching how `boblight`/`home_assistant`/`mqtt` are already live there):

```yaml
mouse_remap:
  enabled: true
  layers:
    - layer: 2
      remap:
        wheelup: volup
        wheeldn: voldn
```

## Implementation

### 1. `corsair_mouse_monitor.py`

Add `import glob` to the imports.

Add `find_m65_ultra_device()` (device-discovery function above) at module
level.

Add a `bind()` method to `CorsairMouseMonitor`, next to `set_rgb()`:

```python
def bind(self, pairs: Dict[str, str]) -> bool:
    """Live-rebind keys via ckb-next. pairs: {source_key: target_key},
    e.g. {'wheelup': 'volup', 'wheeldn': 'voldn'}.

    IMPORTANT: pairs are joined with spaces, not commas - ckb-next's
    command parser only supports commas on the LEFT side of a single
    pair. A comma between two full pairs corrupts the second pair's
    target and the daemon silently no-ops. See command.c readcmd().

    Returns True if the command was written successfully. This does NOT
    guarantee the daemon accepted every key name - unknown names are
    also silently ignored by the daemon.
    """
    if not pairs:
        return True
    spec = ' '.join(f'{src}:{dst}' for src, dst in pairs.items())
    try:
        with open(self.cmd_path, 'w') as cmd:
            cmd.write('active\n')
            cmd.write(f'bind {spec}\n')
            cmd.flush()
        return True
    except Exception as e:
        print(f"Error sending bind command: {e}")
        return False
```

Do **not** call `.start()` on `CorsairMouseMonitor` for this feature — that
sets up a notification-node listener thread for button/DPI events, which
this feature doesn't need. Just instantiate the class (no I/O happens in
`__init__`) and call `.bind()` directly.

### 2. `keyboard_overlay_gui.py`

**`KeyboardOverlay.__init__`** — add near the existing `mqtt_client` /
`mqtt_enabled` block (~line 232):

```python
# Mouse layer remap (set later by main)
self.mouse_client = None
self.mouse_remap_layers = []       # [{'layer': int, 'remap': {src: dst}, 'restore': {src: src}}, ...]
self.mouse_remap_active_layer = None   # layer number currently remapped, or None
```

**`on_layer_changed`** — add a block after the `ha_color_enabled` block
(~after line 822), before or after the MQTT block, doesn't matter which:

```python
# Apply/restore mouse remap bound to the active layer
if self.mouse_client and self.mouse_remap_layers:
    matched = next((mr for mr in self.mouse_remap_layers
                     if mr['layer'] == layer_num), None)

    if matched is not None and self.mouse_remap_active_layer != matched['layer']:
        if self.mouse_client.bind(matched['remap']):
            self.mouse_remap_active_layer = matched['layer']
    elif matched is None and self.mouse_remap_active_layer is not None:
        prev = next((mr for mr in self.mouse_remap_layers
                      if mr['layer'] == self.mouse_remap_active_layer), None)
        if prev and self.mouse_client.bind(prev['restore']):
            self.mouse_remap_active_layer = None
```

**`main()`** — add a setup block, modeled directly on the existing
`brightness_keys` parsing block (~lines 1891-1917). Place it after the MQTT
setup block and before `overlay.load_layers()` (~line 1948):

```python
# Setup mouse layer remap integration if enabled
mouse_client = None
mouse_remap_layers = []
raw_mouse_remap = config.get('mouse_remap', {}) or {}
if raw_mouse_remap.get('enabled'):
    import corsair_mouse_monitor

    device_path = raw_mouse_remap.get('device') or corsair_mouse_monitor.find_m65_ultra_device()
    if not device_path:
        print("[MOUSE] Warning: mouse_remap enabled but no M65 Ultra found under /dev/input/ckb*, continuing without it")
    else:
        mouse_client = corsair_mouse_monitor.CorsairMouseMonitor(device_path=device_path)
        print(f"[MOUSE] Layer remap enabled, using {device_path}")

        seen_layers = set()
        for i, raw in enumerate(raw_mouse_remap.get('layers') or []):
            try:
                layer = int(raw['layer'])
                remap = {str(k): str(v) for k, v in dict(raw['remap']).items()}
                if not remap:
                    raise ValueError("remap must have at least one key:target pair")
                if layer in seen_layers:
                    print(f"[MOUSE] Warning: mouse_remap.layers[{i}] duplicate layer {layer}, ignoring")
                    continue
                seen_layers.add(layer)
                mouse_remap_layers.append({
                    'layer': layer,
                    'remap': remap,
                    'restore': {src: src for src in remap},
                })
            except (KeyError, ValueError, TypeError) as e:
                print(f"[MOUSE] Warning: skipping invalid mouse_remap.layers[{i}] entry: {e}")
        if mouse_remap_layers:
            print(f"[MOUSE] {len(mouse_remap_layers)} layer remap binding(s) configured")

overlay.mouse_client = mouse_client
overlay.mouse_remap_layers = mouse_remap_layers
```

**Shutdown cleanup** — in the `finally:` block at the end of `main()`
(~lines 1966-1975), add restore-on-exit so a Ctrl+C while the layer is held
doesn't leave the wheel permanently stuck on volume:

```python
    finally:
        keyboard_monitor.running = False
        keyboard.close()
        if ha_client:
            ha_client.stop_polling()
            ha_client.disconnect()
        if mqtt_client_instance:
            mqtt_client_instance.disconnect()
        if mouse_client and overlay.mouse_remap_active_layer is not None:
            active = next((mr for mr in mouse_remap_layers
                            if mr['layer'] == overlay.mouse_remap_active_layer), None)
            if active:
                mouse_client.bind(active['restore'])
```

No changes needed to `KeyboardMonitor` (the background polling thread) or
to argparse — this follows `brightness_keys`' precedent of being
config-file-only, no CLI flag equivalent.

## Testing / acceptance checklist

1. `python3 -c "import corsair_mouse_monitor as m; print(m.find_m65_ultra_device())"`
   prints a `/dev/input/ckbN` path (not `None`).
2. With `mouse_remap` absent/`enabled: false`: app behaves exactly as
   before, no `[MOUSE]` log lines, no `/dev/input/ckb*` access attempted.
3. With `mouse_remap.enabled: true` and the layer-2 binding configured:
   hold the physical key that sends `MO(2)` — scrolling the wheel changes
   system volume (verify with the OS volume OSD), *not* scrolling.
4. Release the layer key — wheel scrolls normally again, immediately.
5. Quick tap (press+release faster than a poll cycle) doesn't leave the
   wheel stuck remapped.
6. Ctrl+C (or otherwise exit the app) *while the layer key is held down* —
   after exit, the wheel scrolls normally (validates the `finally:`
   restore). This is the one easiest correctness detail to accidentally
   skip — check it explicitly, don't assume.
7. Unplug the mouse / stop the daemon, then start
   `keyboard_overlay_gui.py` with `mouse_remap.enabled: true` — app should
   print the "no M65 Ultra found" warning and continue running normally
   (keyboard overlay still works), not crash or hang.
8. Sanity-check the underlying mechanism directly if anything above fails:
   `python3 wheel_volume_test.py 15` and scroll during the window — if
   *this* doesn't work, the bug is in the bind command construction (check
   for the comma-vs-space mistake first), not in the layer-detection glue.

## Explicitly out of scope for this pass

- Mouse reconnect handling. The keyboard has elaborate reconnect logic
  (`KeyboardMonitor.reconnect_keyboard()`); the mouse does not need it here
  — if the mouse's `/dev/input/ckbN` path disappears mid-session, `bind()`
  returns `False`, a warning is printed, and the remap is simply not
  applied/restored until the path reappears (next layer-change event will
  retry naturally since `bind()` is called fresh each time). Don't build
  more than this.
- Remapping physical mouse **buttons** (not just the wheel). The config
  schema already supports it (`remap` is an arbitrary `{src: dst}` dict,
  and `mouse1`..`mouse8`/`dpiup`/`dpidn`/`sniper` are valid key names) —
  no schema change will be needed later — but only the wheel→volume case
  needs to be tested and working for this handover to be considered done.
- Layer-stack-aware remapping (see "important existing simplification"
  above) — intentionally not done, for consistency with the rest of the
  file.
- Keyboard reconnect interaction: `KeyboardMonitor.reconnect_keyboard()`
  resets its own layer state but does not know about
  `overlay.mouse_remap_active_layer`. If the *keyboard* disconnects while a
  mouse remap is active, the remap won't be explicitly restored at that
  moment (only on the next real layer change, or app exit). Not worth
  handling specially for this pass — flagging it so it isn't mistaken for
  an oversight later.
