import sys
from pathlib import Path
import unittest


# Make `src/` importable when running tests via `python -m unittest`.
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))


from synarius_core.model import Model, ModelElementType, SignalContainer  # noqa: E402


class RecordingIntegrationTest(unittest.TestCase):
    def test_recording_container_exists_for_main_model(self) -> None:
        model = Model.new("main")
        rec = model.get_root_by_type(ModelElementType.MODEL_RECORDING)
        self.assertIsNotNone(rec)
        self.assertIsInstance(rec, SignalContainer)

    def test_recording_container_is_empty_by_default(self) -> None:
        model = Model.new("main")
        rec = model.get_root_by_type(ModelElementType.MODEL_RECORDING)
        assert isinstance(rec, SignalContainer)
        self.assertEqual(rec._series_store, {})  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()

