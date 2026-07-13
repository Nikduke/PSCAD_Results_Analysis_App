from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from pscad_plotter_app_v3.models import ProjectContext, VoltageLimitSet
from pscad_plotter_app_v3.services.json_store import read_json_file


class LimitService:
    """Load workbook MM limits and merge project-level overrides."""

    LIMITS_FILENAME = "limits.json"

    def load_effective_limits(self, context: ProjectContext) -> dict[str, VoltageLimitSet]:
        workbook_limits = self.load_workbook_limits(context.workbook_path)
        override_limits = self.load_override_limits(context.state_dir / self.LIMITS_FILENAME)
        merged = dict(workbook_limits)
        for key, value in override_limits.items():
            merged[key] = value
        return merged

    def load_workbook_limits(self, workbook_path: Path | None) -> dict[str, VoltageLimitSet]:
        if workbook_path is None or not workbook_path.exists():
            return {}

        workbook = load_workbook(workbook_path, read_only=True, data_only=True)
        try:
            if "MM_blocks" not in workbook.sheetnames:
                return {}

            sheet = workbook["MM_blocks"]
            rows = list(sheet.iter_rows(values_only=True))
            if not rows:
                return {}

            headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
            header_index = {name: index for index, name in enumerate(headers)}
            required = ["Un", "SDPF_LG", "SDPF_LL", "SIWL_LG", "SIWL_LL"]
            if any(column not in header_index for column in required):
                return {}

            limits: dict[str, VoltageLimitSet] = {}
            for row in rows[1:]:
                if not row:
                    continue
                try:
                    voltage = float(row[header_index["Un"]])
                    sdpf_lg = float(row[header_index["SDPF_LG"]])
                    sdpf_ll = float(row[header_index["SDPF_LL"]])
                    siwl_lg = float(row[header_index["SIWL_LG"]])
                    siwl_ll = float(row[header_index["SIWL_LL"]])
                except (TypeError, ValueError):
                    continue
                key = f"{voltage:g}"
                limits.setdefault(
                    key,
                    VoltageLimitSet(
                        voltage_kv=voltage,
                        sdpf_lg=sdpf_lg,
                        sdpf_ll=sdpf_ll,
                        siwl_lg=siwl_lg,
                        siwl_ll=siwl_ll,
                        source="workbook",
                    ),
                )
            return limits
        finally:
            workbook.close()

    def load_override_limits(self, path: Path) -> dict[str, VoltageLimitSet]:
        if not path.exists():
            return {}
        payload = read_json_file(path)
        if not isinstance(payload, dict):
            return {}
        return {key: VoltageLimitSet.from_dict(value) for key, value in payload.items()}

    def get_limit_for_voltage(self, limits: dict[str, VoltageLimitSet], voltage_kv: float | None) -> VoltageLimitSet | None:
        if voltage_kv is None:
            return None
        return limits.get(f"{float(voltage_kv):g}")
