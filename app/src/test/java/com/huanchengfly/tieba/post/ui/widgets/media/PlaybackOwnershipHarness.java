package com.huanchengfly.tieba.post.ui.widgets.media;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** Pure JVM assertions: these do not emulate Android, Compose, Media3, or coroutine scheduling. */
public final class PlaybackOwnershipHarness {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    public static void dormantReleaseDoesNotCreate() {
        int[] created = {0};
        PlaybackResource<Object> resource = new PlaybackResource<>(
                () -> { created[0]++; return new Object(); }, value -> {});
        require(resource.getOrCreate() == null, "inactive access must not create");
        resource.release();
        resource.activate();
        resource.release();
        require(created[0] == 0, "release must not allocate an unused preview/player");
    }

    public static void activeOwnerKeepsOneResource() {
        int[] created = {0};
        int[] released = {0};
        PlaybackResource<Object> resource = new PlaybackResource<>(
                () -> { created[0]++; return new Object(); }, value -> released[0]++);
        resource.activate();
        Object first = resource.getOrCreate();
        // Represents stable ownership while presentation moves/recomposes; not a Compose test.
        for (int i = 0; i < 20; i++) {
            resource.activate();
            require(resource.getOrCreate() == first, "stable owner replaced its resource");
        }
        require(created[0] == 1 && released[0] == 0, "presentation must not churn resources");
        resource.release();
        require(released[0] == 1, "owner exit must release exactly once");
    }

    public static void lateAccessCannotRecreate() {
        int[] created = {0};
        int[] released = {0};
        PlaybackResource<Object> resource = new PlaybackResource<>(
                () -> { created[0]++; return new Object(); }, value -> released[0]++);
        resource.activate();
        resource.getOrCreate();
        resource.release();
        for (int i = 0; i < 20; i++) {
            resource.release();
            require(resource.getOrCreate() == null && resource.peek() == null,
                    "late callback resurrected a closed resource");
        }
        require(created[0] == 1 && released[0] == 1, "release is not idempotent");
    }

    public static void explicitActivationCanCreateANewLifetime() {
        int[] released = {0};
        PlaybackResource<Object> resource = new PlaybackResource<>(Object::new, value -> released[0]++);
        resource.activate();
        Object first = resource.getOrCreate();
        resource.release();
        resource.activate();
        require(resource.getOrCreate() != first, "explicit new owner reused a released instance");
        resource.release();
        require(released[0] == 2, "each lifetime must release once");
    }

    public static void releaseFailureStillClearsOwnership() {
        PlaybackResource<Object> resource = new PlaybackResource<>(Object::new,
                value -> { throw new IllegalStateException("synthetic release failure"); });
        resource.activate();
        resource.getOrCreate();
        try {
            resource.release();
            throw new AssertionError("expected failure");
        } catch (IllegalStateException expected) {
            require(resource.peek() == null && resource.getOrCreate() == null,
                    "failing release left an active resource");
        }
        resource.release();
    }

    public static void unrelatedAndStaleRowsCannotDetach() {
        PlaybackOwner<Object> owner = new PlaybackOwner<>();
        Object a = new String("same media"), b = new String("same media");
        require(owner.replace(a) == null, "first attach has no previous row");
        require(!owner.detach(b) && owner.owns(a), "equal media is not row identity");
        require(owner.replace(b) == a, "switch must return the old UI for reset");
        require(!owner.detach(a) && owner.owns(b), "disposing old row detached the new row");
        require(owner.detach(b) && !owner.detach(b), "current detach must be idempotent");
        require(owner.get() == null && !owner.owns(null), "detached owner remains visible");
    }

    public static void ownerShutdownClearsTheCurrentRow() {
        PlaybackOwner<Object> owner = new PlaybackOwner<>();
        Object a = new Object();
        owner.replace(a);
        require(owner.clear() == a && owner.get() == null, "shutdown did not return/clear owner");
        require(owner.clear() == null && !owner.detach(a), "shutdown was not idempotent");
    }

