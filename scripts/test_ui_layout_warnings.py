"""Resource/source regression checks, not Android layout or accessibility runtime QA."""
import pathlib
import unittest
import xml.etree.ElementTree as ET


ROOT = pathlib.Path(__file__).resolve().parents[1]
LAYOUT = ROOT / 'app/src/main/res/layout'
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'
ANDROID = '{http://schemas.android.com/apk/res/android}'
APP = '{http://schemas.android.com/apk/res-auto}'


def read_layout(name):
    return ET.parse(LAYOUT / name).getroot()


def view_with_id(root, view_id):
    return next(view for view in root.iter() if view.get(ANDROID + 'id') == view_id)


class DialogAccessibilityResourcesTest(unittest.TestCase):
    def test_only_decorative_icons_are_hidden(self):
        for name, icon_id in (
            ('dialog_request_permission_tip.xml', '@+id/request_permission_tip_dialog_icon'),
            ('layout_alert_dialog.xml', '@android:id/icon'),
        ):
            with self.subTest(layout=name):
                root = read_layout(name)
                icon = view_with_id(root, icon_id)
                self.assertEqual('@null', icon.get(ANDROID + 'contentDescription'))
                self.assertEqual('no', icon.get(ANDROID + 'importantForAccessibility'))
                self.assertIsNone(icon.get(ANDROID + 'clickable'))
                self.assertIsNone(icon.get(ANDROID + 'focusable'))
                # No parent/text subtree was excluded with the decorative image.
                hidden = [view for view in root.iter()
                          if view.get(ANDROID + 'importantForAccessibility') in ('no', 'noHideDescendants')]
                self.assertEqual([icon], hidden)

    def test_permission_title_and_message_keep_text_semantics(self):
        root = read_layout('dialog_request_permission_tip.xml')
        for view_id in ('@+id/request_permission_tip_dialog_title',
                        '@+id/request_permission_tip_dialog_message'):
            with self.subTest(view_id=view_id):
                view = view_with_id(root, view_id)
                self.assertTrue(view.tag.endswith('TextView'))
                self.assertIsNone(view.get(ANDROID + 'contentDescription'))
                self.assertIsNone(view.get(ANDROID + 'importantForAccessibility'))
        source = (JAVA / 'components/dialogs/RequestPermissionTipDialog.kt').read_text()
        self.assertIn('title.text = context.getString(', source)
        self.assertIn('message.text =', source)
        self.assertNotIn('request_permission_tip_dialog_icon', source)

    def test_alert_title_and_message_keep_text_semantics(self):
        root = read_layout('layout_alert_dialog.xml')
        for view_id in ('@+id/alertTitle', '@android:id/message'):
            with self.subTest(view_id=view_id):
                view = view_with_id(root, view_id)
                self.assertIsNone(view.get(ANDROID + 'contentDescription'))
                self.assertIsNone(view.get(ANDROID + 'importantForAccessibility'))
        self.assertEqual('viewStart', view_with_id(root, '@+id/alertTitle').get(ANDROID + 'textAlignment'))


class LogicalLayoutResourcesTest(unittest.TestCase):
    def test_alert_alignment_and_icon_gap_use_logical_edges(self):
        root = read_layout('layout_alert_dialog.xml')
        self.assertEqual('start|top', root.get(ANDROID + 'gravity'))
        template = view_with_id(root, '@+id/title_template')
        self.assertEqual('center_vertical|start', template.get(ANDROID + 'gravity'))
        icon = view_with_id(root, '@android:id/icon')
        self.assertEqual('8dip', icon.get(ANDROID + 'layout_marginEnd'))
        self.assertIsNone(icon.get(ANDROID + 'layout_marginRight'))
        self.assertEqual('32dip', icon.get(ANDROID + 'layout_width'))
        self.assertEqual('32dip', icon.get(ANDROID + 'layout_height'))

    def test_theme_swatch_preserves_end_only_spacing(self):
        root = read_layout('item_theme_color.xml')
        self.assertEqual('0dp', root.get(ANDROID + 'paddingStart'))
        self.assertEqual('4dp', root.get(ANDROID + 'paddingEnd'))
        self.assertIsNone(root.get(ANDROID + 'paddingLeft'))
        self.assertIsNone(root.get(ANDROID + 'paddingRight'))
        self.assertEqual('4dp', root.get(ANDROID + 'paddingBottom'))
        preview = view_with_id(root, '@+id/theme_preview')
        self.assertEqual('48dp', preview.get(ANDROID + 'layout_width'))
        self.assertEqual('48dp', preview.get(ANDROID + 'layout_height'))
        selected = view_with_id(root, '@+id/theme_selected')
        self.assertEqual('bottom|end', selected.get(ANDROID + 'layout_gravity'))
        self.assertEqual('-4dp', selected.get(ANDROID + 'layout_marginEnd'))

    def test_permission_text_constraints_still_follow_start_and_end(self):
        root = read_layout('dialog_request_permission_tip.xml')
        icon = view_with_id(root, '@+id/request_permission_tip_dialog_icon')
        title = view_with_id(root, '@+id/request_permission_tip_dialog_title')
        message = view_with_id(root, '@+id/request_permission_tip_dialog_message')
        self.assertEqual('parent', icon.get(APP + 'layout_constraintStart_toStartOf'))
        self.assertEqual('@+id/request_permission_tip_dialog_icon',
                         title.get(APP + 'layout_constraintStart_toEndOf'))
        self.assertEqual('@+id/request_permission_tip_dialog_title',
                         message.get(APP + 'layout_constraintStart_toStartOf'))
        for view in (title, message):
            self.assertEqual('parent', view.get(APP + 'layout_constraintEnd_toEndOf'))


if __name__ == '__main__':
    unittest.main()
