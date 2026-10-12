"""Source and source-derived arithmetic guards, not Compose/runtime animation or RTL QA."""
import ast
import math
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
TABS = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post/ui/widgets/compose/Tabs.kt'


def arithmetic(expression, values):
    """Evaluate only the arithmetic subset shared by these Kotlin/Python expressions."""
    def value(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -value(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise AssertionError('Unsupported arithmetic expression: ' + expression)
    return value(ast.parse(expression, mode='eval').body)


class ComposeTabPlacementSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TABS.read_text()
        cls.offset = cls.source.split('fun Modifier.tabIndicatorOffset(', 1)[1].split('/**', 1)[0]
        cls.pager = cls.source.split('fun PagerTabIndicator(', 1)[1].split('@Composable', 1)[0]
        cls.indicator = cls.source.split('fun TabIndicator(', 1)[1].split('@Composable', 1)[0]

    def test_animated_offset_reads_stay_inside_relative_placement_lambdas(self):
        for body, state, y in ((self.offset, 'indicatorOffset', '0'),
                               (self.pager, 'animatedIndicatorOffset', '(-8).dp.roundToPx()'),
                               (self.indicator, 'animatedIndicatorOffset', '(-8).dp.roundToPx()')):
            with self.subTest(state=state, body=body[:30]):
                self.assertIn('.offset { IntOffset(' + state + '.roundToPx(), ' + y + ') }', body)
                self.assertNotIn('.offset(x =', body)
                self.assertNotIn('absoluteOffset', body)
                self.assertNotIn('IntOffset(', body.split('.offset {', 1)[0])
                self.assertEqual(1, body.count(state + '.roundToPx()'))
                # Only the animation delegate declaration and deferred lambda may reference
                # this state. Computing a separate value during composition defeats the fix.
                self.assertEqual(2, len(re.findall(r'\b' + state + r'\b', body)))
                self.assertIn('.wrapContentSize(Alignment.BottomStart)', body)

    def test_existing_animation_targets_specs_and_indicator_sizes_remain(self):
        self.assertIn('targetValue = currentTabPosition.left,', self.offset)
        self.assertEqual(2, self.offset.count('animationSpec = tween(durationMillis = 250, easing = FastOutSlowInEasing)'))
        self.assertIn('.width(currentTabWidth)', self.offset)
        self.assertIn('animateDpAsState(targetValue = indicatorOffset)', self.pager)
        self.assertIn('animateDpAsState(targetValue = currentTabLeft)', self.indicator)
        for body in (self.pager, self.indicator):
            self.assertIn('.height(3.dp)', body)
            self.assertIn('= 16.dp', body)
        # This separate warning remains visible; this batch does not silently change smoothing.
        self.assertIn('val fraction = pagerState.currentPageOffsetFraction', self.pager)
        self.assertNotIn('derivedStateOf', self.pager)

    def test_all_selected_index_indicator_lookups_tolerate_shrinking_lists(self):
        self.assertNotIn('tabPositions[selectedTabIndex]', self.source)
        self.assertEqual(3, self.source.count('tabPositions.getOrNull(selectedTabIndex)'))
        self.assertEqual(2, self.source.count('tabPositions.getOrNull(selectedTabIndex)?.let'))
        self.assertIn('val currentTab = tabPositions.getOrNull(selectedTabIndex) ?: return', self.indicator)
        self.assertIn('if (tabPositions.isNotEmpty())', self.pager)
        self.assertIn('minOf(tabPositions.lastIndex, pagerState.currentPage)', self.pager)

    def test_source_centering_formula_handles_unequal_first_and_last_tabs(self):
        tabs = ((12, 70), (82, 110), (192, 90))
        for body, width_name in ((self.pager, 'tabWidth'), (self.indicator, 'tabIndicatorWidth')):
            expression = re.search(r'val currentTabLeft = ([^\n]+)', body).group(1)
            expression = expression.replace('currentTab.left', 'left').replace('currentTab.width', 'width')
            centers = [arithmetic(expression, {'left': left, 'width': width, width_name: 16})
                       for left, width in tabs]
            self.assertEqual([39, 129, 229], centers)
        for tab_name in ('nextTab', 'prevTab'):
            expression = re.search(r'val ' + tab_name + r'Left = ([^\n]+)', self.pager).group(1)
            expression = expression.replace(tab_name + '.left', 'left').replace(tab_name + '.width', 'width')
            self.assertEqual(129, arithmetic(expression, {'left': 82, 'width': 110, 'tabWidth': 16}))
        self.assertIn('lerp(currentTabLeft, nextTabLeft, fraction)', self.pager)
        self.assertIn('lerp(currentTabLeft, prevTabLeft, -fraction)', self.pager)

    def test_density_conversion_and_relative_rtl_reference_geometry(self):
        # Given sampled animation values (not animation timing), lambda placement keeps the
        # previous dp geometry after roundToPx. Relative offset mirrors it in an RTL parent.
        for density in (1, 1.5, 3):
            width = math.floor(16 * density + 0.5)
            parent_width = math.floor(400 * density + 0.5)
            for animated_dp in (39, (39 + 129) / 2, 129, 229):
                with self.subTest(density=density, sampled_dp=animated_dp):
                    x = math.floor(animated_dp * density + 0.5)
                    y = math.floor(-8 * density + 0.5)
                    ltr = x
                    rtl = parent_width - width - x
                    self.assertEqual(parent_width - width, ltr + rtl)
                    self.assertEqual(-8 * density, y)
                    self.assertGreaterEqual(min(ltr, rtl), 0)
            self.assertEqual(math.floor(84 * density + 0.5),
                             math.floor(((39 + 129) / 2) * density + 0.5))


if __name__ == '__main__':
    unittest.main()
