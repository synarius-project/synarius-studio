"""
Regression tests for the simulation run-loop worker (pause / live time axis).

Catches:
- Live ticks using wall clock instead of model time: with a *slow* QTimer interval but *small*
  dt_s, consecutive tick times must differ by dt_s, not by the timer period.
- Pause: no further steps (and thus no further time advances) until resume.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from synarius_core.model import Model, Variable  # noqa: E402
from synarius_studio.main_window import _RunLoopWorker  # noqa: E402


def _minimal_model() -> Model:
    model = Model.new("main")
    v = Variable(name="v", type_key="t", value=0.0)
    model.attach(v, parent=model.root, reserve_existing=False, remap_ids=False)
    return model


class RunLoopWorkerTimeAndPauseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if QApplication.instance() is None:
            cls._owns_app = True
            cls._app = QApplication([])
        else:
            cls._owns_app = False
            cls._app = QApplication.instance()
        assert cls._app is not None

    def setUp(self) -> None:
        self._app = type(self)._app

    def test_tick_timestamps_use_simulation_dt_not_timer_interval(self) -> None:
        """
        If ticks carried perf_counter()-based values, consecutive samples would be ~timer_ms apart.
        They must match engine dt_s (here 0.02) while the timer fires every 300 ms.
        """
        dt_s = 0.02
        tick_ms = 300
        model = _minimal_model()
        worker = _RunLoopWorker(model, dt_s=dt_s, tick_interval_ms=tick_ms)
        thread = QThread()
        worker.moveToThread(thread)
        ticks: list[float] = []

        def _on_tick(t: float, _payload: object) -> None:
            ticks.append(float(t))

        worker.tick.connect(_on_tick)
        thread.started.connect(worker.start)
        worker.stopped.connect(thread.quit)

        thread.start()
        deadline = time.monotonic() + 8.0
        while len(ticks) < 4 and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.005)
        worker.request_stop()
        while thread.isRunning() and time.monotonic() < deadline + 2.0:
            self._app.processEvents()
            time.sleep(0.005)
        thread.wait(5000)

        self.assertGreaterEqual(len(ticks), 4, "expected at least four ticks before stop")
        for i in range(1, 4):
            delta = ticks[i] - ticks[i - 1]
            self.assertLess(
                abs(delta - dt_s),
                1e-6,
                f"tick delta should be dt_s={dt_s}, got {delta} (would be ~{tick_ms / 1000.0}s if wall clock)",
            )

    def test_pause_holds_simulation_time_until_resume(self) -> None:
        dt_s = 0.02
        tick_ms = 40
        model = _minimal_model()
        worker = _RunLoopWorker(model, dt_s=dt_s, tick_interval_ms=tick_ms)
        thread = QThread()
        worker.moveToThread(thread)
        ticks: list[float] = []

        def _on_tick(t: float, _payload: object) -> None:
            ticks.append(float(t))

        worker.tick.connect(_on_tick)
        thread.started.connect(worker.start)
        worker.stopped.connect(thread.quit)

        thread.start()
        deadline = time.monotonic() + 6.0
        while len(ticks) < 3 and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.002)

        self.assertGreaterEqual(len(ticks), 3)
        t_at_pause = ticks[-1]
        worker.request_pause()
        time.sleep(0.35)
        for _ in range(200):
            self._app.processEvents()
            time.sleep(0.002)
        self.assertEqual(len(ticks), 3, "pause must not advance simulation (no extra ticks)")

        worker.request_resume()
        while len(ticks) < 4 and time.monotonic() < deadline + 2.0:
            self._app.processEvents()
            time.sleep(0.002)

        worker.request_stop()
        while thread.isRunning() and time.monotonic() < deadline + 3.0:
            self._app.processEvents()
            time.sleep(0.002)
        thread.wait(5000)

        self.assertGreaterEqual(len(ticks), 4)
        self.assertAlmostEqual(ticks[3] - t_at_pause, dt_s, delta=1e-5)


if __name__ == "__main__":
    unittest.main()
