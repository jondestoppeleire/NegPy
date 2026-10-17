# 0001. Camera scan capture: Film, Light and Infrared

Status: Proposed
Date: 2026-10-16
Design: [docs/design/camera-scan-capture.md](../design/camera-scan-capture.md)

## Context

The Scan tab's Camera side drives a tethered camera and an optional Scanlight. One dropdown, **Preset**, holds three kinds of entry: five built-in white-light film types, the user's calibrated per-stock exposure recipes, and the action "Create a manual preset…". The capture pattern, Triplet or Single Capture, is a read-only field of a recipe, set in the calibration window's own dropdown. A first-time user sees a card of grayed sliders and steppers, a dropdown that lists only white-light entries, and a hint at the bottom that says to select or create a preset.

The Roll tab already asks what the film is, with a Film Mode card of Color, B&W and Slide. The Film Scanner side already asks for infrared with an **IR** toggle. The Camera side repeats neither, and has no infrared at all: the Big Scanlight carries 850 nm LEDs and its firmware lights them from byte 4 of `SET_COLOR`, which NegPy sends as 0. Retouch's IR Removal already consumes any `metadata["ir"]` plane.

## Decision

1. The Camera side asks three questions, in the order a user decides them, each one control that already exists in the app:
   - **Film**: the Roll tab's Film Mode choice, Color, B&W or Slide. It sets the process on import, and the captured roll's Film Mode card shows the same value.
   - **Light**: White, Trichrome or Single RGB. It is the list of exposures one Scan shoots. Without a Scanlight only White exists, under the camera's own light.
   - **Infrared**: one toggle, as on the Film Scanner card. On, each frame gets one more exposure under the IR LEDs, lit alone, saved as `<frame>_IR`, decoded to a gray plane in `metadata["ir"]`, and IR Removal on for that frame. Grayed for B&W, with the Film Scanner's "blocks infrared" hint, and on a Scanlight without IR LEDs.
2. A **recipe** is the exposure solved for one film stock under one Light and Infrared state: LED levels, a shutter per channel, ISO and aperture, and for Single RGB an optional sensor profile. Recipes live in an **Exposure** card under a **Film stock** picker that lists only recipes for the current Light and Infrared state. White has no recipe: its exposure stays the Live View steppers and Meter, and the card says so in one hint.
3. **Calibrate…** is one primary button. The window keeps its name field, base crosshair, ISO and aperture steppers and Create Sensor Profile. It drops its capture dropdown and probes the channels Film, Light and Infrared imply, IR with its own shutter.
4. A hand-set recipe is the Exposure card's edit toggle, a `header_button`, with save and delete beside it. The dropdown action goes.
5. Import reads the three choices: process from Film, Trichrome Mode and Narrowband from Light, Linear RAW and the sensor profile from a Single RGB recipe, `ir_dust_remove` from Infrared. The Scanning Setup wizard stays for files scanned outside NegPy.
6. Infrared ships only after a rig check proves the camera sees 850 nm through its IR-cut filter. Until then the toggle is grayed with the reason. The work lands as two pieces: infrared capture under today's card first, as a toggle beside Capture mode, then the card restructure.

### First-time path

1. Plug in the camera and the Scanlight. The Camera card shows two green dots.
2. Film: Color.
3. Light: Trichrome, the default with a Scanlight present.
4. Infrared: on, the default when the light has IR LEDs and the film passes them.
5. Output: pick a folder.
6. Exposure: Calibrate…, click the clear base, name the stock, Calibrate.
7. Scan. Every later frame is one Scan; every later stock is one Calibrate.

### Functionality parity

| Today | After |
|---|---|
| White Light (B&W or Slide Film) with autodetect, White Light B&W, White Light Color Negative, White Light Slide, and the + IR pair for Color Negative and Slide | Light: White, with Film: B&W or Slide. Autodetect goes: Film is explicit. |
| Triplet preset | Light: Trichrome, a recipe |
| Single Capture preset with Create Sensor Profile | Light: Single RGB, a recipe, Create Sensor Profile in the window |
| "+" calibrate | Calibrate… |
| Create a manual preset…, floppy, trash | Exposure card's edit, save and delete header buttons |
| Preset dropdown | Film stock picker, filtered by Light and Infrared |
| Capture mode, in the card and in the window | Light |
| Red, Green, Blue, White sliders; Light Off | unchanged; the White slider shows only under White |
| ISO, Shutter, Aperture steppers in the card | unchanged, read-only under a recipe, editable in edit mode |
| Channel Delay | unchanged; hidden under White and Single RGB |
| Live View, Meter, histogram, zebras, focus meter, Retake, Keep Light On | unchanged |
| Live View R, G, B and IR one-channel captures | unchanged; IR follows the Infrared toggle's hardware gate |
| Aperture Priority Meter on the EXPOSURE row | the Exposure card's header, beside Calibrate… |
| IR Shutter stepper | the Exposure card's Infrared row; calibration fills it when the probe reaches a target, the stepper overrides it |
| Scanlight without a white LED, v1 to v3 | Light offers Trichrome and Single RGB |
| Camera without CONFIG, issue #621 | Light offers White only |
| Camera without live view | Calibrate… grayed, as "+" is today |
| No Scanlight | Light: White under the camera's own light, with today's hint to connect one |
| Saved presets and settings | mapped on load in `__post_init__`; no entry in `domain/migrations.py`, which holds `WorkspaceConfig` fixups |
| Nothing | Infrared |

## Consequences

- A new user meets one choice at a time, in the words the Roll tab and the Film Scanner card already use, and reaches a scan with one calibration.
- A trichrome frame can carry an infrared plane, and IR Removal, the IR overlay and the `_ir.tiff` linear export work on it with no new pipeline stage. `THUMBNAIL_RENDER_VERSION` stays, since existing frames have no IR plane.
- `sidebar/scanlight.py` loses its preset list, sentinel and gating around them, about a quarter of the file. `test_scanlight_sidebar.py` and eight other test files reference those names and change with it.
- `ScanlightSettings` and `ScanlightPreset` grow fields and map legacy ones; `RgbScanConfig`, the triplet store, `CaptureRequest`, `CaptureResult` and `_PendingCaptureImport` each gain an infrared field.
- The protocol, the driver, `Channel`, the capture service, the calibration ladder and the simulated camera learn a fourth channel, lit alone like White.
- A stock camera may not see 850 nm; jackw01 states a converted body is needed. Then the Infrared toggle ships grayed and the rest of the decision stands.
- Autodetect of a white capture's film type goes. Film is asked once instead.
