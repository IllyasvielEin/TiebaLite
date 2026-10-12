package com.huanchengfly.tieba.post.utils;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class PickerUriPolicyTest {
    @Test public void permitsSelectedProviderContentIncludingCloudAndDocuments() {
        assertTrue(PickerUriPolicy.isAllowed("content", "media"));
        assertTrue(PickerUriPolicy.isAllowed("content", "com.android.providers.media.documents"));
        assertTrue(PickerUriPolicy.isAllowed("content", "example.cloud.provider"));
    }

    @Test public void rejectsNetworkAndFileUrisBeforeGenericImageLoading() {
        for (String scheme : new String[]{"http", "https", "file", "data", "android.resource", "intent"}) {
            assertFalse(PickerUriPolicy.isAllowed(scheme, "example.com"));
        }
    }

    @Test public void rejectsMissingSchemeOrProvider() {
        assertFalse(PickerUriPolicy.isAllowed(null, "media"));
        assertFalse(PickerUriPolicy.isAllowed("", "media"));
        assertFalse(PickerUriPolicy.isAllowed("content", null));
        assertFalse(PickerUriPolicy.isAllowed("content", ""));
        assertFalse(PickerUriPolicy.isAllowed("content", " \t"));
    }

    @Test public void doesNotNormalizeAnUnsupportedSchemeForTheLoader() {
        assertFalse(PickerUriPolicy.isAllowed("CONTENT", "media"));
        assertFalse(PickerUriPolicy.isAllowed(" content", "media"));
    }
}
