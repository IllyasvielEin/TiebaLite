package com.huanchengfly.tieba.post.security

import com.huanchengfly.tieba.post.api.interfaces.impls.MixedTiebaApiImpl
import com.huanchengfly.tieba.post.components.ImageUploader
import com.huanchengfly.tieba.post.repository.AddPostRepository
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Test

class PublicationPolicyTest {
    private fun assertPublicationBlocked(block: suspend () -> Unit) = runBlocking {
        try {
            block()
            fail("Publication must fail before accessing Android, files, accounts, or the network")
        } catch (error: IllegalStateException) {
            assertEquals(PublicationPolicy.DISABLED_MESSAGE, error.message)
        }
    }

    @Test fun capabilityCannotBeEnabledByPreferences() {
        assertFalse(PublicationPolicy.enabled)
        assertPublicationBlocked { PublicationPolicy.requireEnabled() }
    }

    @Test fun directThreadAndReplyCallsFailWithoutAnAccount() {
        assertPublicationBlocked { AddPostRepository.addThread("draft", 1, "forum").collect() }
        assertPublicationBlocked { AddPostRepository.addPost("reply", 1, "forum", 2).collect() }
        assertPublicationBlocked {
            AddPostRepository.addPost("nested reply", 1, "forum", 2, postId = 3, subPostId = 4).collect()
        }
    }

    @Test fun legacyApiCallsFailBeforeClientAndAccountInitialization() {
        val api = MixedTiebaApiImpl
        assertPublicationBlocked {
            api.addPostFlow("reply", "1", "forum", "2", null, null, null, null, null)
        }
        assertPublicationBlocked { api.addThreadFlow("draft", "forum", "1", "title", 1, 1) }
        assertPublicationBlocked { api.webReply("1", "forum", "2", "", "draft", null, "", "1", "") }
        assertPublicationBlocked { api.webReply("1", "forum", "2", "", "draft", null, "", "3", "1", "1", "") }
        assertPublicationBlocked { api.webReply("1", "forum", "2", "", "draft", null, "", "3", "4", "1", "1", "") }
        assertPublicationBlocked { api.webReplyAsync("1", "forum", "2", "", "draft", null, "", "1", "") }
        assertPublicationBlocked { api.webReplyAsync("1", "forum", "2", "", "draft", null, "", "3", "1", "1", "") }
        assertPublicationBlocked { api.webReplyAsync("1", "forum", "2", "", "draft", null, "", "3", "4", "1", "1", "") }
    }

    @Test fun mediaIsBlockedBeforeFilesAreReadIncludingEmptyBatches() {
        val uploader = ImageUploader("forum")
        assertPublicationBlocked { uploader.uploadSinglePicture("/nonexistent/test-image") }
        assertPublicationBlocked { uploader.uploadImages(listOf("/nonexistent/test-image")).collect() }
        assertPublicationBlocked { uploader.uploadImages(emptyList()).collect() }
    }
}
