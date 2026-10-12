"""Focused source regressions; Android compilation/runtime tests are still required."""
from pathlib import Path
import re
import unittest

JAVA = Path(__file__).resolve().parents[2] / 'main/java/com/huanchengfly/tieba/post'


class ComposeCompatibilityChecks(unittest.TestCase):
    def test_default_link_settings_guards_api31_and_falls_back(self):
        source = (JAVA / 'ui/page/settings/more/MoreSettingsPage.kt').read_text()
        helper = source.split('private fun openDefaultLinkSettings', 1)[1]
        branches = re.search(
            r'if \(Build.VERSION.SDK_INT >= Build.VERSION_CODES.S\) \{(.*?)\} else \{(.*?)\}',
            helper, re.S,
        )
        self.assertIsNotNone(branches)
        modern, legacy = branches.groups()
        self.assertIn('Settings.ACTION_APP_OPEN_BY_DEFAULT_SETTINGS', modern)
        self.assertIn('Settings.ACTION_APPLICATION_DETAILS_SETTINGS', modern)
        self.assertIn('Settings.ACTION_APPLICATION_DETAILS_SETTINGS', legacy)
        self.assertNotIn('ACTION_APP_OPEN_BY_DEFAULT_SETTINGS', legacy)
        self.assertIn('catch (_: ActivityNotFoundException)', helper)
        self.assertIn('for (action in actions)', helper)
        self.assertIn('Uri.parse("package:${context.packageName}")', helper)
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
