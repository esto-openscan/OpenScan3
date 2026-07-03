# Debian Packaging

This is the first pragmatic Debian packaging milestone for the OpenScan3
firmware runtime. The package is intentionally small: it bundles a Python
wheelhouse at build time and creates the runtime virtual environment during
package installation.

## Build

From this directory, install the Debian build tooling and run:

```sh
dpkg-buildpackage -us -uc -b
```

The build reads the firmware version from `pyproject.toml`, builds a wheel for
the local `openscan-firmware` package, and asks `pip wheel` to build or download
wheels for the runtime dependencies declared in `pyproject.toml`.

Build-time network access may be required for this milestone because the
wheelhouse is assembled during the Debian package build. Package installation on
the target device must not need network access.

Expected build dependencies include:

```sh
debhelper
libcap-dev
python3
python3-pip
python3-venv
```

Some runtime dependencies include native or Raspberry Pi specific packages, such
as `picamera2`, `gphoto2`, `rpi.gpio`, and `zxing-cpp`. Building the wheelhouse
can fail if compatible wheels, headers, or native build tools are unavailable for
the build architecture. `libcap-dev` is required to build the `python-prctl`
wheel pulled in by `picamera2`.

## Installed Layout

The package installs release artifacts under:

```text
/opt/openscan3/releases/<version>/
/opt/openscan3/releases/<version>/wheels/
/opt/openscan3/releases/<version>/venv/
/opt/openscan3/current -> /opt/openscan3/releases/<version>
```

Application release directories under `/opt/openscan3/releases` are owned by
`root:root`.

Writable runtime paths are:

```text
/etc/openscan3
/var/openscan3
/var/openscan3/projects
/var/openscan3/community-tasks
/var/log/openscan3
```

These directories are created as `openscan:openscan` with mode `2775`. If
`setfacl` is available, `postinst` also applies default group-writable ACLs. The
package creates the `openscan` system user and group when they do not already
exist.

During `postinst`, bundled default settings are copied from the release
directory into `/etc/openscan3/{device,firmware,logging}` only when the target
file does not already exist. The mutable active device configuration
`device_config.json` is intentionally not shipped as a default preset; the
firmware creates or updates it as runtime state.

## Wheelhouse And Venv Installation

The generated `.deb` contains all wheels under:

```text
/opt/openscan3/releases/<version>/wheels/
```

It also contains package defaults under:

```text
/opt/openscan3/releases/<version>/default-settings/
```

During `postinst`, the package creates a fresh virtual environment with:

```sh
python3 -m venv --system-site-packages /opt/openscan3/releases/<version>/venv
```

It then installs the firmware from the bundled wheelhouse only:

```sh
/opt/openscan3/releases/<version>/venv/bin/python -m pip install \
  --no-index \
  --find-links=/opt/openscan3/releases/<version>/wheels \
  openscan-firmware==<version>
```

No dependency download is performed during target package installation.

## Systemd Service

The package installs the service as:

```text
/lib/systemd/system/openscan3.service
```

The service name intentionally remains `openscan3.service`. Its runtime command
is:

```sh
/opt/openscan3/current/venv/bin/openscan-firmware serve --root-path /api --reload-trigger
```

`postinst` runs `systemctl daemon-reload` when systemd is available and uses
`systemctl try-restart openscan3.service` so development installs do not
unexpectedly start the service.

## Package Responsibilities

```text
openscan3-firmware = backend application code and openscan3.service
openscan3-client = SPA assets under /usr/share/openscan3-client/
openscan3-updater = /usr/bin/openscan-updater and updater Python code
openscan3-camera-stack = tested camera stack marker provided by variant packages
openscan3-system-config = nginx, APT source/key, policy, sudoers, tmpfiles, logrotate
```

`openscan3-firmware` owns the mechanical runtime installation: release
directory, bundled wheelhouse, virtual environment, runtime directories, current
symlink, and systemd unit. It does not own nginx configuration.

`openscan3-system-config` owns the appliance integration layer that used to live
in pi-gen or temporarily in this firmware package. It installs the nginx site,
OpenScan APT public key/source, update policy defaults, sudoers bridge,
tmpfiles directories, and logrotate defaults. It intentionally does not ship
PHP, `/admin` updater routes, firmware backend code, webclient assets, updater
implementation code, or camera-stack artifacts.

## pi-gen, openscan3-firmware.deb, And openscan3-updater

The pi-gen image installs the signed APT packages for the OpenScan runtime and
system integration. It keeps a bootstrap copy of the public OpenScan APT key and
source file only so it can install `openscan3-system-config`; after installation,
those paths are package-owned by `openscan3-system-config`.

`openscan3-updater` is not implemented here. It should later decide if and when
an upgrade is installed. The updater must not mutate the active virtual
environment with `pip install -U`; package installation owns the venv contents.

## Known Limitations

This milestone does not split dependencies between APT-managed and venv-managed
Python packages. `pyproject.toml` remains the source of truth for runtime Python
dependencies.

The venv still uses `--system-site-packages` for compatibility with the current
Raspberry Pi image.

On a bare Raspberry Pi OS Lite image, importing `picamera2` also requires system
bindings such as `python3-libcamera` and `python3-kms++` to be installed. The
current pi-gen image may already provide these; this first milestone does not
model those runtime system dependencies completely.

Older release pruning is intentionally not implemented yet. Keeping only the
current and previous releases should wait until release-retention policy is
defined independently from repair.

Legacy pi-gen paths are not removed:

```text
/opt/openscan3-src
/usr/local/bin/openscan3
/usr/local/sbin/openscan3-update
/opt/openscan3/venv
```

If `/opt/openscan3/current` already exists as a non-symlink, `postinst` leaves it
unchanged and reports the conflict instead of deleting it.
