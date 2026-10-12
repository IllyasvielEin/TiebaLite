package com.huanchengfly.tieba.post.ui.widgets.media;

import org.junit.Test;

public class PlaybackOwnershipTest {
    @Test public void dormantReleaseDoesNotCreate() { PlaybackOwnershipHarness.dormantReleaseDoesNotCreate(); }
    @Test public void activeOwnerKeepsOneResource() { PlaybackOwnershipHarness.activeOwnerKeepsOneResource(); }
    @Test public void lateAccessCannotRecreate() { PlaybackOwnershipHarness.lateAccessCannotRecreate(); }
    @Test public void explicitActivationCreatesANewLifetime() { PlaybackOwnershipHarness.explicitActivationCanCreateANewLifetime(); }
    @Test public void releaseFailureStillClearsOwnership() { PlaybackOwnershipHarness.releaseFailureStillClearsOwnership(); }
    @Test public void staleRowsCannotDetachCurrent() { PlaybackOwnershipHarness.unrelatedAndStaleRowsCannotDetach(); }
    @Test public void shutdownClearsTheCurrentRow() { PlaybackOwnershipHarness.ownerShutdownClearsTheCurrentRow(); }
    @Test public void sourceRestoreIsBoundToIdentity() { PlaybackOwnershipHarness.sameSourceRestoresButChangedSourceStartsFresh(); }
    @Test public void headerOrderAndVariantsAreHandled() { PlaybackOwnershipHarness.headerOrderIsStableButVariantsInvalidateState(); }
    @Test public void sourceTypesAndFramingDoNotAlias() { PlaybackOwnershipHarness.sourceTypesAndLengthFramingCannotAlias(); }
}
