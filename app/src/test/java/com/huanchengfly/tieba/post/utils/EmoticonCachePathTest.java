package com.huanchengfly.tieba.post.utils;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.nio.file.Files;

import static org.junit.Assert.*;

public class EmoticonCachePathTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    @Test public void acceptsKnownAndSafeFutureIds() throws Exception {
        File root = temporary.newFolder("emoticon");
        for (String id : new String[]{"image_emoticon1", "image_emoticon137", "face-v2_123"}) {
            assertTrue(EmoticonCachePath.isValidId(id));
            assertEquals(new File(root, id + ".png").getCanonicalFile(),
                    EmoticonCachePath.resolve(root, id));
        }
    }

    @Test public void rejectsTraversalAbsoluteEncodedAndInvalidIds() throws Exception {
        File root = temporary.newFolder("emoticon");
        for (String id : new String[]{null, "", "..", "../secret", "/tmp/secret", "a/b",
                "a\\b", "%2e%2e%2fsecret", "a\u0000b", "a:b", "a.png", " a", "中文",
                new String(new char[129]).replace('\0', 'a')}) {
            assertFalse("Unexpected valid ID", EmoticonCachePath.isValidId(id));
            assertNull(EmoticonCachePath.resolve(root, id));
        }
    }

    @Test public void rejectsSymlinkEscapingCache() throws Exception {
        File root = temporary.newFolder("emoticon");
        File outside = temporary.newFile("outside.png");
        Files.createSymbolicLink(new File(root, "image_emoticon1.png").toPath(), outside.toPath());
        assertNull(EmoticonCachePath.resolve(root, "image_emoticon1"));
    }
}
