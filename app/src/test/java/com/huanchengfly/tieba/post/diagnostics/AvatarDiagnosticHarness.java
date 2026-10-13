package com.huanchengfly.tieba.post.diagnostics;

import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.*;
import com.huanchengfly.tieba.post.security.PublicDownloadPolicyException;

import java.io.IOException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.concurrent.CancellationException;
import javax.net.ssl.SSLException;
import javax.net.ssl.SSLHandshakeException;
import javax.net.ssl.SSLPeerUnverifiedException;

/** Pure host checks; no Android runtime, network, account, or fixture portrait is needed. */
public final class AvatarDiagnosticHarness {
    private static void check(boolean value, String label) {
        if (!value) throw new AssertionError(label);
    }

    public static void main(String[] args) {
        inputAndHostPrivacy();
        boundedSessionLifecycle();
        failureVocabulary();
        statusAndCopyPrivacy();
        stateObserverLifecycle();
        delayedSessionRace();
        System.out.println("Avatar diagnostic host checks passed");
    }

    private static void inputAndHostPrivacy() {
        check(AvatarDiagnosticStore.classifyInput(null) == InputKind.EMPTY, "null input");
        check(AvatarDiagnosticStore.classifyInput("") == InputKind.EMPTY, "empty input");
        check(AvatarDiagnosticStore.classifyInput("synthetic-portrait-secret") == InputKind.PORTRAIT_ID, "ID kind only");
        check(AvatarDiagnosticStore.classifyInput("http://tb.himg.baidu.com/sys/portrait/item/synthetic") == InputKind.HTTP_URL, "http kind");
        check(AvatarDiagnosticStore.classifyInput("HTTPS://tb.himg.baidu.com/a?BDUSS=synthetic-secret") == InputKind.HTTPS_URL, "case-insensitive classification");
        check(AvatarDiagnosticStore.classifyInput("content://private-account/secret") == InputKind.LOCAL, "local kind");
        check(AvatarDiagnosticStore.classifyInput("//tb.himg.baidu.com/private") == InputKind.OTHER, "relative URL");
        check(AvatarDiagnosticStore.classifyInput("javascript:synthetic-secret") == InputKind.OTHER, "unsupported scheme");
        check(AvatarDiagnosticStore.classifyInput(" \nsynthetic-secret") == InputKind.OTHER, "malformed input");
        check(AvatarDiagnosticStore.classifyHost("TB.HIMG.BAIDU.COM") == Host.AVATAR_CDN, "exact allowlist case");
        for (String host : new String[]{"tb.himg.baidu.com.evil.example", "secret.example", "tb.himg.baidu.com@evil.example", "tb.himg.baidu.com\nsecret", "192.0.2.1"}) {
            check(AvatarDiagnosticStore.classifyHost(host) == Host.OTHER, "host bucket");
        }
        check(AvatarDiagnosticStore.hostFromInput("https://tb.himg.baidu.com@secret.example/a") == Host.OTHER, "URL userinfo deception");
        check(AvatarDiagnosticStore.hostFromInput("https://synthetic-secret@tb.himg.baidu.com/private") == Host.AVATAR_CDN, "no userinfo retained");
    }

    private static void boundedSessionLifecycle() {
        AvatarDiagnosticStore store = new AvatarDiagnosticStore();
        check(!store.snapshot().enabled && store.snapshot().events.isEmpty(), "default off");
        check(store.open(Source.AVATAR, InputKind.PORTRAIT_ID, Host.AVATAR_CDN) == null, "no lease while off");
        store.setEnabled(true);
        Lease initial = store.open(Source.AVATAR, InputKind.PORTRAIT_ID, Host.AVATAR_CDN);
        for (int i = 0; i < AvatarDiagnosticStore.MAX_EVENTS + 5; i++) store.record(initial, Stage.START);
        check(store.snapshot().events.size() == AvatarDiagnosticStore.MAX_EVENTS, "bounded ring");
        check(store.snapshot().dropped == 5, "eviction count");
        try {
            store.snapshot().events.clear();
            throw new AssertionError("snapshot must be immutable");
        } catch (UnsupportedOperationException expected) { }
        store.clear();
        store.record(initial, Stage.ERROR);
        check(store.snapshot().enabled && store.snapshot().events.isEmpty(), "clear rejects in-flight event");
        Lease afterClear = store.open(Source.AVATAR, InputKind.HTTP_URL, Host.AVATAR_CDN);
        store.record(afterClear, Stage.SUCCESS_DOWNLOAD_CACHE);
        check(store.snapshot().events.get(0).stage == Stage.SUCCESS_DOWNLOAD_CACHE, "explicit cache source");
        store.setEnabled(false);
        store.record(afterClear, Stage.ERROR);
        check(store.snapshot().events.isEmpty(), "disable clears and rejects late event");
        store.setEnabled(true);
        store.record(initial, Stage.ERROR);
        store.record(afterClear, Stage.ERROR);
        check(store.snapshot().events.isEmpty(), "reenable rejects all previous leases");
        Lease latest = store.open(Source.AVATAR, InputKind.HTTP_URL, Host.AVATAR_CDN);
        store.record(latest, Stage.CANCELLED);
        check(store.snapshot().events.get(0).stage == Stage.CANCELLED, "current cancellation");
        check(new AvatarDiagnosticStore().snapshot().events.isEmpty(), "new process starts empty");
    }

