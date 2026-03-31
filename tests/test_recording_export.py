import sys
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd


# Make `src/` importable when running tests via `python -m unittest`.
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))


from synarius_core.model import Model, Variable  # noqa: E402
from synarius_studio.main_window import MainWindow  # noqa: E402


class RecordingExportTest(unittest.TestCase):
    def test_save_recording_writes_non_trivial_timeseries(self) -> None:
        model = Model.new("main")
        v1 = Variable(name="v_a", type_key="var", value=0.0)
        v2 = Variable(name="v_b", type_key="var", value=0.0)
        model.attach(v1, parent=model.root, reserve_existing=False, remap_ids=False)
        model.attach(v2, parent=model.root, reserve_existing=False, remap_ids=False)

        mw = MainWindow()
        mw._controller.model = model  # type: ignore[attr-defined]

        # Synthetic full run buffers: three samples per variable.
        mw._record_series_buffers = {  # type: ignore[attr-defined]
            "v_a": ([0.0, 1.0, 2.0], [1.0, 1.1, 1.2]),
            "v_b": ([0.0, 1.0, 2.0], [2.0, 2.1, 2.2]),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "test_record.parquet"
            mw._save_recording_to_path(out, fmt="parquet")  # type: ignore[attr-defined]
            self.assertTrue(out.is_file(), "Recording file was not created")

            df = pd.read_parquet(out)
            self.assertEqual(sorted(df.columns.tolist()), ["v_a", "v_b"])
            self.assertEqual(len(df.index), 3)
            self.assertTrue(np.allclose(df["v_a"].to_numpy(), np.array([1.0, 1.1, 1.2])))
            self.assertTrue(np.allclose(df["v_b"].to_numpy(), np.array([2.0, 2.1, 2.2])))


if __name__ == "__main__":
    unittest.main()

