package com.huanchengfly.tieba.post.models.database

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccountRedactionTest {
    @Test
    fun stringRepresentationNeverIncludesCredentialsOrProfile() {
        val secrets = listOf("fake-bduss", "fake-stoken", "fake-cookie", "fake-tbs", "fake-zid", "fake-name")
        val account = Account(bduss = secrets[0], sToken = secrets[1], cookie = secrets[2],
            tbs = secrets[3], zid = secrets[4], name = secrets[5])
        for (secret in secrets) assertFalse(account.toString().contains(secret))
        assertTrue(account.toString().contains("[REDACTED]"))
        // Redaction must not erase credentials used by the app.
        assertTrue(account.bduss == secrets[0])
    }
}
