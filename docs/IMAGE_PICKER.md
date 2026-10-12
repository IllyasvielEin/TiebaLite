# Image picker migration

The avatar and transparent-background screens use lifecycle-registered AndroidX
`PickVisualMedia` contracts in single-image mode. The existing Activity 1.13.0
dependency chooses the system photo picker, an eligible system fallback, or
`ACTION_OPEN_DOCUMENT` when an eligible picker is unavailable. The approved
minimum is API 35; neither selection path requests whole-library access.

Official contract and fallback documentation:
- https://developer.android.com/reference/androidx/activity/result/contract/ActivityResultContracts.PickVisualMedia
- https://developer.android.com/training/data-storage/shared/photo-picker

## Preserved behavior

Only `content` URIs with a nonempty provider authority are accepted from picker
results. The active callbacks reject network/file/other schemes before the generic
Glide/Sketch loaders can interpret them. The retained adapter filters its result
list through the same policy. Arbitrary provider authorities are allowed because
system document/cloud providers are legitimate selection sources; URI read
failures still need graceful handling.

- Avatar selection still loads the selected URI through Glide into a local file,
  crops to a square with UCrop, and sends the existing portrait-upload intent only
  after a successful crop with a non-null output URI.
- Background selection still reads the selected URI, writes the original image
  into app cache, and crops into the existing app background file. Its aspect
  ratio, theme preview, and save flow are unchanged.
- Cancelling the picker does not load/crop an image. Cancelling UCrop does not
  upload a portrait or replace the current background. Unreadable avatar URIs and
  malformed crop results show the existing load-failed message instead of being
  treated as success.
- Selected URIs are read immediately through the existing image loaders. They are
  not saved as long-lived references or given persistent grants; crop inputs use
  local files. A future background/deferred-media feature would need its own
  explicit URI lifetime handling.
- The native publication capability remains disabled. The retained source-level
  multi-media adapter delegates to AndroidX too; it does not re-enable composers.
  Its request state is per launcher, cleared after cancellation or a result, and
  results are deduplicated and limited because document fallback may ignore the
  requested maximum. If process death loses its legacy request ID, its result is
  discarded rather than sent to a different request. Active single-image screens
  do not use this legacy request-ID adapter.

## Removed dependency and permission scope

Matisse, its keep rules, and the obsolete in-app-picker setting are removed. The
only other Matisse references were JPEG/GIF MIME strings in ImageUtil; these use
the same standard MIME values directly. Existing saved picker preference values
are simply no longer consulted; no user settings store or draft data is deleted.

The app no longer declares READ_MEDIA_IMAGES. It does not need
READ_MEDIA_VISUAL_USER_SELECTED because it no longer maintains a permission-based
in-app gallery. READ_EXTERNAL_STORAGE and WRITE_EXTERNAL_STORAGE remain with
existing SDK caps: the old-device image/file download paths still request them.
Those unrelated paths were not redesigned in this migration. The final merged
manifest must still be checked during Android build validation.

## Verification

Run the focused source wiring checks:

```sh
python3 app/src/test/compatibility/check_image_picker.py
python3 app/src/test/security/check_publication_boundaries.py
./gradlew --no-daemon :app:testReleaseUnitTest --tests '*PickerUriPolicyTest'
```

The picker checks cover official contract wiring, cancellation/null guards,
no broad permission requests in active screens, content-URI gating, local-file crop handoff,
error feedback, per-launcher legacy request reset, fallback count limiting,
Matisse removal, and retained download/publication boundaries. They are source
regressions, not executable Android picker or URI-grant tests. PickerUriPolicyTest
adds pure JVM cases for provider content and rejected network/file/malformed URIs. Android compilation,
full lint, unit tests, and unsigned assembly remain required build gates.

The approved runtime matrix is Android 17/API 37 as primary and Android 15/API 35
at the supported minimum, with Android 16/API 36 as an optional intermediate lane.
Versions below API 35 cannot install this edition. The compile/target API 37
migration still needs CI and behavior validation.
The following device/emulator cases are still required:

- API 35/37 (optional 36): single selected URI without whole-library permission,
  remote/cloud image, unreadable/revoked URI, cancellation, and a second selection.
- Contract fallback and malformed/cancel results: mock these separately without
  implying the framework/system-picker UI ran on a device.
- Both screens: crop success/cancel/error, activity recreation and process death
  while the picker or cropper is open; returning must not commit stale output.
- API 37 large screen: UCrop rotation, split screen, and fold/unfold. The existing
  portrait manifest declaration has not been changed or claimed sufficient.
- Publication remains disabled during browsing, restored composer routes and
  reply taps; no real-account upload/post is needed to test these boundaries.

No device/emulator pass is implied by the source checks or by compilation.
