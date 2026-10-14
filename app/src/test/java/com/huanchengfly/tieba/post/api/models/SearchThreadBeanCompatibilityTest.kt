package com.huanchengfly.tieba.post.api.models

import com.huanchengfly.tieba.post.api.retrofit.NullOnEmptyConverterFactory
import com.huanchengfly.tieba.post.api.retrofit.converter.gson.GsonConverterFactory
import com.huanchengfly.tieba.post.api.retrofit.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.SerializationException
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Test
import retrofit2.Retrofit

class SearchThreadBeanCompatibilityTest {
    // Match the existing production options; no new permissive parser/fallback behavior.
    private val json = Json {
        isLenient = true
        ignoreUnknownKeys = true
        coerceInputValues = true
    }
    private val retrofit = Retrofit.Builder()
        .baseUrl("https://tieba.baidu.com/")
        .addConverterFactory(NullOnEmptyConverterFactory())
        .addConverterFactory(json.asConverterFactory())
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    private enum class Model { THREAD, MAIN_POST, POST_INFO }
    private data class ContentCase(val label: String, val input: JsonElement?, val expected: String)
    private val cases = listOf(
        ContentCase("normal", JsonPrimitive("plain content"), "plain content"),
        ContentCase("null", JsonNull, ""),
        ContentCase("omitted", null, ""),
        ContentCase("empty", JsonPrimitive(""), ""),
        ContentCase("whitespace", JsonPrimitive(" \t\n "), " \t\n "),
        ContentCase("highlight", JsonPrimitive("<em>matched</em> &amp; tail"), "<em>matched</em> &amp; tail"),
    )
    private val normal = JsonPrimitive("plain content")
    private val user = buildJsonObject {
        put("user_name", "synthetic-user")
        put("show_nickname", "Synthetic")
        put("portrait", "synthetic-portrait")
    }

    private fun fixture(model: Model, content: JsonElement?): JsonObject = buildJsonObject {
        put("title", "synthetic title")
        content?.let { put("content", it) }
        put("user", user)
        when (model) {
            Model.THREAD -> {
                put("tid", "123")
                put("pid", "456")
                put("time", "1700000000")
                put("modified_time", 1700000001L)
                put("post_num", "2")
                put("like_num", "3")
                put("share_num", "4")
                put("forum_id", "5")
                put("forum_name", "synthetic forum")
                put("type", 1)
                put("forum_info", buildJsonObject {
                    put("forum_name", "synthetic forum")
                    put("avatar", "synthetic-avatar")
                })
            }
            Model.MAIN_POST -> {
                put("tid", 123L)
                put("like_num", "3")
                put("share_num", "4")
                put("post_num", "2")
            }
            Model.POST_INFO -> {
                put("tid", 123L)
                put("pid", 456L)
            }
        }
    }

    private fun responseFixture(content: JsonElement?, changedModel: Model? = null,
                                changedFixture: JsonObject? = null): JsonObject {
        fun selected(model: Model) = if (changedModel == model) changedFixture!! else fixture(model, content)
        val thread = JsonObject(selected(Model.THREAD) + mapOf(
            "main_post" to selected(Model.MAIN_POST),
            "post_info" to selected(Model.POST_INFO),
        ))
        return buildJsonObject {
            put("no", 0)
            put("error", "")
            put("data", buildJsonObject {
                put("has_more", 1)
                put("current_page", 2)
                put("post_list", buildJsonArray { add(thread) })
            })
            put("unknown_fixture_field", true)
        }
    }

    private inline fun <reified T> converted(input: JsonObject): T {
        val converter = retrofit.responseBodyConverter<T>(T::class.java, emptyArray())
        return requireNotNull(converter.convert(input.toString().toResponseBody("application/json".toMediaType())))
    }

    private fun contentOf(model: Model, input: JsonObject, throughConverter: Boolean): String {
        return when (model) {
            Model.THREAD -> if (throughConverter) converted<SearchThreadBean.ThreadInfoBean>(input).content
                else json.decodeFromString<SearchThreadBean.ThreadInfoBean>(input.toString()).content
            Model.MAIN_POST -> if (throughConverter) converted<SearchThreadBean.MainPost>(input).content
                else json.decodeFromString<SearchThreadBean.MainPost>(input.toString()).content
            Model.POST_INFO -> if (throughConverter) converted<SearchThreadBean.PostInfo>(input).content
                else json.decodeFromString<SearchThreadBean.PostInfo>(input.toString()).content
        }
    }

    @Test fun allThreeModelsCoerceOnlyNullOrOmittedContentAndKeepRealStrings() {
        for (model in Model.entries) {
            for (case in cases) {
                for (throughConverter in listOf(false, true)) {
                    assertEquals("$model ${case.label} converter=$throughConverter", case.expected,
                        contentOf(model, fixture(model, case.input), throughConverter))
                }
            }
        }
    }

    @Test fun completeSearchResponsesPreserveNestedContentAcrossTheActualConverterChain() {
        for (case in cases) {
            val decoded = converted<SearchThreadBean>(responseFixture(case.input))
            assertEquals(0, decoded.errorCode)
            assertEquals(2, decoded.data.currentPage)
            assertEquals(1, decoded.data.hasMore)
            assertEquals(1, decoded.data.postList.size)
            val thread = decoded.data.postList.single()
            assertEquals("synthetic title", thread.title)
            assertEquals("123", thread.tid)
            assertEquals("0", thread.cid)
            assertEquals(case.expected, thread.content)
            assertNotNull(thread.mainPost)
            assertNotNull(thread.postInfo)
            assertEquals(case.expected, thread.mainPost!!.content)
            assertEquals(case.expected, thread.postInfo!!.content)
            assertEquals(123L, thread.mainPost!!.tid)
            assertEquals(456L, thread.postInfo!!.pid)
        }
    }

    @Test fun objectOrArrayContentStillFailsForEachModelAndNestedResponse() {
        val invalid = listOf(buildJsonObject { put("unexpected", "object") }, buildJsonArray { add(JsonPrimitive("array")) })
        for (model in Model.entries) {
            for (content in invalid) {
                val input = fixture(model, content)
                for (throughConverter in listOf(false, true)) {
                    assertThrows(SerializationException::class.java) { contentOf(model, input, throughConverter) }
                }
                assertThrows(SerializationException::class.java) {
                    converted<SearchThreadBean>(responseFixture(normal, model, input))
                }
            }
        }
    }

    @Test fun otherRequiredFieldsAndInvalidTypesStillFailWithoutGsonFallback() {
        for (model in Model.entries) {
            val input = fixture(model, normal)
            val missingTitle = JsonObject(input - "title")
            val invalidTitle = JsonObject(input + ("title" to buildJsonObject { put("bad", true) }))
            for (broken in listOf(missingTitle, invalidTitle)) {
                for (throughConverter in listOf(false, true)) {
                    assertThrows(SerializationException::class.java) { contentOf(model, broken, throughConverter) }
                }
                assertThrows(SerializationException::class.java) {
                    converted<SearchThreadBean>(responseFixture(normal, model, broken))
                }
            }
        }
        val missingEnvelopeField = JsonObject(responseFixture(normal) - "data")
        assertThrows(SerializationException::class.java) { converted<SearchThreadBean>(missingEnvelopeField) }
    }
}
