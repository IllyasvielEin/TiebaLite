"""Source-level resource selection regression for the minSdk 35 consolidation.

The fixture records the pre-cleanup 1ba4d6a0 definitions. This is a deliberately
restricted selector for the qualifiers present in this change, not an Android
resource compiler or a replacement for packaged-resource/device verification.
"""
from pathlib import Path
import hashlib
import itertools
import json
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
RES = ROOT / "app/src/main/res"
FIXTURE = Path(__file__).with_name("fixtures") / "api35_resource_winners.json"
OBSOLETE_DIRS = (
    "drawable-v23", "mipmap-anydpi-v26", "mipmap-anydpi-v31",
    "values-v27", "values-v29", "values-v31",
)
REMOVED_STRINGS = (
    "toast_no_permission_insert_photo", "toast_no_permission_upload_portrait",
    "common_permission_activity_recognition_api29",
    "summary_battery_optimization_old_android_version",
    "tip_permission_storage", "tip_permission_storage_download",
    "toast_no_permission_save_photo",
)
DENSITIES = {"ldpi": 120, "mdpi": 160, "hdpi": 240, "xhdpi": 320,
             "xxhdpi": 480, "xxxhdpi": 640}


def node_data(node):
    children = list(node)
    if node.tag == "style":
        names = [child.attrib["name"] for child in children]
        if len(names) != len(set(names)):
            raise AssertionError(f"Duplicate style item in {node.attrib['name']}")
        # Style bags are maps, unlike ordered layer-list/adaptive-icon children.
        children.sort(key=lambda child: child.attrib["name"])
    return [node.tag, sorted(node.attrib.items()), (node.text or "").strip(),
            [node_data(child) for child in children]]


def signature(path=None, node=None):
    if node is not None or path.suffix == ".xml":
        node = node if node is not None else ET.parse(path).getroot()
        data = json.dumps(node_data(node), ensure_ascii=False, separators=(",", ":")).encode()
    else:
        data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def parse_qualifiers(directory):
    result = {"api": 0, "night": None, "sw": 0, "density": None}
    for qualifier in directory.split("-")[1:]:
        if re.fullmatch(r"v\d+", qualifier):
            result["api"] = int(qualifier[1:])
        elif qualifier in ("night", "notnight"):
            result["night"] = qualifier == "night"
        elif re.fullmatch(r"sw\d+dp", qualifier):
            result["sw"] = int(qualifier[2:-2])
        elif qualifier in DENSITIES or qualifier == "anydpi":
            result["density"] = qualifier
        else:
            raise AssertionError(f"Unsupported qualifier {qualifier}; review the selector")
    return result


def inventory(res, keys):
    result = {key: [] for key in keys}
    for directory in sorted(res.iterdir()):
        if not directory.is_dir():
            continue
        kind = directory.name.split("-")[0]
        if kind == "values":
            for path in sorted(directory.glob("*.xml")):
                for node in ET.parse(path).getroot():
                    key = f"{node.tag}/{node.attrib.get('name', '')}"
                    if key in result:
                        result[key].append({"source": path.relative_to(res).as_posix(),
                                            "qualifiers": parse_qualifiers(directory.name),
                                            "sha256": signature(node=node)})
        else:
            for path in sorted(directory.iterdir()):
                if not path.is_file():
                    continue
                key = f"{kind}/{path.stem}"
                if key in result:
                    result[key].append({"source": path.relative_to(res).as_posix(),
                                        "qualifiers": parse_qualifiers(directory.name),
                                        "sha256": signature(path=path)})
    for key, candidates in result.items():
        qualifiers = [json.dumps(item["qualifiers"], sort_keys=True) for item in candidates]
        if len(qualifiers) != len(set(qualifiers)):
            raise AssertionError(f"Duplicate same-config resource {key}; do not guess a merge order")
    return result


def select(candidates, api, night, width, density):
    choices = [item for item in candidates
               if item["qualifiers"]["api"] <= api
               and item["qualifiers"]["sw"] <= width
               and item["qualifiers"]["night"] in (None, night)]
    if not choices:
        raise AssertionError("No matching resource")
    # For the present qualifier subset: smallest width, night, density, API.
    for field in ("sw", "night"):
        best = max(item["qualifiers"][field] is not None if field == "night"
                   else item["qualifiers"][field] for item in choices)
        choices = [item for item in choices
                   if (item["qualifiers"][field] is not None if field == "night"
                       else item["qualifiers"][field]) == best]
    if any(item["qualifiers"]["density"] == "anydpi" for item in choices):
        choices = [item for item in choices if item["qualifiers"]["density"] == "anydpi"]
    elif any(item["qualifiers"]["density"] is not None for item in choices):
        # Target icons always have eligible anydpi winners at API35+. A new raster
        # fallback must receive a real Android selection review, not an approximation.
        exact = [item for item in choices if DENSITIES.get(item["qualifiers"]["density"]) == density]
        if not exact:
            raise AssertionError("Unexpected raster fallback; inspect Android density selection")
        choices = exact
    highest = max(item["qualifiers"]["api"] for item in choices)
    winners = [item for item in choices if item["qualifiers"]["api"] == highest]
    if len(winners) != 1:
        raise AssertionError(f"Ambiguous resource winners: {winners}")
    return winners[0]


class ResourceQualifierEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.current = inventory(RES, cls.fixture["resources"])

    def test_effective_api35_36_37_winners_match_pre_cleanup_fixture(self):
        for api, night, width, density in itertools.product(
                (35, 36, 37), (False, True), (360, 599, 600, 840),
                (120, 160, 240, 320, 420, 480, 560, 640)):
            for key, previous in self.fixture["resources"].items():
                before = select(previous, api, night, width, density)
                after = select(self.current[key], api, night, width, density)
                with self.subTest(resource=key, api=api, night=night, width=width, density=density):
                    self.assertEqual(before["sha256"], after["sha256"],
                                     f"{before['source']} -> {after['source']}")

    def test_lower_version_directories_are_gone_and_min_sdk_is_compatible(self):
        for directory in OBSOLETE_DIRS:
            self.assertFalse((RES / directory).exists(), directory)
        build = (ROOT / "app/build.gradle.kts").read_text()
        self.assertGreaterEqual(int(re.search(r"minSdk\s*=\s*(\d+)", build)[1]), 35)

    def test_remaining_night_width_and_density_variants_are_unchanged(self):
        expected = self.fixture["unchanged_qualified_files"]
        actual_paths = {path.relative_to(RES).as_posix()
                        for directory in RES.iterdir() if directory.is_dir()
                        and (directory.name in ("values-night", "values-sw600dp")
                             or directory.name in {f"mipmap-{d}" for d in DENSITIES})
                        for path in directory.iterdir() if path.is_file()}
        self.assertEqual(set(expected), actual_paths)
        for relative, digest in expected.items():
            self.assertEqual(digest, hashlib.sha256((RES / relative).read_bytes()).hexdigest(), relative)

    def test_orphan_strings_have_no_remaining_main_source_references(self):
        for path in (ROOT / "app/src/main").rglob("*"):
            if path.is_file() and path.suffix in (".xml", ".kt", ".java", ".proto", ".json"):
                content = path.read_text()
                for name in REMOVED_STRINGS:
                    self.assertNotIn(name, content, str(path))

    def test_style_winners_are_complete_bags_without_duplicate_items(self):
        names = ("Base.AppTheme", "Base.AppTheme.Dark", "AppTheme.PhotoView", "Theme.Splash")
        styles = {node.attrib["name"]: node for path in (RES / "values").glob("*.xml")
                  for node in ET.parse(path).getroot() if node.tag == "style" and node.attrib["name"] in names}
        self.assertEqual(set(names), set(styles))
        items = {name: {child.attrib["name"]: (child.text or "").strip() for child in node}
                 for name, node in styles.items()}
        for node in styles.values():
            node_data(node)  # Reject duplicate items rather than last-wins dictionary masking.
        self.assertEqual("false", items["Base.AppTheme"]["android:forceDarkAllowed"])
        self.assertEqual("true", items["Base.AppTheme"]["android:windowLightNavigationBar"])
        self.assertEqual("false", items["Base.AppTheme.Dark"]["android:forceDarkAllowed"])
        self.assertEqual("false", items["Base.AppTheme.Dark"]["android:windowLightNavigationBar"])
        self.assertEqual("shortEdges", items["AppTheme.PhotoView"]["android:windowLayoutInDisplayCutoutMode"])
        self.assertEqual("@drawable/ic_splash_text", items["Theme.Splash"]["android:windowSplashScreenBrandingImage"])

    def test_themed_adaptive_icons_keep_the_api31_whole_resource_winner(self):
        namespace = "{http://schemas.android.com/apk/res/android}drawable"
        for name in ("ic_launcher_new_themed", "ic_launcher_new_themed_round"):
            node = ET.parse(RES / "mipmap-anydpi" / f"{name}.xml").getroot()
            self.assertEqual("adaptive-icon", node.tag)
            self.assertEqual("@color/ic_launcher_new_themed_background", node.find("background").attrib[namespace])
            self.assertEqual("@drawable/ic_launcher_new_themed_foreground", node.find("foreground").attrib[namespace])
            self.assertIsNone(node.find("monochrome"))  # API26's child must not leak into the API31 winner.

    def test_selector_fixture_is_sensitive_to_lost_winners(self):
        # Built-in negative controls prove the fixture is not merely comparing names.
        before = self.fixture["resources"]["mipmap/ic_launcher_new_themed"]
        correct = select(before, 35, False, 360, 320)
        no_v31 = [item for item in before if item["qualifiers"]["api"] != 31]
        self.assertNotEqual(correct["sha256"], select(no_v31, 35, False, 360, 320)["sha256"])
        style = self.fixture["resources"]["style/Base.AppTheme"]
        correct = select(style, 35, False, 360, 320)
        no_v29 = [item for item in style if item["qualifiers"]["api"] != 29]
        self.assertNotEqual(correct["sha256"], select(no_v29, 35, False, 360, 320)["sha256"])


if __name__ == "__main__":
    unittest.main()