    private static void failureVocabulary() {
        String secret = "https://private.example/portrait-id?BDUSS=synthetic-secret";
        check(AvatarDiagnosticStore.classifyFailure(new UnknownHostException(secret)) == Category.DNS, "DNS");
        check(AvatarDiagnosticStore.classifyFailure(new SocketTimeoutException(secret)) == Category.TIMEOUT, "timeout");
        check(AvatarDiagnosticStore.classifyFailure(new SSLPeerUnverifiedException(secret)) == Category.TLS_CERTIFICATE, "certificate");
        check(AvatarDiagnosticStore.classifyFailure(new SSLHandshakeException(secret)) == Category.TLS_HANDSHAKE, "handshake");
        check(AvatarDiagnosticStore.classifyFailure(new SSLException(secret)) == Category.TLS, "TLS");
        check(AvatarDiagnosticStore.classifyFailure(new IOException(secret)) == Category.IO_OR_HTTP, "IO");
        check(AvatarDiagnosticStore.classifyFailure(new RuntimeException(secret, new UnknownHostException(secret))) == Category.DNS, "bounded cause classification");
        check(AvatarDiagnosticStore.classifyFailure(new RuntimeException(secret)) == Category.OTHER, "unknown fixed bucket");
        check(AvatarDiagnosticStore.classifyFailure(new CancellationException(secret)) == Category.NONE, "cancellation");
        check(AvatarDiagnosticStore.classifyFailure(new PublicDownloadPolicyException(PublicDownloadPolicyException.Reason.METHOD)) == Category.BLOCKED_METHOD, "method policy");
        check(AvatarDiagnosticStore.classifyFailure(new PublicDownloadPolicyException(PublicDownloadPolicyException.Reason.CREDENTIALS)) == Category.BLOCKED_CREDENTIALS, "credential policy");
        check(AvatarDiagnosticStore.classifyFailure(new PublicDownloadPolicyException(PublicDownloadPolicyException.Reason.INSECURE_TRANSPORT)) == Category.BLOCKED_HTTP, "transport policy");
        RuntimeException cycle = new RuntimeException(secret);
        RuntimeException second = new RuntimeException(secret, cycle);
        cycle.initCause(second);
        check(AvatarDiagnosticStore.classifyFailure(cycle) == Category.OTHER, "cause cycle is bounded");
        AvatarDiagnosticStore store = new AvatarDiagnosticStore();
        store.setEnabled(true);
        Lease empty = store.open(Source.AVATAR, InputKind.EMPTY, Host.NONE);
        store.recordError(empty, new IOException(secret));
        check(store.snapshot().events.get(0).category == Category.EMPTY_INPUT, "empty terminal category");
        Lease ordinary = store.open(Source.AVATAR, InputKind.HTTPS_URL, Host.OTHER);
        store.recordError(ordinary, new CancellationException(secret));
        check(store.snapshot().events.get(1).stage == Stage.CANCELLED, "error-wrapped cancellation stage");
        store.recordError(ordinary, new IOException(secret));
        check(!store.snapshot().report().contains(secret) && !store.snapshot().report().contains("synthetic-secret"), "no messages exported");
    }

    private static void statusAndCopyPrivacy() {
        AvatarDiagnosticStore store = new AvatarDiagnosticStore();
        check(store.snapshot().report().contains("enabled=false events=0"), "copy off session");
        store.setEnabled(true);
        Lease network = store.open(Source.NETWORK, InputKind.HTTP_URL, Host.AVATAR_CDN);
        store.record(network, Stage.RESPONSE, Category.NONE, 302, RedirectScheme.HTTP, Host.OTHER);
        store.record(network, Stage.RESPONSE, Category.NONE, 999999, RedirectScheme.OTHER, Host.OTHER);
        String report = store.snapshot().report();
        check(report.contains("status=302") && report.contains("redirect=HTTP/other"), "bounded response metadata");
        check(!report.contains("999999") && !report.contains("https://") && !report.contains("/sys/"), "no invalid status or URL");
        check(report.contains("independent") && report.contains("do not prove a cache hit"), "coverage is explicit");
        store.clear();
        check(store.snapshot().report().contains("enabled=true events=0") && !store.snapshot().report().contains("status=302"), "copy cleared session");
        store.setEnabled(false);
        check(!store.snapshot().report().contains("redirect=HTTP"), "no stale copy after disable");
    }

