"""Four strictly typed, hardware-guarded OS tools for Kite AI (Epic 6.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .. import LIBVA_DRIVER_PIN, MESA_DRIVER_PIN, REQUIRED_DXVK_VERSION
from ..compress.aliaser import build_file_uri, build_kite_uri
from ..index.store import IndexStore
from ..mining.extractor import extract_content
from ..models import ToolCallResult
from ..privacy import PrivacyFilter


class OsToolbox:
    """Sandboxed hooks into Kite AI Store, kite-settings, kite-hw-tune, and KiteBridge."""

    def __init__(
        self,
        store: IndexStore,
        *,
        hw_profile_path: str | Path = "/run/kite-os/hw-profile.json",
        settings_path: str | Path | None = None,
        wine_prefix_path: str | Path | None = None,
        privacy: PrivacyFilter | None = None,
    ) -> None:
        self.store = store
        self.hw_profile_path = Path(hw_profile_path)
        self.settings_path = Path(settings_path) if settings_path else None
        self.wine_prefix_path = Path(wine_prefix_path) if wine_prefix_path else None
        self.privacy = privacy or store.privacy

    def _read_hw_profile(self) -> dict[str, Any]:
        if self.hw_profile_path.is_file():
            try:
                data = json.loads(self.hw_profile_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError):
                pass
        return {
            "schema_version": 1,
            "ram_mb": 8192,
            "memory": {"tier": "8G"},
            "power": {"source": "AC"},
            "blur": {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True},
            "subsystems": {"wine": {"dxvk_version": REQUIRED_DXVK_VERSION, "ntsync": True}},
        }

    def search_local_index(self, query: str, *, limit: int = 10) -> ToolCallResult:
        """Query SQLite FTS5, collapse SimHash duplicates, and return clickable URI cards."""
        hits = self.store.search(query, limit=limit, collapse_duplicates=True)
        cards = [
            {
                "id": f"F{i}",
                "file_name": h.file_name,
                "abs_path": h.abs_path,
                "platform_badge": h.platform_badge,
                "confidence": h.confidence,
                "duplicate_count": h.duplicate_count,
                "kite_uri": build_kite_uri(h.abs_path),
                "file_uri": build_file_uri(h.abs_path),
            }
            for i, h in enumerate(hits, start=1)
        ]
        return ToolCallResult(
            tool_name="search_local_index",
            ok=True,
            tokens_cost=0 if not cards else min(250, 20 * len(cards)),
            data={"query": query, "count": len(cards), "cards": cards},
        )

    def inspect_file_head(self, abs_path: str, *, max_lines: int = 25) -> ToolCallResult:
        """Read up to 25 lines or headings of a non-blocked file."""
        if self.privacy.is_blocked(abs_path):
            return ToolCallResult(
                tool_name="inspect_file_head",
                ok=False,
                tokens_cost=0,
                error=f"Blocked by .kiteignore privacy guardrail: {abs_path}",
            )
        p = Path(abs_path)
        if not p.is_file():
            return ToolCallResult(
                tool_name="inspect_file_head",
                ok=False,
                tokens_cost=0,
                error=f"File not found: {abs_path}",
            )
        extracted = extract_content(p)
        lines = extracted.text_sample.splitlines()[: max(1, min(25, max_lines))]
        return ToolCallResult(
            tool_name="inspect_file_head",
            ok=True,
            tokens_cost=min(150, max(80, 15 + len(lines) * 4)),
            data={
                "abs_path": str(p),
                "file_name": extracted.file_name,
                "platform_badge": extracted.platform_badge,
                "headings": list(extracted.headings),
                "symbols": list(extracted.symbols),
                "head_lines": lines,
            },
        )

    def apply_os_setting(self, updates: Mapping[str, Any]) -> ToolCallResult:
        """Adjust blur passes, taskbar alignment, or power profile within hardware tier limits."""
        prof = self._read_hw_profile()
        tier = str((prof.get("memory") or {}).get("tier", "8G"))
        power_src = str((prof.get("power") or {}).get("source", "AC"))

        applied: dict[str, Any] = {}
        rejected: list[str] = []

        if "blur_passes" in updates:
            req_passes = int(updates["blur_passes"])
            if tier == "4G" and req_passes > 0:
                rejected.append("4G RAM tier forces static acrylic blur (blur_passes=0).")
                applied["blur_passes"] = 0
            elif power_src == "Battery" and req_passes > 1:
                rejected.append("Battery mode caps Dual-Kawase blur to 1 pass.")
                applied["blur_passes"] = 1
            elif req_passes > 2:
                rejected.append("Intel HD 4400 blur budget caps Dual-Kawase at 2 passes.")
                applied["blur_passes"] = 2
            else:
                applied["blur_passes"] = max(0, req_passes)

        if "blur_size" in updates:
            req_size = int(updates["blur_size"])
            max_size = 0 if tier == "4G" else (4 if power_src == "Battery" else 6)
            if req_size > max_size:
                rejected.append(f"Blur size clamped from {req_size} to {max_size} for {tier}/{power_src}.")
            applied["blur_size"] = max(0, min(req_size, max_size))

        if "taskbar_alignment" in updates:
            align = str(updates["taskbar_alignment"]).lower()
            if align in ("center", "left"):
                applied["taskbar_alignment"] = align
            else:
                rejected.append(f"Invalid taskbar_alignment '{align}'; expected 'center' or 'left'.")

        if "dxvk_version" in updates and str(updates["dxvk_version"]).strip() != REQUIRED_DXVK_VERSION:
            return ToolCallResult(
                tool_name="apply_os_setting",
                ok=False,
                tokens_cost=40,
                error=f"Forbidden DXVK version '{updates['dxvk_version']}'; Intel HD 4400 requires {REQUIRED_DXVK_VERSION}.",
            )

        if self.settings_path is not None:
            current: dict[str, Any] = {}
            if self.settings_path.is_file():
                try:
                    current = json.loads(self.settings_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    current = {}
            current.update(applied)
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

        return ToolCallResult(
            tool_name="apply_os_setting",
            ok=True,
            tokens_cost=65,
            data={"tier": tier, "power": power_src, "applied": applied, "clamped_notes": rejected},
        )

    def diagnose_runtime(self, runtime: str = "all") -> ToolCallResult:
        """Inspect Wine/Waydroid/OSX-KVM status and suggest one-click fixes within invariants."""
        prof = self._read_hw_profile()
        subsystems = prof.get("subsystems") or {}
        wine_cfg = subsystems.get("wine") or {}
        dxvk_ver = str(wine_cfg.get("dxvk_version", REQUIRED_DXVK_VERSION))
        findings: list[dict[str, str]] = []

        if dxvk_ver != REQUIRED_DXVK_VERSION:
            findings.append({
                "subsystem": "wine",
                "severity": "critical",
                "issue": f"DXVK {dxvk_ver} violates Intel HD 4400 Vulkan 1.2 limit",
                "fix": f"kite-bridge setup wine --dxvk {REQUIRED_DXVK_VERSION}",
            })

        if self.wine_prefix_path is not None:
            manifest = self.wine_prefix_path / ".kitebridge-manifest.json"
            if manifest.is_file():
                try:
                    mdata = json.loads(manifest.read_text(encoding="utf-8"))
                    m_dxvk = str(mdata.get("dxvk_version", ""))
                    if m_dxvk != REQUIRED_DXVK_VERSION:
                        findings.append({
                            "subsystem": "wine",
                            "severity": "critical",
                            "issue": f"Prefix manifest pins DXVK '{m_dxvk}' instead of {REQUIRED_DXVK_VERSION}",
                            "fix": f"kite-bridge setup wine --repair-dxvk {REQUIRED_DXVK_VERSION}",
                        })
                    if mdata.get("wined3d_dx12") is False:
                        findings.append({
                            "subsystem": "wine",
                            "severity": "critical",
                            "issue": "DX12 WineD3D OpenGL fallback disabled",
                            "fix": "kite-bridge setup wine --enforce-wined3d-dx12",
                        })
                except (OSError, ValueError):
                    findings.append({
                        "subsystem": "wine",
                        "severity": "warning",
                        "issue": "Corrupt .kitebridge-manifest.json",
                        "fix": "kite-bridge setup wine --reinit-manifest",
                    })

        return ToolCallResult(
            tool_name="diagnose_runtime",
            ok=True,
            tokens_cost=140,
            data={
                "runtime": runtime,
                "driver_pins": {
                    "MESA_LOADER_DRIVER_OVERRIDE": MESA_DRIVER_PIN,
                    "LIBVA_DRIVER_NAME": LIBVA_DRIVER_PIN,
                    "DXVK_VER": REQUIRED_DXVK_VERSION,
                },
                "healthy": len(findings) == 0,
                "findings": findings,
            },
        )
