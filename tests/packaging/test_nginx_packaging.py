import json
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def package_dependency_names() -> set[str]:
    control = (ROOT / "debian" / "control").read_text()
    package = control.split("\nPackage: openscan3-firmware\n", maxsplit=1)[1]
    depends = package.split("\nDescription:", maxsplit=1)[0]

    names: set[str] = set()
    for line in depends.splitlines():
        stripped = line.strip()
        if not stripped or stripped in {"Architecture: any", "Depends:"}:
            continue
        names.add(stripped.rstrip(",").split()[0])
    return names


def test_firmware_does_not_install_package_owned_nginx_config() -> None:
    assert not (ROOT / "debian" / "openscan3.conf").exists()
    assert (
        "debian/openscan3.conf etc/nginx/sites-available/"
        not in (ROOT / "debian" / "install").read_text()
    )


def test_firmware_does_not_depend_on_nginx_or_php_fpm() -> None:
    dependencies = package_dependency_names()

    assert "nginx" not in dependencies
    assert "php-fpm" not in dependencies


def test_postinst_does_not_manage_nginx_site() -> None:
    postinst = (ROOT / "debian" / "postinst").read_text()

    assert "NGINX_SITE_AVAILABLE" not in postinst
    assert "nginx -t" not in postinst
    assert "systemctl reload nginx.service" not in postinst
    assert "systemctl restart nginx.service" not in postinst


def test_firmware_service_upgrade_restart_is_stateful() -> None:
    preinst = (ROOT / "debian" / "preinst").read_text()
    postinst = (ROOT / "debian" / "postinst").read_text()
    rules = (ROOT / "debian" / "rules").read_text()

    assert "systemctl is-active --quiet openscan3.service" in preinst
    assert "openscan3.service-was-active" in preinst
    assert "#DEBHELPER#" in preinst
    assert "dh_installsystemd --no-start" in rules
    assert "dh_installsystemd --no-enable" not in rules
    assert "systemctl enable openscan3.service" not in postinst
    assert "systemctl start openscan3.service || true" in postinst
    assert "systemctl restart openscan3.service" in postinst
    assert "systemctl try-restart openscan3.service || true" in postinst


def test_packaged_service_uses_current_release_without_reload_supervisor() -> None:
    service = (ROOT / "debian" / "openscan3.service").read_text()

    assert (
        "ExecStart=/opt/openscan3/current/venv/bin/openscan-firmware serve --root-path /api"
        in service
    )
    assert "--reload-trigger" not in service
    assert "/opt/openscan3/venv" not in service


def test_debian_package_bundles_default_settings_without_runtime_device_config() -> None:
    rules = (ROOT / "debian" / "rules").read_text()
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    packaged_device_settings = pyproject["tool"]["setuptools"]["data-files"][
        "openscan_firmware/settings/device"
    ]

    assert "$(RELEASE_DIR)/default-settings/device" in rules
    assert "settings/device/default_*.json" in rules
    assert "settings/device/example_custom.json" in rules
    assert "settings/firmware/*.json" in rules
    assert "settings/logging/*.json" in rules
    assert "settings/device/device_config.json" not in rules
    assert "settings/device/device_config.json" not in packaged_device_settings


def test_postinst_seeds_default_settings_without_overwriting_runtime_files() -> None:
    postinst = (ROOT / "debian" / "postinst").read_text()

    assert "python_package_version" not in postinst
    assert "sed -E" not in postinst
    assert "RELEASE_METADATA=\"/usr/share/openscan3-firmware/release.json\"" in postinst
    assert "python_version=\"$(bundled_python_version \"$version\")\"" in postinst
    assert "seed_default_settings \"$python_version\"" in postinst
    assert "install_release_venv \"$python_version\"" in postinst
    assert "update_current_link \"$python_version\"" in postinst
    assert "default-settings" in postinst
    assert "create_runtime_dir /etc/openscan3/device" in postinst
    assert "create_runtime_dir /etc/openscan3/firmware" in postinst
    assert "create_runtime_dir /etc/openscan3/logging" in postinst
    assert "if [ -e \"$target_file\" ]; then" in postinst
    assert "install -o \"$RUNTIME_USER\" -g \"$RUNTIME_GROUP\" -m 0664" in postinst


