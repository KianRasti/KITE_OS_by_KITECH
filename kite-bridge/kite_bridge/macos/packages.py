"""Apple .pkg archive inspection & extraction via xar, pkgutil, pbzx, and darling."""

from __future__ import annotations

import hashlib
import shlex
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from ..abstractions import (
    LocalPrefixFilesystem,
    PrefixFilesystem,
    ProcessRunner,
    SubprocessRunner,
)
from ..config import BridgeConfig
from ..models import BridgeError, MissingToolError, PkgInspectResult


class PkgHandler:
    """Inspects and extracts Apple flat/component .pkg installers."""

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        fs: PrefixFilesystem | None = None,
        config: BridgeConfig | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.fs = fs or LocalPrefixFilesystem()
        self.config = config or BridgeConfig.from_env()

    def inspect_pkg(self, pkg_path: str) -> PkgInspectResult:
        xar_bin = self.runner.which("xar")
        pkgutil_bin = self.runner.which("pkgutil")
        entries: list[str] = []
        staging = self._staging_dir(pkg_path)
        if xar_bin:
            res = self.runner.run([xar_bin, "-tf", pkg_path])
            if res.returncode != 0:
                raise BridgeError(f"xar -tf failed ({res.returncode}): {res.stderr}")
            entries = [line.strip() for line in res.stdout.splitlines() if line.strip()]
            meta_entries = [
                e for e in entries if PurePosixPath(e).name in ("Distribution", "PackageInfo")
            ]
            if meta_entries:
                self.fs.mkdir(staging, parents=True)
                self.runner.run([xar_bin, "-xf", pkg_path, "-C", staging, *meta_entries], check=False)
        elif pkgutil_bin:
            res = self.runner.run([pkgutil_bin, "--expand", pkg_path, staging])
            if res.returncode != 0:
                raise BridgeError(f"pkgutil --expand failed ({res.returncode}): {res.stderr}")
            entries = self.fs.glob(staging, "**/*")
        else:
            raise MissingToolError("xar", "Install `xar` or `darling` to inspect .pkg archives.")

        pkg_format = "product-archive" if any(e.endswith("Distribution") for e in entries) else "component-pkg"
        apps_found = sorted({e for e in entries if e.endswith(".app") or ".app/" in e})
        identifier: str | None = None
        version: str | None = None
        title: str | None = None

        # Parse Distribution or PackageInfo XML if staged on filesystem
        dist_path = f"{staging}/Distribution"
        pkg_info_path = f"{staging}/PackageInfo"
        if self.fs.exists(dist_path):
            identifier, version, title = self._parse_distribution_xml(self.fs.read_text(dist_path))
        elif self.fs.exists(pkg_info_path):
            identifier, version, title = self._parse_package_info_xml(self.fs.read_text(pkg_info_path))
        else:
            for entry in entries:
                if entry.endswith("/PackageInfo") and self.fs.exists(f"{staging}/{entry}"):
                    identifier, version, title = self._parse_package_info_xml(
                        self.fs.read_text(f"{staging}/{entry}")
                    )
                    if identifier or version:
                        break

        return PkgInspectResult(
            pkg_path=pkg_path,
            package_format=pkg_format,
            identifier=identifier,
            version=version,
            title=title,
            apps_found=apps_found,
            entries=entries,
        )

    def extract_pkg(
        self,
        pkg_path: str,
        dest_dir: str,
        *,
        use_darling_installer: bool = False,
    ) -> PkgInspectResult:
        if use_darling_installer:
            darling_bin = self.runner.which("darling")
            if not darling_bin:
                raise MissingToolError("darling", "Install Darling to run `installer -pkg`.")
            res = self.runner.run([darling_bin, "shell", "installer", "-pkg", pkg_path, "-target", "/"])
            if res.returncode != 0:
                raise BridgeError(f"darling installer failed ({res.returncode}): {res.stderr}")
            return PkgInspectResult(
                pkg_path=pkg_path,
                package_format="darling-installer",
                identifier=None,
                version=None,
                title=PurePosixPath(pkg_path).stem,
                extracted_to="/",
            )

        xar_bin = self.runner.which("xar")
        if not xar_bin:
            raise MissingToolError("xar", "Install `xar` to extract .pkg archives.")

        staging = self._staging_dir(pkg_path)
        self.fs.mkdir(staging, parents=True)
        self.fs.mkdir(dest_dir, parents=True)

        res = self.runner.run([xar_bin, "-xf", pkg_path, "-C", staging])
        if res.returncode != 0:
            raise BridgeError(f"xar -xf failed ({res.returncode}): {res.stderr}")

        entries = self.fs.glob(staging, "**/*")
        payloads = [p for p in entries if PurePosixPath(p).name == "Payload"]
        for payload in payloads:
            self._extract_payload(payload, dest_dir)

        identifier: str | None = None
        version: str | None = None
        title: str | None = None
        if self.fs.exists(f"{staging}/Distribution"):
            identifier, version, title = self._parse_distribution_xml(self.fs.read_text(f"{staging}/Distribution"))
        elif self.fs.exists(f"{staging}/PackageInfo"):
            identifier, version, title = self._parse_package_info_xml(self.fs.read_text(f"{staging}/PackageInfo"))

        apps = self.fs.glob(dest_dir, "**/*.app")
        return PkgInspectResult(
            pkg_path=pkg_path,
            package_format="product-archive" if self.fs.exists(f"{staging}/Distribution") else "component-pkg",
            identifier=identifier,
            version=version,
            title=title,
            apps_found=apps,
            entries=entries,
            extracted_to=dest_dir,
        )

    def _extract_payload(self, payload_path: str, dest_dir: str) -> None:
        header = b""
        if self.fs.exists(payload_path):
            try:
                header = self.fs.read_head_tail(payload_path, head=4, tail=0)[0][:4]
            except OSError:
                header = b""
        bsdtar = self.runner.which("bsdtar")
        if header.startswith(b"pbzx"):
            pbzx = self.runner.which("pbzx")
            if pbzx:
                cmd = [
                    "sh",
                    "-c",
                    f"{shlex.quote(pbzx)} -n {shlex.quote(payload_path)} | cpio -idm -D {shlex.quote(dest_dir)}",
                ]
                res = self.runner.run(cmd)
                if res.returncode == 0:
                    return
                raise BridgeError(f"pbzx extraction failed ({res.returncode}): {res.stderr}")
        if bsdtar:
            res = self.runner.run([bsdtar, "-xf", payload_path, "-C", dest_dir])
            if res.returncode != 0:
                raise BridgeError(f"bsdtar extraction failed ({res.returncode}): {res.stderr}")
            return
        raise MissingToolError("bsdtar", "Install `libarchive` (bsdtar) or `pbzx` to unpack .pkg Payload.")

    def _staging_dir(self, pkg_path: str) -> str:
        digest = hashlib.sha256(pkg_path.encode("utf-8")).hexdigest()[:10]
        return f"{self.config.macos_dir}/cache/pkg-{digest}"

    @staticmethod
    def _parse_distribution_xml(xml_text: str) -> tuple[str | None, str | None, str | None]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None, None, None
        title_el = root.find(".//title")
        pkg_ref = root.find(".//pkg-ref")
        ident = pkg_ref.attrib.get("id") if pkg_ref is not None else None
        ver = pkg_ref.attrib.get("version") if pkg_ref is not None else None
        title = title_el.text.strip() if (title_el is not None and title_el.text) else None
        return ident, ver, title

    @staticmethod
    def _parse_package_info_xml(xml_text: str) -> tuple[str | None, str | None, str | None]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None, None, None
        return (
            root.attrib.get("identifier"),
            root.attrib.get("version"),
            root.attrib.get("identifier"),
        )
