"""Source regression checks supplement JVM tests; do not prove runtime UI behavior."""
from pathlib import Path
import unittest
import re

JAVA = Path(__file__).resolve().parents[2] / "main/java/com/huanchengfly/tieba/post"


class PublicationBoundaries(unittest.TestCase):
    def test_single_immutable_disabled_capability(self):
        policy = (JAVA / "security/PublicationPolicy.kt").read_text()
        self.assertIn("val enabled: Boolean = false", policy)
        self.assertNotIn("var enabled", policy)
        self.assertNotIn("appPreferences", policy)

    def test_composer_guard_precedes_draft_and_account_access(self):
        source = (JAVA / "ui/page/reply/ReplyPage.kt").read_text()
        body = source.split("internal fun ReplyPageContent(", 1)[1]
        guard = body.index("if (!PublicationPolicy.enabled)")
        self.assertLess(guard, body.index("val hash = remember"))
        self.assertLess(guard, body.index("AccountUtil.getAccountInfo"))
        self.assertIn("return", body[guard:body.index("val hash = remember")])
        self.assertIn("TextButton(onClick = onBack)", body)
        self.assertEqual(3, source.count("ReplyPageContent(\n"))  # definition, dialog and destination

    def test_service_and_media_guards_are_before_work(self):
        source = (JAVA / "repository/AddPostRepository.kt").read_text()
        self.assertEqual(2, source.count("PublicationPolicy.requireEnabled()"))
        for name in ("addThread", "addPost"):
            method = source.split("fun " + name + "(", 1)[1]
            self.assertLess(method.index("PublicationPolicy.requireEnabled()"), method.index("TiebaApi.getInstance()"))
        source = (JAVA / "ui/page/reply/ReplyViewModel.kt").read_text()
        for name, work in (("Send", "AddPostRepository"), ("UploadImages", "ImageUploader")):
            method = source.split("private fun ReplyUiIntent." + name + ".producePartialChange()", 1)[1]
            self.assertLess(method.index("if (!PublicationPolicy.enabled)"), method.index(work))
        source = (JAVA / "components/ImageUploader.kt").read_text()
        method = source.split("suspend fun uploadSinglePicture(", 1)[1]
        self.assertLess(method.index("PublicationPolicy.requireEnabled()"), method.index("BitmapFactory"))

    def test_legacy_api_guards_precede_media_and_request_preparation(self):
        source = (JAVA / "api/interfaces/impls/MixedTiebaApiImpl.kt").read_text()
        methods = re.findall(
            r"override fun (webUploadPic|webReplyAsync|webReply|addPostFlow|addThreadFlow)\("
            r".*?(?=\n    override fun |\Z)", source, flags=re.S
        )
        self.assertEqual(9, len(methods))
        blocks = re.split(r"(?=    override fun )", source)
        checked = 0
        for block in blocks:
            if not re.match(r"    override fun (webUploadPic|webReplyAsync|webReply|addPostFlow|addThreadFlow)\(", block):
                continue
            checked += 1
            body = block.split("{", 1)[1].lstrip()
            self.assertTrue(body.startswith("PublicationPolicy.requireEnabled()"), block[:90])
        self.assertEqual(9, checked)

    def test_floor_and_subreply_detail_taps_are_never_reply_events(self):
        thread = (JAVA / "ui/page/thread/ThreadPage.kt").read_text()
        floor = thread.split("fun PostCard(", 1)[1].split("private fun SubPostItem(", 1)[0]
        trigger = floor.split("LongClickMenu(", 1)[1].split("menuContent =", 1)[0]
        self.assertIn("onClick = null", trigger)
        self.assertNotIn("onReplyClick(", trigger)
        detail = (JAVA / "ui/page/subposts/SubPostsPage.kt").read_text().split("private fun SubPostItem(", 1)[1]
        self.assertIn("onClick = null\n        )", detail)
        self.assertNotIn("onClick = { onReplyClick", detail)
        for source in (floor, detail):
            self.assertIn("R.string.menu_copy", source)
            self.assertIn("R.string.title_report", source)
            self.assertIn("onMenuDeleteClick", source)

    def test_preview_taps_still_open_subreply_details_and_content_keeps_handlers(self):
        source = (JAVA / "ui/page/thread/ThreadPage.kt").read_text()
        preview = source.split("private fun SubPostItem(", 1)[1].split("fun UserNameText(", 1)[0]
        self.assertIn("onClick = {\n            onOpenSubPosts(subPostList.get { id })", preview)
        self.assertIn("SubPostsSheetPageDestination(", source)
        floor = source.split("fun PostCard(", 1)[1].split("private fun SubPostItem(", 1)[0]
        self.assertIn("render.Render()", floor)
        self.assertIn("PicWaterfallContentRender(it)", floor)
        self.assertIn("onUserClick(author)", floor)
        detail = (JAVA / "ui/page/subposts/SubPostsPage.kt").read_text().split("private fun SubPostItem(", 1)[1]
        self.assertIn("contentRenders.fastForEach { it.Render() }", detail)
        self.assertIn("onUserClick(author.get())", detail)

    def test_long_press_only_menu_has_no_tap_action_or_ripple(self):
        source = (JAVA / "ui/widgets/compose/Menu.kt").read_text().split("fun LongClickMenu(", 1)[1]
        click_branch = source.split("val triggerModifier = if (onClick != null)", 1)[1].split("} else if (enabled)", 1)[0]
        self.assertIn("Modifier.combinedClickable(", click_branch)
        self.assertIn("onClick()", click_branch)
        long_only = source.split("} else if (enabled)", 1)[1].split("} else {", 1)[0]
        self.assertIn("detectTapGestures(onLongPress", long_only)
        self.assertIn("menuState.offset = position", long_only)
        self.assertIn(".semantics {", long_only)
        self.assertIn("onLongClick {", long_only)
        self.assertNotIn("onClick =", long_only)
        self.assertNotIn("onTap =", long_only)
        self.assertNotIn("combinedClickable", long_only)
        self.assertNotIn("indication =", long_only)

    def test_composer_affordances_respect_capability(self):
        for filename in ("thread/ThreadPage.kt", "subposts/SubPostsPage.kt"):
            for line in (JAVA / "ui/page" / filename).read_text().splitlines():
                if "appPreferences.hideReply" in line:
                    self.assertIn("PublicationPolicy.enabled", line)
        forum = (JAVA / "ui/page/forum/ForumPage.kt").read_text()
        self.assertIn('PublicationPolicy.enabled && context.appPreferences.forumFabFunction == "post"', forum)


if __name__ == "__main__":
    unittest.main()