def test_release_metadata_writer_records_one_validated_nightly_identity(tmp_path: Path) -> None:
    output = tmp_path / "release.json"
    command = [
        "python3",
        str(ROOT / "scripts" / "write-release-metadata.py"),
        "--output",
        str(output),
        "--channel",
        "nightly",
        "--debian-version",
        "0.11.11~nightly.20260722152803.g2498e42",
        "--python-version",
        "0.11.11.dev20260722152803+g2498e42",
        "--build-timestamp",
        "20260722152803",
        "--source-revision",
        "2498e42",
        "--expected-debian-version",
        "0.11.11~nightly.20260722152803.g2498e42",
        "--expected-python-version",
        "0.11.11.dev20260722152803+g2498e42",
    ]

    subprocess.run(command, check=True)

    assert json.loads(output.read_text()) == {
        "schema": 1,
        "channel": "nightly",
        "debian_version": "0.11.11~nightly.20260722152803.g2498e42",
        "python_version": "0.11.11.dev20260722152803+g2498e42",
        "build_timestamp": "20260722152803",
        "source_revision": "2498e42",
    }


def test_release_metadata_writer_rejects_mixed_nightly_identity(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "write-release-metadata.py"),
            "--output",
            str(tmp_path / "release.json"),
            "--channel",
            "nightly",
            "--debian-version",
            "0.11.11~nightly.20260722152803.g2498e42",
            "--python-version",
            "0.11.11.dev20260722152931+g2498e42",
            "--build-timestamp",
            "20260722152803",
            "--source-revision",
            "2498e42",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Python version does not match" in result.stderr


def test_postinst_reads_exact_python_version_from_release_metadata(tmp_path: Path) -> None:
    metadata = tmp_path / "release.json"
    metadata.write_text(
        json.dumps(
            {
                "schema": 1,
                "channel": "nightly",
                "debian_version": "0.11.11~nightly.20260722152803.g2498e42",
                "python_version": "0.11.11.dev20260722152803+g2498e42",
                "build_timestamp": "20260722152803",
                "source_revision": "2498e42",
            }
        )
    )
    postinst = (ROOT / "debian" / "postinst").read_text()
    function_start = postinst.index("bundled_python_version()")
    function_end = postinst.index("\n}\n", function_start) + len("\n}\n")
    function = postinst[function_start:function_end]

    result = subprocess.run(
        [
            "sh",
            "-c",
            f'{function}\nRELEASE_METADATA="$1" bundled_python_version "$2"',
            "sh",
            str(metadata),
            "0.11.11~nightly.20260722152803.g2498e42",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "0.11.11.dev20260722152803+g2498e42"


def test_postinst_rejects_release_metadata_for_another_debian_package(tmp_path: Path) -> None:
    metadata = tmp_path / "release.json"
    metadata.write_text(
        json.dumps(
            {
                "schema": 1,
                "debian_version": "0.11.11~nightly.20260722152803.g2498e42",
                "python_version": "0.11.11.dev20260722152803+g2498e42",
            }
        )
    )
    postinst = (ROOT / "debian" / "postinst").read_text()
    function_start = postinst.index("bundled_python_version()")
    function_end = postinst.index("\n}\n", function_start) + len("\n}\n")
    function = postinst[function_start:function_end]

    result = subprocess.run(
        [
            "sh",
            "-c",
            f'{function}\nRELEASE_METADATA="$1" bundled_python_version "$2"',
            "sh",
            str(metadata),
            "0.11.11~nightly.20260722152931.g2498e42",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "does not match installed Debian version" in result.stderr


def test_pwm_hardware_does_not_override_process_signal_handlers() -> None:
    pwm_hardware = (ROOT / "openscan_firmware" / "utils" / "pwm_hardware.py").read_text()

    assert "signal.signal" not in pwm_hardware
    assert "_signal_handler" not in pwm_hardware
    assert "atexit.register(_HwPWM._cleanup)" in pwm_hardware


def test_lifespan_logs_shutdown_cleanup() -> None:
    main = (ROOT / "openscan_firmware" / "main.py").read_text()

    assert "OpenScan3 service shutdown: starting hardware cleanup." in main
    assert "device_controller.cleanup_and_exit()" in main
    assert "OpenScan3 service shutdown: hardware cleanup completed." in main
