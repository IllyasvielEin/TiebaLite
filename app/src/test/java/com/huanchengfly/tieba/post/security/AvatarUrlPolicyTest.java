package com.huanchengfly.tieba.post.security;

import org.junit.Test;

public final class AvatarUrlPolicyTest {
    @Test public void preservesExactRoutesAndRejectsUnrelatedAuthorities() { AvatarUrlPolicyHarness.run(); }
}
