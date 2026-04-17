"""Unit tests for theme.py, resource_paths.py, and studio_paths.py (no full Studio instantiation)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (
    Path(__file__).resolve().parents[1] / "src",
    _REPO_ROOT / "synarius-core" / "src",
    _REPO_ROOT / "synarius-apps" / "src",
):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)


class RgbHexScaleTest(unittest.TestCase):

    def setUp(self) -> None:
        from synarius_studio.theme import _rgb_hex_scale
        self._scale = _rgb_hex_scale

    def test_identity_factor(self) -> None:
        self.assertEqual(self._scale("#808080", 1.0), "#808080")

    def test_darken(self) -> None:
        result = self._scale("#ffffff", 0.5)
        self.assertEqual(result, "#808080")

    def test_clamp_to_zero(self) -> None:
        result = self._scale("#000000", 0.0)
        self.assertEqual(result, "#000000")

    def test_clamp_to_255(self) -> None:
        result = self._scale("#ffffff", 2.0)
        self.assertEqual(result, "#ffffff")

    def test_invalid_hex_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._scale("#12345", 1.0)

    def test_too_short_raises(self) -> None:
        with self.assertRaises(ValueError):
            self._scale("#fff", 1.0)

    def test_returns_lowercase_hex(self) -> None:
        result = self._scale("#AABBCC", 1.0)
        self.assertTrue(result.startswith("#"))
        self.assertEqual(result, result.lower())


class QssWidgetIdBackgroundTest(unittest.TestCase):

    def setUp(self) -> None:
        from synarius_studio.theme import qss_widget_id_background
        self._fn = qss_widget_id_background

    def test_contains_object_name(self) -> None:
        result = self._fn("myWidget", "#ff0000")
        self.assertIn("#myWidget", result)

    def test_contains_background_color(self) -> None:
        result = self._fn("myWidget", "#ff0000")
        self.assertIn("#ff0000", result)

    def test_contains_background_property(self) -> None:
        result = self._fn("myWidget", "#ff0000")
        self.assertIn("background-color", result)


class StudioTabBarStylesheetTest(unittest.TestCase):

    def setUp(self) -> None:
        from synarius_studio.theme import studio_tab_bar_stylesheet
        self._fn = studio_tab_bar_stylesheet

    def test_contains_qtabbar(self) -> None:
        result = self._fn(selected_tab_bg="#123456")
        self.assertIn("QTabBar", result)

    def test_contains_selected_bg(self) -> None:
        result = self._fn(selected_tab_bg="#abcdef")
        self.assertIn("#abcdef", result)

    def test_contains_tab_selected_rule(self) -> None:
        result = self._fn(selected_tab_bg="#123456")
        self.assertIn("tab:selected", result)


class StudioToolbarStylesheetTest(unittest.TestCase):

    def setUp(self) -> None:
        from synarius_studio.theme import studio_toolbar_stylesheet
        self._fn = studio_toolbar_stylesheet

    def test_default_background(self) -> None:
        result = self._fn()
        self.assertIn("QToolBar", result)
        self.assertIn("background-color", result)

    def test_custom_background(self) -> None:
        result = self._fn(background_color="#ff0000")
        self.assertIn("#ff0000", result)

    def test_contains_tooltip_qss(self) -> None:
        result = self._fn()
        self.assertIn("QToolTip", result)


class WithTooltipQssTest(unittest.TestCase):

    def setUp(self) -> None:
        from synarius_studio.theme import with_tooltip_qss, TOOLTIP_QSS
        self._fn = with_tooltip_qss
        self._tooltip_qss = TOOLTIP_QSS

    def test_appends_tooltip_qss(self) -> None:
        base = "QWidget { color: red; }"
        result = self._fn(base)
        self.assertIn(base, result)
        self.assertIn("QToolTip", result)

    def test_base_preserved(self) -> None:
        base = "QLabel { font-size: 12px; }"
        result = self._fn(base)
        self.assertTrue(result.startswith(base))


class StudioTooltipStylesheetTest(unittest.TestCase):

    def test_returns_tooltip_qss(self) -> None:
        from synarius_studio.theme import studio_tooltip_stylesheet, TOOLTIP_QSS
        self.assertEqual(studio_tooltip_stylesheet(), TOOLTIP_QSS)


class IsFrozenTest(unittest.TestCase):

    def test_not_frozen_in_tests(self) -> None:
        from synarius_studio.resource_paths import is_frozen
        self.assertFalse(is_frozen())

    def test_frozen_when_sys_frozen_set(self) -> None:
        from synarius_studio.resource_paths import is_frozen
        with patch.object(sys, "frozen", True, create=True):
            self.assertTrue(is_frozen())


class BundleRootTest(unittest.TestCase):

    def test_returns_path(self) -> None:
        from synarius_studio.resource_paths import bundle_root
        result = bundle_root()
        self.assertIsInstance(result, Path)

    def test_dev_mode_is_package_dir(self) -> None:
        from synarius_studio.resource_paths import bundle_root
        result = bundle_root()
        self.assertTrue(result.exists())


class StudioIconPathTest(unittest.TestCase):

    def test_default_icon_name(self) -> None:
        from synarius_studio.resource_paths import studio_icon_path
        result = studio_icon_path()
        self.assertEqual(result.name, "synarius64.png")

    def test_custom_icon_name(self) -> None:
        from synarius_studio.resource_paths import studio_icon_path
        result = studio_icon_path("custom.svg")
        self.assertEqual(result.name, "custom.svg")


class PrependDevSynariusAppsSrcTest(unittest.TestCase):

    def test_returns_bool(self) -> None:
        from synarius_studio.resource_paths import prepend_dev_synarius_apps_src
        result = prepend_dev_synarius_apps_src()
        self.assertIsInstance(result, bool)

    def test_returns_false_when_frozen(self) -> None:
        from synarius_studio.resource_paths import prepend_dev_synarius_apps_src
        with patch.object(sys, "frozen", True, create=True):
            result = prepend_dev_synarius_apps_src()
        self.assertFalse(result)


class StudioUserDataDirTest(unittest.TestCase):

    def test_returns_path(self) -> None:
        from synarius_studio.studio_paths import studio_user_data_dir
        result = studio_user_data_dir()
        self.assertIsInstance(result, Path)

    def test_contains_synarius(self) -> None:
        from synarius_studio.studio_paths import studio_user_data_dir
        result = studio_user_data_dir()
        self.assertIn("Synarius", str(result))

    def test_linux_xdg_path(self) -> None:
        from synarius_studio.studio_paths import studio_user_data_dir
        with patch.dict("os.environ", {"XDG_DATA_HOME": "/tmp/xdg"}):
            with patch("sys.platform", "linux"):
                result = studio_user_data_dir()
        self.assertIn("synarius", str(result).lower())

    def test_linux_fallback_no_xdg(self) -> None:
        from synarius_studio.studio_paths import studio_user_data_dir
        env = {k: v for k, v in __import__("os").environ.items() if k != "XDG_DATA_HOME"}
        with patch.dict("os.environ", env, clear=True):
            with patch("sys.platform", "linux"):
                result = studio_user_data_dir()
        self.assertIsInstance(result, Path)


class StudioPluginsAndLibDirTest(unittest.TestCase):

    def test_plugins_dir_is_subdir_of_user_data(self) -> None:
        from synarius_studio.studio_paths import studio_plugins_dir, studio_user_data_dir
        self.assertEqual(studio_plugins_dir(), studio_user_data_dir() / "Plugins")

    def test_lib_dir_is_subdir_of_user_data(self) -> None:
        from synarius_studio.studio_paths import studio_lib_dir, studio_user_data_dir
        self.assertEqual(studio_lib_dir(), studio_user_data_dir() / "Lib")


class StudioLibraryExtraRootsTest(unittest.TestCase):

    def test_returns_empty_list_when_no_lib_dir(self) -> None:
        from synarius_studio.studio_paths import studio_library_extra_roots
        with patch("synarius_studio.studio_paths.studio_lib_dir") as mock_lib:
            mock_lib.return_value = Path("/nonexistent/path/that/does/not/exist")
            result = studio_library_extra_roots()
        self.assertEqual(result, [])

    def test_returns_list(self) -> None:
        from synarius_studio.studio_paths import studio_library_extra_roots
        result = studio_library_extra_roots()
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
