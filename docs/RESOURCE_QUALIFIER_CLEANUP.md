# Resource qualifier consolidation for minSdk 35

Baseline: `1ba4d6a0` (minSdk 35, compile/target SDK 37). This change removes
obsolete resource version directories while preserving the complete resource
that Android API 35+ already selects. It does not redesign the splash screen,
launcher icons, theme palette, or navigation bars.

## Exact winners retained

| Resource | Previous API35+ winner | Current location |
|---|---|---|
| drawable/splash | drawable-v23/splash.xml | drawable/splash.xml |
| 10 ordinary launcher/shortcut adaptive icons | mipmap-anydpi-v26 | mipmap-anydpi |
| ic_launcher_new_themed and its round variant | mipmap-anydpi-v31 | mipmap-anydpi |
| style/AppTheme.PhotoView | values-v27/styles.xml | values/styles.xml |
| style/Base.AppTheme and Base.AppTheme.Dark | values-v29/styles.xml | values/styles.xml |
| style/Theme.Splash | values-v31/styles.xml | values/styles.xml |
| 3 ic_launcher_new_themed_* colors | values-v31/colors.xml | values/colors.xml |

The styles are selected as whole bags. No style-item union across API versions
was performed, and no duplicate same-configuration style definition or duplicate
item was introduced. The winner preserves PhotoView's cutout mode, both base
themes' force-dark/navigation-bar flags, and the splash branding image. Existing
parents and all other style attributes remain unchanged.

The two API31 themed adaptive icons intentionally have different foreground and
background references from their API26 alternatives and **no monochrome child**.
The complete API31 definitions are retained; merging the API26 monochrome child
would change API35+ behavior. The other icons retain their original complete
API26 definitions. Raster density alternatives are retained unchanged.

The themed color winners still reference `android:color/system_accent1_300/600`;
they are not replaced with the previous base hex fallback. The splash still
references the unchanged day/night `colorSplashBg` resource. The `anydpi`
qualifier remains in place, so adaptive icons continue to outrank density-specific
raster variants.

Official resource-selection reference:
https://developer.android.com/guide/topics/resources/providing-resources

## Seven narrowly proven orphan strings

The two original PhotoPicker leftovers only had definitions at the baseline:

- toast_no_permission_insert_photo
- toast_no_permission_upload_portrait

The minSdk35 source cleanup removed the sole runtime references to five more
strings. Their causal baseline references were checked before deletion:

| Removed string | Sole reference at baseline 1ba4d6a0 |
|---|---|
| common_permission_activity_recognition_api29 | PermissionUtils.kt:206, pre-API30 label branch |
| summary_battery_optimization_old_android_version | OKSignSettingsPage.kt:186, pre-API23 branch |
| tip_permission_storage | ImageUtil.kt:308, old storage-permission flow |
| tip_permission_storage_download | FileUtil.kt:212, old storage-permission flow |
| toast_no_permission_save_photo | ImageUtil.kt:310, old storage-permission flow |

Current main-source searches found no remaining static names, `R.string` or XML
references to these seven. The dynamic lookup sites were reviewed: App's theme
lookups target colors; EmoticonManager targets drawable IDs; status-bar utilities
target system dimensions. No dynamic string lookup or reflection naming these
resources was found. This is a narrow source/dependency-usage assessment, not a
general proof that every lint-unused resource is safe to delete. All other
unused strings, dynamic colors, emoticons and icon identities are retained.

## Regression evidence

Run:

```sh
python3 app/src/test/compatibility/check_resource_qualifier_equivalence.py
```

The immutable pre-edit fixture is
`app/src/test/compatibility/fixtures/api35_resource_winners.json`. It identifies
the full baseline commit and records 20 resource IDs, 92 original variants and
67 unchanged night/width/density files. XML signatures include expanded attribute
names, values, ordered children and complete style bags. Style-item order alone
is ignored because a style bag is keyed by attribute; duplicate items fail.

The test compares **3,840 effective selections**: all 20 resources across API
35/36/37, day/night, smallest widths 360/599/600/840 dp, and densities
120/160/240/320/420/480/560/640 dpi. It also verifies:

- All six obsolete version directories are absent and minSdk remains at least 35
- Night, tablet-width and raster-density files are byte-for-byte unchanged
- All seven removed string names are absent from main source/resources
- Critical style items and complete API31 themed icon definitions are retained
- Negative controls reject losing the API31 icon or API29 base-style winner

This selector deliberately supports only qualifiers present in this change. It
fails on unknown qualifiers or an unexpected raster fallback rather than
pretending to implement Android's complete resource-resolution algorithm. Do not
automatically refresh the fixture to make a behavior change pass; review and
explicitly update expected semantics if an intentional redesign follows.

The source tests and XML parse checks passed locally. They are not a claim that
AAPT linking, release resource shrinking, launcher rendering, or device behavior
has been revalidated. The normal integration build/lint checks still need to run;
device regressions should compare cold splash, light/dark theme, launcher icon
choices and a tablet-width layout on the supported API35/API37 lanes. No new
APK-size or performance saving is claimed without measuring the resulting APK.
