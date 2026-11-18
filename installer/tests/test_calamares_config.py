from __future__ import annotations

import yaml

from conftest import BRANDING_DIR, CALAMARES_DIR, MODULES_DIR


def _load_yaml(path):
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert isinstance(data, dict), f"{path} did not parse to a YAML mapping"
    return data


def test_all_calamares_yaml_files_parse():
    required_modules = [
        "partition.conf",
        "mount.conf",
        "bootloader.conf",
        "shellprocess.conf",
        "shellprocess_cleanup.conf",
        "unpackfs.conf",
        "fstab.conf",
        "initcpio.conf",
        "users.conf",
    ]
    for name in required_modules:
        assert (MODULES_DIR / name).is_file(), f"Missing module config: {name}"

    yaml_files = [
        CALAMARES_DIR / "settings.conf",
        BRANDING_DIR / "branding.desc",
        *sorted(MODULES_DIR.glob("*.conf")),
    ]
    for path in yaml_files:
        _load_yaml(path)


def test_settings_sequence_and_branding():
    settings = _load_yaml(CALAMARES_DIR / "settings.conf")
    assert settings["branding"] == "kite-os"
    assert "local" in settings["modules-search"]
    assert settings["dont-chroot"] is False

    sequence = settings["sequence"]
    assert len(sequence) == 3
    assert "show" in sequence[0]
    assert "exec" in sequence[1]
    assert "show" in sequence[2]

    first_show = sequence[0]["show"]
    for page in ("welcome", "locale", "keyboard", "partition", "users", "summary"):
        assert page in first_show

    exec_jobs = sequence[1]["exec"]
    assert exec_jobs.index("partition") < exec_jobs.index("mount")
    assert exec_jobs.index("mount") < exec_jobs.index("bootloader")
    assert exec_jobs.index("mount") < exec_jobs.index("shellprocess")
    assert exec_jobs.index("shellprocess") < exec_jobs.index("umount")
    assert "finished" in sequence[2]["show"]


def test_branding_desc_metadata_and_assets():
    desc = _load_yaml(BRANDING_DIR / "branding.desc")
    assert desc["componentName"] == "kite-os"
    assert desc["slideshowAPI"] == 2
    assert "KITE_OS" in desc["strings"]["productName"]

    style = desc["style"]
    for pascal_key in (
        "SidebarBackground",
        "SidebarText",
        "SidebarTextCurrent",
        "SidebarBackgroundCurrent",
    ):
        assert pascal_key in style, f"Expected PascalCase style key {pascal_key}"

    for key, rel_path in desc["images"].items():
        asset = BRANDING_DIR / rel_path
        assert asset.is_file() and asset.stat().st_size > 0, f"Missing image {key}: {asset}"

    slideshow = BRANDING_DIR / desc["slideshow"]
    assert slideshow.is_file() and slideshow.stat().st_size > 0


def test_partition_and_mount_btrfs_layout():
    part = _load_yaml(MODULES_DIR / "partition.conf")
    assert part["defaultFileSystemType"] == "btrfs"
    assert "btrfs" in part["availableFileSystemTypes"]
    assert part["initialSwapChoice"] == "none"
    assert part["efi"]["mountPoint"] == "/boot/efi"

    mount = _load_yaml(MODULES_DIR / "mount.conf")
    subvols = {entry["subvolume"]: entry["mountPoint"] for entry in mount["btrfsSubvolumes"]}
    expected_subvols = {
        "/@": "/",
        "/@home": "/home",
        "/@kitebridge": "/var/lib/kitebridge",
        "/@snapshots": "/.snapshots",
    }
    assert subvols == expected_subvols
    assert len(mount["btrfsSubvolumes"]) == 4

    btrfs_opts = next(m for m in mount["mountOptions"] if m["filesystem"] == "btrfs")
    for key in ("options", "ssdOptions", "hddOptions"):
        opts = btrfs_opts[key]
        assert "compress=zstd:1" in opts, f"compress=zstd:1 missing in mountOptions.{key}"
        assert "noatime" in opts, f"noatime missing in mountOptions.{key}"


def test_bootloader_haswell_kernel_params():
    boot = _load_yaml(MODULES_DIR / "bootloader.conf")
    assert boot["efiBootLoader"] == "grub"
    assert boot["efiBootloaderId"] == "kite-os"
    assert boot["installEFIFallback"] is True

    params = set(boot["kernelParams"])
    for required in (
        "quiet",
        "i915.enable_fbc=1",
        "i915.fastboot=1",
        "intel_pstate=active",
        "psi=1",
    ):
        assert required in params, f"Missing kernel param: {required}"


def test_shellprocess_services_and_driver_pins():
    sp = _load_yaml(MODULES_DIR / "shellprocess.conf")
    assert sp["dontChroot"] is False
    joined = "\n".join(sp["script"])
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in joined
    assert "LIBVA_DRIVER_NAME=i965" in joined
    assert "/etc/environment.d/10-kite-haswell.conf" in joined
    assert "/var/lib/kitebridge" in joined
    assert "kite-hw-tune.service" in joined
    assert "kite-power.service" in joined


def test_pre_initcpio_archiso_cleanup_configured():
    settings = _load_yaml(CALAMARES_DIR / "settings.conf")
    instances = settings.get("instances", [])
    cleanup_inst = [
        inst
        for inst in instances
        if isinstance(inst, dict) and inst.get("id") == "cleanup"
    ]
    assert len(cleanup_inst) == 1, "settings.conf must declare instances id='cleanup'"
    assert cleanup_inst[0]["module"] == "shellprocess"
    assert cleanup_inst[0]["config"] == "shellprocess_cleanup.conf"

    exec_jobs = settings["sequence"][1]["exec"]
    assert "shellprocess@cleanup" in exec_jobs
    assert (
        exec_jobs.index("unpackfs")
        < exec_jobs.index("shellprocess@cleanup")
        < exec_jobs.index("initcpiocfg")
        < exec_jobs.index("initcpio")
    )

    cleanup_conf = _load_yaml(MODULES_DIR / "shellprocess_cleanup.conf")
    assert cleanup_conf["dontChroot"] is False
    assert cleanup_conf["timeout"] == 60
    joined = "\n".join(cleanup_conf["script"])
    assert "/etc/mkinitcpio.conf.d/archiso.conf" in joined
    assert "/usr/lib/initcpio/hooks/archiso" in joined
    assert "/usr/lib/initcpio/install/archiso" in joined


def test_completeness_modules():
    unpack = _load_yaml(MODULES_DIR / "unpackfs.conf")
    assert unpack["unpack"][0]["sourcefs"] == "squashfs"

    fstab = _load_yaml(MODULES_DIR / "fstab.conf")
    assert "tmpOptions" in fstab

    initcpio = _load_yaml(MODULES_DIR / "initcpio.conf")
    assert initcpio["kernel"] == "linux-cachyos"

    users = _load_yaml(MODULES_DIR / "users.conf")
    assert users["sudoersGroup"] == "wheel"
    groups = {
        g["name"] if isinstance(g, dict) else g
        for g in users["defaultGroups"]
    }
    for req in ("wheel", "kvm", "input", "video", "audio"):
        assert req in groups, f"Missing default group: {req}"
