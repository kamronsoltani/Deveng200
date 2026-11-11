# Deveng200 — Flow + Pressure Monitor (XIAO ESP32-C3)

Embedded firmware for a Seeed XIAO ESP32-C3 that measures water flow and two pressures for a water-treatment test setup. Live values show on a small OLED and over USB serial. **Flow is calibrated. Pressure is not calibrated yet** - that is the main handoff for the next person.

## Repo layout

```
├── platformio.ini          PlatformIO env for seeed_xiao_esp32c3
├── src/main.cpp            Firmware (flow + pressure + OLED + serial)
├── tools/
│   ├── flow_monitor_gui.py Live plot / record from the monitor firmware
│   └── flowcal_gui.py      Gravimetric flow-calibration helper GUI
├── data/
│   └── CALIBRATION_FLOW_TRIAL_1.csv   13-point flow calibration runs
├── requirements.txt        Python deps for the GUIs
└── README.md
```

## Hardware

| Part | Detail |
|---|---|
| Board | Seeed XIAO ESP32-C3 (PlatformIO `seeed_xiao_esp32c3`, Arduino) |
| Display | SSD1306 128×32 OLED over I2C, mounted rotated 180° (`U8G2_R2`) |
| Flow | Pulse turbine, signal → GPIO21, internal pull-up, falling-edge ISR |
| Pressure | Two ratiometric transducers (red = supply, black = GND, green = signal) |
| Button | GPIO6 (D4) → GND, internal pull-up, 200 ms debounce in ISR |

### Pressure sensors

- **P1:** 100 psi, GPIO3 (D1)
- **P2:** 20 psi, GPIO4 (D2)
- Output assumed **10%–90% of supply = 0 to full scale**
- Currently assumed **3.3 V supply** — **unverified**. If they need 5 V, the green output (up to ~4.5 V) must go through a divider (e.g. 10k/22k) before the ADC pin.

### Pin map (GPIO)

| Function | GPIO | XIAO label |
|---|---|---|
| OLED SDA | 20 | D7 |
| OLED SCL | 8 | D8 |
| Button | 6 | D4 |
| Pressure 1 | 3 | D1 |
| Pressure 2 | 4 | D2 |
| Flow signal | 21 | D6 |

Notes:

- GPIO2 (D0) was unreliable for flow during bring-up → flow is on GPIO21.
- Only D0–D3 (GPIO2–GPIO5) have analog input on this board.
- Avoid GPIO9 (boot strap pin).

## Build & flash (firmware)

Requires [PlatformIO](https://platformio.org/).

```bash
pio run -t upload
pio device monitor
```

Serial: **115200** baud.

**Windows path tip:** linking can fail with `collect2.exe: CreateProcess: No such file or directory` if the project lives under a long OneDrive path. Use a short path (e.g. `C:\fm`) and optionally `PLATFORMIO_CORE_DIR=C:\.platformio`.

If the OLED stays blank, `Wire.setPins` may not apply on the installed core. Fall back to software I2C:

```cpp
U8G2_SSD1306_128X32_UNIVISION_F_SW_I2C u8g2(U8G2_R2, PIN_SCL, PIN_SDA, U8X8_PIN_NONE);
```

and remove the three `Wire` lines in `setup()`.

## Run the live GUI

```bash
pip install -r requirements.txt
python tools/flow_monitor_gui.py
```

Pick the XIAO COM port → Connect. The GUI plots L/min and can record a CSV.

`flowcal_gui.py` talks to a **separate calibration sketch** (not in this repo). Use it only if you re-run gravimetric flow calibration with that sketch loaded.

## Behavior (current firmware)

- Updates every **500 ms**. Flow Hz = pulse delta / actual elapsed time.
- Total volume = integral of L/min over time. Reset with serial `r` or on reboot.
- Button cycles OLED pages:
  - **Page 0:** flow summary (Hz, L/min, total, P1/P2 psi)
  - **Page 1:** pressure volts, status, psi
- Pressure status: `NO SIG` (&lt; 0.15 V), `HIGH` (&gt; 3.05 V), `OK`
- Serial line format (keep the **flow** prefix stable for the GUI regex):

```text
12.30 Hz  21.50 L/min  total 1.234 L  P1 45.20 psi  P2 3.10 psi  (1.234V OK, 0.800V OK)
```

GUI regex (flow only today):

```text
([\d.]+)\s*Hz\s+([\d.]+)\s*L/min\s+total\s+([\d.]+)\s*L
```

## Flow calibration (done)

Gravimetric method: capture pulses between two button presses, weigh water (grams / 0.998 g/mL), time with a stopwatch, compute Hz and pulses per liter.

- 13 runs, **6.4–18.4 Hz** (see `data/CALIBRATION_FLOW_TRIAL_1.csv`)
- One outlier (~8.48 Hz, 39.35 pulses/L) was deleted
- Fit used in firmware:

```text
pulses per liter = 0.31824 * Hz + 28.929
L/min = Hz * 60 / pulses per liter
```

- Fit error on the 13 points: ~**3.1% RMS**, ~**6.4% max**
- Most scatter is stopwatch error on short runs (1 kg ≈ 3–5 s at these flows)
- Below **6 Hz** is untested; OLED appends `~` after L/min there
- Above ~18.4 Hz the line **extrapolates** — verify before relying on it
- Valid only for **this** sensor, tubing, and orientation — recalibrate if any change
- A piecewise-linear table was tried and rejected (jumpy given per-run scatter)

## Pressure calibration (TODO — primary handoff)

Values are uncalibrated and use the nominal ratiometric formula in `src/main.cpp`:

```cpp
psi = (v / SUPPLY_V - 0.10f) / 0.80f * fullScale;
```

Suggested procedure:

1. Measure real supply voltage with a multimeter → set `SUPPLY_V`.
2. Check green output at zero pressure (~10% of supply).
3. Zero both sensors at atmospheric pressure (offset).
4. Check span against a reference gauge at **≥3** pressures → apply gain.
5. Prefer mid-range pressures; ESP32 ADC is less linear near the ends.

Expected accuracy after calibration (rough): **±1 psi** on the 100 psi sensor, **±0.3 psi** on the 20 psi sensor.

### Suggested firmware / tooling next steps

1. Move constants into `config.h`; store pressure zero/gain in **Preferences (NVS)**.
2. Add serial commands for pressure zeroing and span calibration.
3. Add pressure columns (and plots) to `tools/flow_monitor_gui.py`.
4. Add a CSV logging mode with timestamped flow **and** pressure.
5. Re-run flow calibration at low flow (&lt;6 Hz) with longer runs (≥5 kg) to cut timing error.
6. Fix GUI “Reset device total” to send serial `r` (firmware already supports it; button currently only shows a message).

## Known issues

- Windows long-path link failures under OneDrive — use a short project path.
- `volatile` increment warning on `pulseCount++` is harmless.
- Monitor GUI does not parse pressure yet (pressure is already on the serial line).

## License / ownership

Internal lab / course handoff for DEVENG 200 water-treatment test setup. Iterate freely for that purpose.
