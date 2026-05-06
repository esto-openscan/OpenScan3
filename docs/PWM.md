# PWM in OpenScan3

This is a short developer note about the PWM abstraction used in OpenScan3.

## Summary

OpenScan3 handles light intensity as a percentage (`0..100`) at controller/API level, then maps that value to a PWM duty cycle (`0..1`) based on configured voltage bounds (`pwm_min`, `pwm_max`).

Main modules:

- `openscan_firmware/controllers/hardware/lights.py`
  - Owns brightness state (`value` in percent) and mapping logic.
- `openscan_firmware/controllers/hardware/gpio.py`
  - Selects hardware PWM when available, otherwise software PWM fallback.
- `openscan_firmware/utils/pwm_hardware.py`
  - Low-level hardware PWM implementation for Raspberry Pi (`/sys/class/pwm` + pinctrl).

## Raspberry Pi Setup Requirement

For hardware PWM support, add the following to `/boot/firmware/config.txt`:

```txt
dtparam=audio=off
dtoverlay=pwm-2chan
```

Important:

- PWM and onboard audio are mutually exclusive with this setup.
- If audio is required, use a separate external PWM chip on the board.

## Practical Note

`pwm_hardware.py` is the utility-layer solution for hardware PWM.  
As long as the boot config above is applied, the rest is handled by the OpenScan3 abstraction.
