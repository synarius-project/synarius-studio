"""FMU import dialog command builder."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synarius_studio.fmu_import_dialog import build_fmu_import_command  # noqa: E402


class FmuImportCommandTest(unittest.TestCase):
    def test_build_command_contains_keywords(self) -> None:
        p = Path("C:/tmp/x.fmu")
        rows = [
            {"name": "u", "value_reference": 1, "causality": "input", "data_type": "float"},
            {"name": "y", "value_reference": 2, "causality": "output", "data_type": "float"},
        ]
        line = build_fmu_import_command(
            fmu_path=p,
            instance_name="fb1",
            model_x=10.0,
            model_y=20.0,
            model_size=1.0,
            selected_variable_rows=rows,
        )
        self.assertIn("new FmuInstance", line)
        self.assertIn("fb1", line)
        self.assertIn("fmu_path=", line)
        self.assertIn("fmu_ports=", line)
        self.assertIn("fmu_variables=", line)
        self.assertIn("'u'", line)
        self.assertIn("'y'", line)


if __name__ == "__main__":
    unittest.main()