    private static void stateObserverLifecycle() {
        AvatarDiagnosticStore store = new AvatarDiagnosticStore();
        AvatarDiagnosticObserver observer = new AvatarDiagnosticObserver(store, InputKind.HTTP_URL, Host.AVATAR_CDN);
        observer.observe(false, store.snapshot().generation, 1, Stage.ERROR, Category.TLS);
        check(store.snapshot().events.isEmpty(), "disabled observer");
        store.setEnabled(true);
        observer.observe(true, store.snapshot().generation, 1, Stage.ERROR, Category.TLS);
        check(store.snapshot().events.size() == 1 && store.snapshot().events.get(0).source == Source.AVATAR_SNAPSHOT, "existing error is labeled snapshot");
        store.clear();
        observer.observe(true, store.snapshot().generation, 1, Stage.ERROR, Category.TLS);
        observer.observe(true, store.snapshot().generation, 2, Stage.ERROR, Category.IO_OR_HTTP);
        check(store.snapshot().events.isEmpty(), "clear does not replay state or pair late result");
        observer.observe(true, store.snapshot().generation, 3, Stage.START, Category.NONE);
        observer.observe(true, store.snapshot().generation, 4, Stage.ERROR, Category.DNS);
        observer.observe(true, store.snapshot().generation, 4, Stage.ERROR, Category.DNS);
        check(store.snapshot().events.size() == 2 && store.snapshot().events.get(1).category == Category.DNS, "new request terminal and duplicate rejection");
        observer.observe(true, store.snapshot().generation, 5, Stage.START, Category.NONE);
        store.clear();
        observer.observe(true, store.snapshot().generation, 5, Stage.START, Category.NONE);
        observer.observe(true, store.snapshot().generation, 6, Stage.CANCELLED, Category.NONE);
        check(store.snapshot().events.isEmpty(), "clear invalidates in-flight display observation");
        observer.observe(true, store.snapshot().generation, 7, Stage.START, Category.NONE);
        store.setEnabled(false);
        observer.observe(false, store.snapshot().generation, 8, Stage.ERROR, Category.OTHER);
        observer.close();
        check(store.snapshot().events.isEmpty(), "disable invalidates observer disposal and terminal");
        store.setEnabled(true);
        observer.observe(true, store.snapshot().generation, 8, Stage.ERROR, Category.OTHER);
        check(store.snapshot().events.get(0).source == Source.AVATAR_SNAPSHOT, "reenable current state is explicit snapshot");
        observer.observe(true, store.snapshot().generation, 9, Stage.START, Category.NONE);
        observer.close();
        check(store.snapshot().events.get(2).stage == Stage.OBSERVATION_ENDED, "disposal does not claim network cancellation");

        AvatarDiagnosticStore fast = new AvatarDiagnosticStore();
        fast.setEnabled(true);
        AvatarDiagnosticObserver cache = new AvatarDiagnosticObserver(fast, InputKind.HTTPS_URL, Host.OTHER);
        cache.observe(true, fast.snapshot().generation, 0, null, Category.NONE);
        cache.observe(true, fast.snapshot().generation, 1, Stage.SUCCESS_MEMORY_OR_RESULT_CACHE, Category.NONE);
        check(fast.snapshot().events.get(0).source == Source.AVATAR_SNAPSHOT, "conflated cache hit is labeled snapshot");
        check(fast.snapshot().events.get(0).stage == Stage.SUCCESS_MEMORY_OR_RESULT_CACHE, "conflated cache source preserved");
    }

    private static void delayedSessionRace() {
        AvatarDiagnosticStore store = new AvatarDiagnosticStore();
        store.setEnabled(true);
        long oldGeneration = store.snapshot().generation;
        AvatarDiagnosticObserver observer = new AvatarDiagnosticObserver(store, InputKind.HTTP_URL, Host.AVATAR_CDN);
        observer.observe(true, oldGeneration, 0, null, Category.NONE);
        store.clear();
        observer.observe(true, oldGeneration, 1, Stage.START, Category.NONE);
        observer.observe(true, oldGeneration, 2, Stage.ERROR, Category.TLS);
        check(store.snapshot().events.isEmpty(), "delayed old session cannot lease cleared session");
        check(store.openForGeneration(oldGeneration, Source.AVATAR, InputKind.HTTP_URL, Host.AVATAR_CDN) == null, "atomic lease mismatch");
        AvatarDiagnosticObserver staleSnapshot = new AvatarDiagnosticObserver(store, InputKind.HTTP_URL, Host.AVATAR_CDN);
        staleSnapshot.observe(true, oldGeneration, 3, Stage.ERROR, Category.DNS);
        check(store.snapshot().events.isEmpty(), "delayed first snapshot cannot lease cleared session");
        long clearedGeneration = store.snapshot().generation;
        observer.observe(true, clearedGeneration, 2, Stage.ERROR, Category.TLS);
        store.setEnabled(false);
        store.setEnabled(true);
        observer.observe(true, clearedGeneration, 4, Stage.START, Category.NONE);
        observer.observe(true, clearedGeneration, 5, Stage.SUCCESS_NETWORK, Category.NONE);
        check(store.snapshot().events.isEmpty(), "delayed old enabled session cannot lease reenabled session");
    }
}
