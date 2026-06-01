#!/usr/bin/env bash

set -u

print_section() {
  local title="$1"
  printf "\n===== %s =====\n" "$title"
}

run_command() {
  local description="$1"
  shift
  print_section "$description"
  printf "+ %s\n" "$*"
  "$@" 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    printf "[exit-code] %s\n" "$rc"
  fi
}

run_if_available() {
  local binary="$1"
  shift
  local description="$1"
  shift
  if command -v "$binary" >/dev/null 2>&1; then
    run_command "$description" "$@"
  else
    print_section "$description"
    printf "%s not found in PATH\n" "$binary"
  fi
}

run_python_probe() {
  local description="$1"
  shift
  print_section "$description"
  "${OPENSCAN_REPORT_PYTHON:-python3}" - "$@" 2>&1
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    printf "[exit-code] %s\n" "$rc"
  fi
}

run_camera_hello_probe() {
  local binary="$1"
  local description="$2"

  print_section "$description"
  if ! command -v "$binary" >/dev/null 2>&1; then
    printf "%s not found in PATH\n" "$binary"
    return
  fi

  printf "+ %s --version\n" "$binary"
  "$binary" --version 2>&1 || printf "[exit-code] %s\n" "$?"

  printf "\n+ %s --list-cameras\n" "$binary"
  local list_output
  list_output="$("$binary" --list-cameras 2>&1)"
  local rc=$?
  printf "%s\n" "$list_output"
  if [ "$rc" -ne 0 ]; then
    printf "[exit-code] %s\n" "$rc"
    return
  fi

  local camera_indices=()
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*([0-9]+)[[:space:]]*: ]]; then
      camera_indices+=("${BASH_REMATCH[1]}")
    fi
  done <<< "$list_output"

  if [ "${#camera_indices[@]}" -eq 0 ]; then
    echo "No cameras listed by $binary"
    return
  fi

  for idx in "${camera_indices[@]}"; do
    printf "\n--- %s camera %s hello probe ---\n" "$binary" "$idx"
    printf "+ timeout 12s %s --camera %s --timeout 2000 --nopreview\n" "$binary" "$idx"
    timeout 12s "$binary" --camera "$idx" --timeout 2000 --nopreview 2>&1
    rc=$?
    if [ "$rc" -ne 0 ]; then
      printf "[exit-code] %s\n" "$rc"
    fi
  done
}

printf "OpenScan Camera Report\n"
printf "Generated: %s\n" "$(date --iso-8601=seconds)"
printf "Host: %s\n" "$(hostname)"
printf "Kernel: %s\n" "$(uname -srmo)"

run_python_probe "OpenScan firmware package info" <<'PY'
import importlib
from importlib.metadata import PackageNotFoundError, version

packages = [
    ("openscan-firmware", "openscan_firmware"),
    ("picamera2", "picamera2"),
    ("linuxpy", "linuxpy"),
    ("gphoto2", "gphoto2"),
]
for package, module_name in packages:
    try:
        package_version = version(package)
    except PackageNotFoundError:
        package_version = "distribution metadata not found"

    try:
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", "built-in")
        import_status = f"import ok ({module_file})"
    except Exception as exc:
        import_status = f"import failed: {exc}"

    print(f"{package}: {package_version}; module {module_name}: {import_status}")
PY
run_command "Python runtime" "${OPENSCAN_REPORT_PYTHON:-python3}" --version
run_command "OpenScan service status" bash -lc 'systemctl status --no-pager -l openscan3.service 2>&1 || true'
run_command "OpenScan service journal excerpts" bash -lc 'journalctl -u openscan3.service -n 160 --no-pager 2>&1 || true'
run_command "Camera ownership diagnostics" bash -lc 'ps -eo pid,ppid,stat,comm,args | egrep "openscan3|python|CameraManager|IPAProxy|rpicam|libcamera" | egrep -v "egrep" || true; if command -v fuser >/dev/null 2>&1; then fuser -v /dev/video* /dev/media* 2>&1 || true; else echo "fuser not found in PATH"; fi'
run_if_available "v4l2-ctl" "V4L2 device overview" v4l2-ctl --list-devices
run_command "Video and media device nodes" bash -lc 'ls -l /dev/video* /dev/media* 2>/dev/null || echo "No /dev/video* or /dev/media* nodes found"'
run_camera_hello_probe "rpicam-hello" "rpicam-hello camera probes"
run_camera_hello_probe "libcamera-hello" "libcamera-hello legacy camera probes"
run_if_available "lsusb" "USB device tree" lsusb -t
run_if_available "lsusb" "USB device list" lsusb
run_if_available "usb-devices" "USB devices (kernel view)" usb-devices
run_command "Kernel camera/video log excerpts" bash -lc 'dmesg | egrep -i "camera|video|uvc|bcm2835|unicam" | tail -n 200'
run_command "Kernel USB log excerpts" bash -lc 'dmesg | egrep -i "usb|xhci|dwc2|dwc_otg|hub|mtp|ptp" | tail -n 200'
run_command "Boot firmware config (/boot/firmware/config.txt)" bash -lc 'if [ -f /boot/firmware/config.txt ]; then sed -n "1,240p" /boot/firmware/config.txt; else echo "/boot/firmware/config.txt not found"; fi'

if command -v v4l2-ctl >/dev/null 2>&1; then
  print_section "Per-device V4L2 details"
  shopt -s nullglob
  video_devices=(/dev/video*)
  shopt -u nullglob

  if [ "${#video_devices[@]}" -eq 0 ]; then
    echo "No /dev/video* devices found"
  else
    for dev in "${video_devices[@]}"; do
      printf "\n--- %s ---\n" "$dev"
      v4l2-ctl -d "$dev" --all 2>&1 | head -n 80
    done
  fi
fi

if command -v udevadm >/dev/null 2>&1; then
  print_section "udev info for /dev/video*"
  shopt -s nullglob
  video_devices=(/dev/video*)
  shopt -u nullglob
  if [ "${#video_devices[@]}" -eq 0 ]; then
    echo "No /dev/video* devices found"
  else
    for dev in "${video_devices[@]}"; do
      printf "\n--- %s ---\n" "$dev"
      udevadm info --query=all --name="$dev" 2>&1 | head -n 120
    done
  fi
else
  print_section "udev info for /dev/video*"
  echo "udevadm not found in PATH"
fi
