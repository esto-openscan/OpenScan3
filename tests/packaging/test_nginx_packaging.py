from pathlib import Path
import tomllib


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

    assert "systemctl is-active --quiet openscan3.service" in preinst
    assert "openscan3.service-was-active" in preinst
    assert "#DEBHELPER#" in preinst
    assert "systemctl enable openscan3.service" in postinst
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

    assert "seed_default_settings \"$version\"" in postinst
    assert "default-settings" in postinst
    assert "create_runtime_dir /etc/openscan3/device" in postinst
    assert "create_runtime_dir /etc/openscan3/firmware" in postinst
    assert "create_runtime_dir /etc/openscan3/logging" in postinst
    assert "if [ -e \"$target_file\" ]; then" in postinst
    assert "install -o \"$RUNTIME_USER\" -g \"$RUNTIME_GROUP\" -m 0664" in postinst


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
