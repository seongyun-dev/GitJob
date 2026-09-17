package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.Test;

class CurrentRegistryVersionTest {

    @Test
    void resolvesTheVersionThroughTheRegistryActivationAlias() {
        var resolver = mock(TechnologyRegistryVersionResolver.class);
        when(resolver.resolveForNewRequest(
                TechnologyRegistryVersionResolver.SUPPORTED_SCHEMA_VERSION))
                .thenReturn("registry-20260911.4");

        var current = new CurrentRegistryVersion(resolver);

        assertEquals("registry-20260911.4", current.resolve());
        verify(resolver).resolveForNewRequest(
                TechnologyRegistryVersionResolver.SUPPORTED_SCHEMA_VERSION);
    }
}
