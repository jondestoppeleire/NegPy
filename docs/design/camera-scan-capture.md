# Camera scan capture: Film, Light and Infrared

Status: draft, written 2026-10-16 against commit `9672ab72`. The decision goes in `docs/adr/0001-camera-scan-capture-model.md`.

## 1. Context and scope

The Scan tab's Camera side captures film with a tethered camera and, when one is connected, a [Scanlight](https://github.com/jackw01/scanlight). One dropdown, **Preset**, carries three decisions: what the film is, which exposures one Scan shoots, and how each exposure is set. Its entries are three built-in white-light film types, the user's calibrated per-stock recipes, and an action, "Create a manual preset…". The capture pattern, Triplet or Single Capture, is a read-only field of a recipe.

Infrared does not exist on the Camera side. The Big Scanlight carries 16 infrared LEDs at 850 nm ([big.md](https://github.com/jackw01/scanlight/blob/main/big.md)) and its firmware drives them from byte 4 of `SET_COLOR` ([control interface](https://github.com/jackw01/scanlight/blob/main/automation/bsl_control_interface.md)). NegPy's encoder sends that byte as 0. The consumer side exists: Retouch's **IR Removal** runs on any `metadata["ir"]` plane and is gated by `state.has_ir`.

Scope: the Camera cards of the Scan tab, the calibration window, the capture service and the import of captured frames. Out of scope: the Film Scanner cards and every pipeline stage.

Written now because the first Scanlight session on a Big Scanlight with a Sony A7R5 found the preset path hard to follow and found no way to shoot infrared.

## 2. Goals and non-goals

Goals:

- A first-time user picks film, light and infrared in that order, and sees each choice once.
- A trichrome scan, with or without infrared, takes one calibration per film stock and one Scan per frame.
- Every current capability survives: white light with film-type import, triplet, single RGB with a sensor profile, hand-set recipes, Meter, Retake, Keep Light On, Channel Delay.
- An infrared frame reaches IR Removal with no new pipeline stage.

Non-goals:

- Changes to the Film Scanner cards.
- A new look. Every control is an existing factory.
- Infrared on a camera that cannot see 850 nm.
- Replacing the Scanning Setup wizard, which serves files scanned outside NegPy.

## 3. Design

### 3.1 What the tab does today

| What the user sees | What it is | Where |
|---|---|---|
| Presets that are only B&W, Slide, or both | Three built-in white-light modes. They set the W LED and the process on import. No calibration. | `_BUILTIN_WHITE_PRESETS` in `sidebar/scanlight.py` |
| "Create a manual preset…" | A dropdown entry that unlocks the R/G/B sliders and the ISO, shutter and aperture steppers. Its **Capture mode** offers Triplet or Single Capture, one exposure with all three LEDs lit. | `_MANUAL_PRESET`, `_set_manual_mode` |
| "+" opens a window with a sample light | The calibration window. It lights a fixed reference mix, the user clicks the clear base, and it solves LED levels plus one shutter for the stock. | `calibration_window.py`, `_on_preset_new` |
| Triplet in that window, then save | The window's own Triplet / Single Capture dropdown. **Calibrate & Save** stores a preset with the solved levels. Infrared is never shot. | `CAPTURE_MODES`, `_on_calibration_finished` |

Findings, each with its consequence:

1. **Three kinds of entry in one list.** Film type, exposure recipe and an edit action share the Preset dropdown. A new user cannot tell which entries scan and which configure.
2. **The capture pattern is a property of a recipe, not a choice.** Triplet or Single Capture is set in two places, the sidebar's disabled Capture mode and the calibration window's dropdown, and is visible in neither until a calibration runs.
3. **Film type is asked differently per scanner.** The Film Scanner card has **Film** and an **IR** toggle from one vocabulary, `FILM_TYPES` in `infrastructure/scanners/params.py`. The Camera card folds film type into preset names, and any RGB preset implies color negative, so a B&W roll under RGB light imports as C-41.
4. **Exposure lives in three places.** Live View toolbar steppers for white and camera-only scans, sidebar steppers for a manual preset, calibration-window steppers for ISO and aperture before a run.
5. **Three save paths.** "+" calibrates and saves, the floppy saves a manual preset through a name prompt, the built-ins cannot be saved.
6. **No infrared.** The driver sends IR 0. Capture, calibration, import and the triplet model know three channels.
7. **A fourth place describes the rig.** The Process panel's Scanning Setup wizard asks camera or scanner, white or narrowband, to set Linear RAW and Narrowband. A capture made in the Scan tab already knows both answers.
8. **The first-run card is a wall of disabled controls.** With no preset selected, the Preset & Light card shows four grayed sliders, a grayed Capture mode, three grayed steppers reading "—" and two grayed header icons. The only instruction is the gate hint under the footer, "To scan: select or create a preset", and the dropdown it points at lists an action and three white-light entries.
9. **An action sits in the dropdown as a value.** In manual mode the combo reads "+ Create a manual preset…" as its current selection.
10. **One light, two numbers.** Under a calibrated recipe the sliders read the scan levels while the status line reads the framing light, dimmed three stops. Nothing says which is which.
11. **White hides the exposure.** A white-light preset removes the EXPOSURE block from the card. ISO and shutter then live only in the Live View window's toolbar, and the card gives no pointer to it. Channel Delay stays visible, with nothing to delay.
12. **The vocabulary exists twice already.** The Roll tab's Film Mode card is a `SegmentedChoice` of Color, B&W and Slide, the process modes a capture imports into. The Film Scanner card's Film & Quality has an **IR** `labeled_toggle`. The Camera side reuses neither.
13. **The Output card can sit below the fold.** On a laptop-height window the camera cards fill the scroll area and the gate hint names a folder control the user has not seen.

Branch `feat/scan-meter-channel-capture` adds, on top of this state: an **Aperture Priority Meter** beside the CAMERA EXPOSURE subheader, which runs the Live View probe under the scan light and overrides a preset's shutter for the session; **R**, **G**, **B** and **IR** selections in Live View, which Scan shoots into the next frame and Retake re-shoots on the current one, every replaced file first kept as a hidden `.previous-` copy; an **IR Shutter** stepper with an **Infrared** toggle, which ends every Scan with an infrared exposure; three built-in presets that need no calibration, **Trichrome, Color Negative**, **Trichrome + IR, Color Negative** and **White Light, Slide + IR**; and a **+** menu with **Calibrate on the Film Base…** and **Set by Hand** in place of the dropdown's manual entry, so a hand-set recipe scans without a save. The IR byte of `SET_COLOR` is live and gated on the light's hardware id. The exposure steppers are editable under every preset and fill from the connection poll, which publishes the held body's settings while no preview streams, so a preset picked before Live View shows the body's exposure at once. The Capture Delay of the Scanlight card is also a stepper beside Scan in Live View. An `_IR` file stays its own frame; the import of an infrared plane remains Piece A.

### 3.2 Model

Three decisions, each one control:

| Decision | Control | Owns |
|---|---|---|
| What the film is | **Film** | the process mode on import, and whether infrared can see dust through it |
| Which exposures one Scan shoots | **Light** | White: one frame under the W LED. Trichrome: R, G, B. Single RGB: one frame with the three LEDs lit. |
| Whether to add an infrared frame | **Infrared** | one more exposure under the IR LEDs, stored beside the frame, and IR Removal on for the frames it captures |

A **recipe** is the exposure solved for one film stock under one Light and Infrared state: LED levels, a shutter per channel, ISO and aperture, and for Single RGB an optional sensor profile. White has no recipe: its exposure stays the Live View steppers and Meter.

### 3.3 Cards

```
┌ Scanner ─────────────────────────────────────┐
│ [ Film Scanner ]  [ ● Camera ]               │
└──────────────────────────────────────────────┘
┌ Camera ──────────────────────────────────────┐
│ ● Camera (USB)   ● Light   41 °C             │
└──────────────────────────────────────────────┘
┌ Film & Light ─────────────────────────── ⓘ ─┐
│ Film      [ Color | B&W | Slide ]            │
│ Light     [ White | Trichrome | Single RGB ] │
│ [ ✓ Infrared ]  a separate IR plane; turns   │
│                 on IR Removal for the frames │
└──────────────────────────────────────────────┘
┌ Exposure ─────────────────────── ✎  💾  🗑 ⓘ ┐
│ Film stock   [ Ektacolor Pro 400          ▾ ]│
│ Red       ───────────●──  212                │
│ Green     ──────●───────  140                │
│ Blue      ───●──────────   96                │
│ Infrared  ───────────●──  255                │
│ ISO 100 · 1/60 s · f/8                       │
│ [ ⌖ Calibrate… ]                             │
│ Channel Delay ──●──────────  0 ms            │
└──────────────────────────────────────────────┘
┌ Output ──────────────────────────────────────┐
│ unchanged                                    │
└──────────────────────────────────────────────┘
  [ ▶ Live View ]  [ ↻ ]  [ 💡 ]
  [ 📷 Scan ]
```

Factories: `SegmentedChoice` for Film and Light, `labeled_toggle` for Infrared, `ChoiceButton` for Film stock, `CompactSlider` for the levels, `header_button` for edit, save and delete, `labeled_action(primary=True)` for Calibrate.

### 3.4 Behavior per control

| Control | Choices | Effect |
|---|---|---|
| Film | the Roll tab's Film Mode choices, Color, B&W and Slide, with the same icons | Process on import, and the captured roll's Film Mode card shows the same value. Grays Infrared for B&W with the Film Scanner card's "blocks infrared" hint. |
| Light | White, Trichrome, Single RGB | The exposures one Scan shoots. Only White without a Scanlight, with today's "connect the Scanlight to scan in RGB" hint. Trichrome Mode on the roll follows it. |
| Infrared | toggle; needs a Scanlight with IR LEDs | A fourth exposure under the IR LEDs, saved as `<frame>_IR`, and `ir_dust_remove` on for those frames. One toggle: the only reason to shoot infrared is removal, and Retouch turns it off per frame. |
| Film stock | recipes solved for the current Light and Infrared state | Recall of levels, shutters, ISO and aperture, read-only. With no recipe the card is grayed under one hint, "Calibrate on the film base, or edit by hand". Under White the card holds one hint instead: "Exposure is set in Live View; Meter sets the shutter from the film base." |
| Calibrate… | primary action | The existing window without its Triplet / Single dropdown. It probes the channels Light and Infrared imply and saves under the typed name. **Create Sensor Profile** stays, for Single RGB. |
| ✎ on the Exposure header | edit toggle | Replaces "Create a manual preset…": unlocks the sliders and steppers; 💾 saves as a named stock; 🗑 deletes the selected stock. |
| Channel Delay | slider | Unchanged. Hidden under White and Single RGB. |

Removed: the three built-in white presets, the `_MANUAL_PRESET` sentinel, the sidebar's disabled Capture mode, the calibration window's capture dropdown. The status line's light echo names its subject, "Framing light" or "Scan light". The gate hint's missing item, such as the output folder, scrolls its card into view on click. The Scanning Setup wizard stays for files scanned elsewhere.

### 3.5 Import rules

| Film | Light | Process | Trichrome Mode | Narrowband | Linear RAW | Sensor profile | IR Removal |
|---|---|---|---|---|---|---|---|
| Color negative | White | C-41 | off | off | off | none | with Infrared |
| B&W negative | White | B&W | off | off | off | none | never |
| Slide | White | E-6 | off | off | off | none | with Infrared |
| any | Trichrome | by Film | on | on | on | none | with Infrared |
| any | Single RGB | by Film | off | on | on | the recipe's | with Infrared |

Today every RGB capture imports as C-41 and a white capture may autodetect. Film replaces both rules.

### 3.6 Calibration window

Title "Calibrate Exposure". The name field, the ROI image, the ISO and aperture steppers, the consistency hint, the progress bar and the status line stay. The capture-mode dropdown goes: the run reads Light and Infrared from the panel. With Infrared on, the ladder probes IR as a fourth channel with its own shutter, since an IR-cut filter leaves it far slower than the visible channels. An IR probe that reaches no target stops the run with the existing over/under report, naming the channel.

### 3.7 Data model

| Record | Change |
|---|---|
| `ScanlightSettings` | `film: str`, `light: str`, `infrared: bool` replace `white_mode`, `white_process_mode`, `single_capture`. Legacy values map in `__post_init__`, where the existing mode rename already maps. |
| `ScanlightPreset` | `ir_level`, `shutter_ir`, and the Light it was solved for, so the Film stock list filters by it. `single_capture` becomes that field. |
| `RgbScanConfig` | `ir_path: str = ""`. `is_rgb_triplet` is unchanged; an IR plane is optional. |
| `triplets_by_path` | the stored list grows from `[green, blue]` to `[green, blue, ir]`; readers iterate the list already. |
| `CaptureRequest` | `film`, `light`, `infrared`, `ir_level`, `shutter_ir`. |
| `CaptureResult` | `ir_path: str = ""`; `paths` appends it when set. |
| `_PendingCaptureImport` | `ir_dust_remove: bool`, applied where `process_mode` is applied. |
| `protocol.encode_set_color` | `ir: int = 0`. The firmware refuses IR together with RGB, so the driver raises as it does for W. |

### 3.8 Capture sequence

| Light | Infrared | Exposures, in order | Light per exposure | Files |
|---|---|---|---|---|
| White | off | 1 | W | `<frame>.<raw>` |
| White | on | 2 | W, IR | `<frame>.<raw>`, `<frame>_IR.<raw>` |
| Trichrome | off | 3 | R, G, B | `<frame>_R`, `_G`, `_B` |
| Trichrome | on | 4 | R, G, B, IR | `_R`, `_G`, `_B`, `_IR` |
| Single RGB | off | 1 | R+G+B | `<frame>.<raw>` |
| Single RGB | on | 2 | R+G+B, IR | `<frame>.<raw>`, `<frame>_IR.<raw>` |

The IR RAW decodes to one gray plane, aligns to the primary with `estimate_shift`, and lands in `metadata["ir"]`. From there `has_ir`, IR Removal, the IR overlay and the `_ir.tiff` linear export work unchanged.

### 3.9 Implementation map

Two separable pieces. Piece A is gated by the rig check in section 6.

Piece A, infrared capture:

| Step | Files | Change |
|---|---|---|
| Protocol | `capture/protocol.py`, `capture/scanlight.py`, `capture/base.py`, `simulated/scanlight.py` | `encode_set_color(ir=)`; IR excludes RGB like W; `has_ir_channel(hw_id)` beside `has_white_channel`. |
| Capture | `capture/base.py`, `services/capture/service.py` | `Channel.IR`; `capture_triplet` walks a channel list; `CaptureResult.ir_path`. |
| Calibration | `services/capture/calibration.py`, `presets.py` | IR probed as a fourth channel with its own shutter. |
| Worker | `workers/capture_worker.py` | request fields; `finished` carries the IR path. |
| Import | `rgbscan/models.py`, `assets/triplets.py`, `controller._on_capture_finished` | `ir_path`; the triplet dict the controller hands discovery grows one entry, so grouping never classifies a gray frame. |
| Decode | `rendering/image_processor.py`, `export/linear_output.py`, `widgets/rgb_triplet_dialog.py` | IR RAW to gray plane, aligned, into `metadata["ir"]`; an Infrared row in Edit Triplet. |
| Retouch default | `controller._PendingCaptureImport` | `ir_dust_remove`. |
| Sim | `simulated/gphoto.py` | `_signal` adds an IR term; `images.film` already returns an IR plane with dust. |
| Docs | `USER_GUIDE.md` Scan tab, `CAMERA_SCANNING.md` | one bullet per control, one paragraph for infrared. |

Piece B, the panel:

| Area | Change |
|---|---|
| `ScanlightSettings`, `ScanlightPreset` | section 3.7 |
| `sidebar/scanlight.py` | `_init_ui`, preset handling, gating and `_push_light` rewritten, about a quarter of the file |
| `sidebar/calibration_window.py` | the capture dropdown goes |
| `sidebar/right_panel.py`, `USER_GUIDE.md` | cards become Film & Light and Exposure; `panel:` keys follow |
| Tests | `test_scanlight_sidebar.py` and eight other files reference `preset_combo`, `calib_window`, `capture_btn`, `white_mode` |

Order: the rig check, then Piece A, then Piece B.

## 4. Alternatives considered

| Alternative | Cost | Why it lost |
|---|---|---|
| "RGB + IR" as a fourth Light choice | Trichrome and Single RGB each need an IR twin: five entries | a toggle composes with every light |
| Two toggles, Infrared and IR Removal | a second decision nobody makes differently at scan time | Retouch already turns removal off per frame |
| Keep the one Preset list and add IR entries | the three kinds stay mixed and the list grows | finding 1 stays |
| Film only as a roll property on the Roll tab | the scan cannot pick the process at import; today's white presets do | loses function |
| Film from the Film Scanner's `FILM_TYPES`, with Kodachrome | a fourth choice the Roll tab's Film Mode card cannot show | the Roll tab's three are the process modes the import sets; a Kodachrome roll turns Infrared off by hand |
| A separate Calibrate IR button | a second run per stock | the ladder already loops channels |

## 5. Cross-cutting concerns

Failure modes:

| Condition | What breaks | What the user sees | Mitigation |
|---|---|---|---|
| The camera cannot see 850 nm through its IR-cut filter | the IR probe reads noise | calibration stops, "under-exposed, IR" | the recipe saves without IR; Scan shoots the visible channels; the Infrared hint names the cause |
| Firmware refuses IR together with RGB | nothing; IR is its own shot | nothing | IR lit alone, like W |
| IR plane misaligned to the primary | IR Removal marks clean film | specks beside dust | `estimate_shift` on the IR plane; **Align channels** in Edit Triplet |
| A Scanlight without IR LEDs, such as a v4 | Infrared has no effect | the toggle grayed with "this Scanlight has no infrared LEDs" | `has_ir_channel(hw_id)` |
| Settings or presets saved by today's build | unknown keys | nothing | `__post_init__` mapping |

Thumbnails: no bump of `THUMBNAIL_RENDER_VERSION`. Existing frames have no IR plane, and a new capture carries `ir_dust_remove` as a saved setting, not a changed default.

## 6. Open questions

| Question | Proposed default | Decider |
|---|---|---|
| Does the stock A7R5 see 850 nm? jackw01 states an IR-converted camera is needed ([issue #3](https://github.com/jackw01/scanlight/issues/3)). | Answered 2026-10-16: no. An IR exposure at 1 s, ISO 100, f/8 peaks at 0.16% of full scale against 12% for the red exposure, and the film area reads at noise level while the black holder reads brightest, so the sensor sees the LED's long-wave tail through the IR-cut filter and nothing of the film. Piece A's import waits for a body without that filter; the Infrared toggle stays for lights and bodies that can use it. | jond |
| IR shutter: shared with the visible channels or its own? | its own | jond |
| Name for a per-stock recipe: "Film stock" or "Preset"? | Film stock | jond |
| Infrared default when the light has IR LEDs? | on for Color negative and Slide | jond |