    public static void sameSourceRestoresButChangedSourceStartsFresh() {
        String a = PlaybackSourceIdentity.forNetwork("https://media.invalid/a", Collections.emptyMap());
        String aAgain = PlaybackSourceIdentity.forNetwork("https://media.invalid/a", Collections.emptyMap());
        String b = PlaybackSourceIdentity.forNetwork("https://media.invalid/b", Collections.emptyMap());
        Object savedPositionAndFullscreen = new Object(), initialPositionAndFullscreen = new Object();
        require(PlaybackSourceIdentity.restoreOrDefault(a, aAgain, savedPositionAndFullscreen,
                initialPositionAndFullscreen) == savedPositionAndFullscreen, "same source lost saved state");
        require(PlaybackSourceIdentity.restoreOrDefault(a, b, savedPositionAndFullscreen,
                initialPositionAndFullscreen) == initialPositionAndFullscreen, "new source inherited old state");
        require(PlaybackSourceIdentity.restoreOrDefault(null, a, savedPositionAndFullscreen,
                initialPositionAndFullscreen) == initialPositionAndFullscreen, "legacy state was trusted without identity");
    }

    public static void headerOrderIsStableButVariantsInvalidateState() {
        Map<String, String> first = new LinkedHashMap<>();
        first.put("X-Variant", "one");
        first.put("Authorization", "synthetic-token");
        Map<String, String> reordered = new LinkedHashMap<>();
        reordered.put("Authorization", "synthetic-token");
        reordered.put("X-Variant", "one");
        String a = PlaybackSourceIdentity.forNetwork("https://media.invalid/a?token=synthetic", first);
        String equivalent = PlaybackSourceIdentity.forNetwork("https://media.invalid/a?token=synthetic", reordered);
        require(a.equals(equivalent), "map order changed source identity");
        reordered.put("Authorization", "different-synthetic-token");
        String changed = PlaybackSourceIdentity.forNetwork("https://media.invalid/a?token=synthetic", reordered);
        require(!a.equals(changed), "header variant inherited identity");
        Object saved = new Object(), fresh = new Object();
        require(PlaybackSourceIdentity.restoreOrDefault(a, changed, saved, fresh) == fresh,
                "changed header variant restored another variant's state");
        require(a.matches("v1:[0-9a-f]{64}") && !a.contains("synthetic") && !a.contains("media.invalid"),
                "discriminator exposes raw URL/header material");
    }

    public static void sourceTypesAndLengthFramingCannotAlias() {
        String raw = PlaybackSourceIdentity.forRaw(42);
        require(raw.equals(PlaybackSourceIdentity.forRaw(42)), "raw identity is unstable");
        require(!raw.equals(PlaybackSourceIdentity.forRaw(43)), "different raw media share identity");
        require(!raw.equals(PlaybackSourceIdentity.forNetwork("42", Collections.emptyMap())),
                "raw/network types share identity");
        require(!raw.equals(PlaybackSourceIdentity.none()), "null/raw source share identity");
        String first = PlaybackSourceIdentity.forNetwork("u", Collections.singletonMap("ab", "c"));
        String second = PlaybackSourceIdentity.forNetwork("u", Collections.singletonMap("a", "bc"));
        require(!first.equals(second), "unframed header concatenation alias");
    }

    public static void main(String[] args) {
        dormantReleaseDoesNotCreate();
        activeOwnerKeepsOneResource();
        lateAccessCannotRecreate();
        explicitActivationCanCreateANewLifetime();
        releaseFailureStillClearsOwnership();
        unrelatedAndStaleRowsCannotDetach();
        ownerShutdownClearsTheCurrentRow();
        sameSourceRestoresButChangedSourceStartsFresh();
        headerOrderIsStableButVariantsInvalidateState();
        sourceTypesAndLengthFramingCannotAlias();
        System.out.println("10 pure playback ownership/resource/source-identity scenarios passed");
    }
}
