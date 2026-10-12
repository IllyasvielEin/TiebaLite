"""Focused source regressions; Android compilation/runtime tests are still required."""
from pathlib import Path
import re
import unittest

JAVA = Path(__file__).resolve().parents[2] / 'main/java/com/huanchengfly/tieba/post'


class ComposeCompatibilityChecks(unittest.TestCase):
    def test_platform_ime_animation_uses_platform_inset_type(self):
        source = (JAVA / 'ui/utils/ImeInsetsConnection.kt').read_text()
        call = source.split('view.windowInsetsController?.controlWindowInsetsAnimation(', 1)[1].split(')', 1)[0]
        self.assertIn('android.view.WindowInsets.Type.ime(', call)
        self.assertNotIn('WindowInsetsCompat', source)

    def test_compose_resource_migration_preserves_context_imports(self):
        # Resource-only context variables can go away while direct uses remain,
        # such as a dataStore read or passing Context to a callback helper.
        for path in JAVA.rglob('*.kt'):
            source = path.read_text()
            if 'LocalContext.current' in source:
                with self.subTest(path=str(path.relative_to(JAVA))):
                    self.assertTrue(
                        'import androidx.compose.ui.platform.LocalContext' in source
                        or 'import androidx.compose.ui.platform.*' in source,
                        'LocalContext.current requires its platform import',
                    )

    def test_default_link_settings_keeps_ordered_vendor_fallback_on_min35(self):
        gradle = (JAVA.parents[6] / 'build.gradle.kts').read_text()
        self.assertRegex(gradle, r'minSdk\s*=\s*35\b')
        source = (JAVA / 'ui/page/settings/more/MoreSettingsPage.kt').read_text()
        helper = source.split('private fun openDefaultLinkSettings', 1)[1]
        actions = helper.split('val actions = listOf(', 1)[1].split(')', 1)[0]
        self.assertLess(actions.index('Settings.ACTION_APP_OPEN_BY_DEFAULT_SETTINGS'),
                        actions.index('Settings.ACTION_APPLICATION_DETAILS_SETTINGS'))
        self.assertIn('catch (_: ActivityNotFoundException)', helper)
        self.assertIn('for (action in actions)', helper)
        self.assertIn('Uri.parse("package:${context.packageName}")', helper)
        self.assertIn('return false', helper)
        self.assertIn('if (!openDefaultLinkSettings(context))', source)

    def test_initial_intent_side_effect_is_deferred(self):
        source = (JAVA / 'arch/Extensions.kt').read_text()
        initial = source.split('initialIntent: List<INTENT>', 1)[1]
        self.assertLess(initial.index('LaunchedEffect(this, initialIntent)'),
                        initial.index('initialized = true'))
        self.assertIn('initialIntent.isNotEmpty() && !initialized', initial)
        self.assertIn('.launchIn(viewModelScope)', initial)

    def test_video_content_identity_is_remembered(self):
        source = (JAVA / 'ui/widgets/compose/FeedCard.kt').read_text()
        self.assertRegex(source, r'val videoPlayerContent = remember\(videoPlayerController\) \{\s*movableContentOf')

    def test_reply_hint_tracks_localized_value(self):
        source = (JAVA / 'ui/page/reply/ReplyPage.kt').read_text()
        self.assertIn('LaunchedEffect(replyHint, editTextView)', source)
        self.assertIn('editTextView?.hint = replyHint', source)
        self.assertIn('stringResource(R.string.hint_reply, replyUserName)', source)


if __name__ == '__main__':
    unittest.main()
