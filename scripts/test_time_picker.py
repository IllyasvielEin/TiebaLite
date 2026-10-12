"""Picker source wiring and executable legacy formatter checks, not Android/Compose runtime proof."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'
PICKER = JAVA / 'ui/widgets/compose/picker'


class PickerWiringTest(unittest.TestCase):
    def test_persistence_model_is_immutable_and_independent_of_compose(self):
        source = (PICKER / 'PickerTime.kt').read_text()
        self.assertNotIn('androidx.compose', source)
        self.assertNotIn('var hours', source)
        self.assertNotIn('var minutes', source)
        self.assertNotIn('String.format(', source)
        self.assertIn("padStart(2, '0')", source)
        self.assertIn('sourceHour % 12', source)
        self.assertIn('hourOfDay < 12', source)
        self.assertIn('RegexOption.IGNORE_CASE', source)

    def test_display_locale_and_updated_parent_callback_are_explicit(self):
        source = (PICKER / 'TimePicker.kt').read_text()
        self.assertIn('LocalConfiguration.current.locales[0]', source)
        self.assertIn('String.format(displayLocale,', source)
        self.assertIn('rememberUpdatedState(onTimeChanged)', source)
        self.assertIn('remember(currentTime, is24TimeFormat)', source)
        self.assertIn('pickerTime = pickerTime.copy(', source)

    def test_both_columns_share_lifecycle_owned_settling(self):
        wheel = (PICKER / 'WheelPicker.kt').read_text()
        time = (PICKER / 'TimePicker.kt').read_text()
        self.assertIn('cyclic = true', wheel)
        self.assertIn('cyclic = false', time)
        self.assertIn('items(if (cyclic) Int.MAX_VALUE else items.size)', wheel)
        self.assertNotIn('rememberCoroutineScope', wheel + time)
        self.assertNotIn('scope.launch', wheel + time)
        self.assertNotIn('collectLatest', wheel)
        self.assertIn('snapshotFlow {', wheel)
        self.assertIn('}.collect { observation ->', wheel)
        self.assertIn('selection.settle(index)?.let { currentOnItemChanged(it) }', wheel)
        self.assertIn('selection.request(currentSelectedItem)', wheel)

    def test_scroll_state_reads_are_in_observation_or_item_derived_state(self):
        source = (PICKER / 'WheelPicker.kt').read_text()
        composition = source.split('    Box(modifier = modifier', 1)[1].split('\ninternal class PickerColumnState', 1)[0]
        self.assertNotIn('isScrollInProgress', composition)
        self.assertNotIn('firstVisibleItemScrollOffset', composition)
        self.assertIn('derivedStateOf { i == listState.firstVisibleItemIndex }', composition)
        self.assertIn('if (items.isEmpty()', source)

    def test_scroll_cancellation_checks_the_owner_before_recovering(self):
        source = (PICKER / 'PickerSelection.kt').read_text()
        catch = source.split('catch (_: CancellationException)', 1)[1].split('}', 1)[0]
        self.assertIn('currentCoroutineContext().ensureActive()', catch)
        self.assertIn('return false', catch)

    def test_cancelled_preview_is_not_an_initial_value_for_the_next_session(self):
        pref = (JAVA / 'ui/common/prefs/widgets/TimePickerPref.kt').read_text()
        dialog = (JAVA / 'ui/widgets/compose/Dialogs.kt').read_text().split('fun TimePickerDialog(', 1)[1].split('fun AlertDialog(', 1)[0]
        self.assertNotIn('timeVal', pref)
        self.assertNotIn('LaunchedEffect(null)', pref)
        self.assertIn('currentTime = value', pref)
        self.assertIn('edit(it)', pref)
        self.assertIn('preferences[selectionKey] = confirmedTime', pref)
        self.assertIn('currentOnValueSaved(confirmedTime)', pref)
        self.assertIn('remember(currentTime, is24TimeFormat, dialogState.show)', dialog)
        self.assertIn('PickerTime.parse(currentTime, is24TimeFormat).toString()', dialog)

    def test_confirmation_reads_actual_position_and_rechecks_after_enablement(self):
        wheel = (PICKER / 'WheelPicker.kt').read_text()
        state = wheel.split('internal class PickerColumnState', 1)[1].split('@Composable', 1)[0]
        for actual_read in ('listState.isScrollInProgress', 'listState.firstVisibleItemIndex',
                            'listState.firstVisibleItemScrollOffset'):
            self.assertIn(actual_read, state)
        self.assertIn('itemHeight > 0 && isPickerSettled(', state)
        self.assertIn('var positioned by mutableStateOf(false)', state)
        self.assertIn('columnState.positioned = false', wheel)
        dialog = (JAVA / 'ui/widgets/compose/Dialogs.kt').read_text().split('fun TimePickerDialog(', 1)[1].split('fun AlertDialog(', 1)[0]
        self.assertIn('derivedStateOf { pickerState.isSettled(', dialog)
        self.assertIn('enabled = dialogState.show && sessionOpen && canConfirm', dialog)
        self.assertIn('val ready = dialogState.show && pickerState.isSettled(', dialog)
        self.assertIn('val accepted = session.confirm(ready)', dialog)

    def test_confirm_and_cancel_close_session_before_callbacks_and_block_preview(self):
        source = (JAVA / 'ui/widgets/compose/Dialogs.kt').read_text()
        dialog = source.split('fun TimePickerDialog(', 1)[1].split('fun AlertDialog(', 1)[0]
        self.assertLess(dialog.index('session.confirm(ready)'), dialog.index('onConfirm(timeVal)'))
        accepted = dialog.split('if (accepted) {', 1)[1].split('accepted\n', 1)[0]
        self.assertLess(accepted.index('sessionOpen = false'), accepted.index('onConfirm(timeVal)'))
        cancel = dialog.split('fun cancelSession()', 1)[1].split('    Dialog(', 1)[0]
        self.assertLess(cancel.index('session.cancel()'), cancel.index('onCancel?.invoke()'))
        self.assertLess(cancel.index('sessionOpen = false'), cancel.index('onCancel?.invoke()'))
        self.assertIn('onDismiss = { cancelSession() }', dialog)
        self.assertIn('DialogNegativeButton(text = cancelText, onClick = { cancelSession() })', dialog)
        preview = dialog.split('onTimeChanged = {', 1)[1].split('is24TimeFormat =', 1)[0]
        self.assertLess(preview.index('if (session.isOpen && dialogState.show)'), preview.index('timeVal = it'))
        self.assertLess(preview.index('if (session.isOpen && dialogState.show)'), preview.index('onValueChange?.invoke(it)'))
        button = source.split('fun DialogScope.DialogPositiveButton(', 1)[1].split('fun DialogScope.DialogNegativeButton(', 1)[0]
        self.assertIn('onClick: () -> Unit = {}', button)
        self.assertIn('DialogPositiveButton(text = text, enabled = true, onClick = { onClick(); true })', button)
        self.assertIn('onClick: () -> Boolean', button)
        self.assertIn('if (onClick()) dismiss()', button)


@unittest.skipUnless(shutil.which('java'), 'JDK required for actual legacy formatter check')
class LegacyFormatterExecutableTest(unittest.TestCase):
    def test_actual_legacy_formatter_under_arabic_and_persian_locales(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stubs = {
                'android/content/Context.java': 'package android.content; public class Context {}',
                'android/util/AttributeSet.java': 'package android.util; public interface AttributeSet {}',
                'android/content/res/TypedArray.java': 'package android.content.res; public class TypedArray { public String getString(int i) { return null; } }',
                'androidx/preference/DialogPreference.java': '''package androidx.preference;
                    public class DialogPreference {
                      public DialogPreference(android.content.Context c, android.util.AttributeSet a) {}
                      protected Object onGetDefaultValue(android.content.res.TypedArray a, int i) { return null; }
                      protected void onSetInitialValue(boolean r, Object d) {}
                      protected String getPersistedString(String s) { return s; }
                      protected boolean persistString(String s) { return true; }
                    }''',
                'FormatterHarness.java': '''import java.util.Locale;
                    import com.huanchengfly.tieba.post.components.prefs.TimePickerPreference;
                    public class FormatterHarness {
                      public static void main(String[] args) {
                        Locale previous = Locale.getDefault();
                        try {
                          for (String language : new String[]{"en", "ar", "fa", "tr"}) {
                            Locale.setDefault(Locale.forLanguageTag(language));
                            for (int h = 0; h < 24; h++) for (int m : new int[]{0, 3, 59}) {
                              String actual = TimePickerPreference.timeToString(h, m);
                              String expected = (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
                              if (!expected.equals(actual)) throw new AssertionError(language + ": " + actual);
                            }
                          }
                        } finally { Locale.setDefault(previous); }
                      }
                    }''',
            }
            sources = []
            for name, source in stubs.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
                sources.append(target)
            sources.append(JAVA / 'components/prefs/TimePickerPreference.java')
            subprocess.run([shutil.which('java'), '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-d', folder, *map(str, sources)], check=True)
            subprocess.run([shutil.which('java'), '-cp', folder, 'FormatterHarness'], check=True)


if __name__ == '__main__':
    unittest.main()
