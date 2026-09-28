package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;

class TechnologyRegistryVersionResolverTest {

    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final TechnologyRegistryVersionResolver resolver =
            new TechnologyRegistryVersionResolver(jdbc);

    @Test
    void resolvesTheCompatibilityTokenThroughTheExplicitActiveAlias() {
        when(jdbc.queryForObject(anyString(), eq(String.class),
                eq("technology-registry/v1"))).thenReturn("registry-20260909.1");

        assertEquals("registry-20260909.1",
                resolver.resolveForNewRequest("technology-registry/v1"));
    }

    @Test
    void verifiesAnExplicitImmutableVersionWithoutTreatingItAsAnAlias() {
        when(jdbc.queryForObject(anyString(), eq(String.class),
                eq("registry-20260908.1"), eq("technology-registry/v1")))
                .thenReturn("registry-20260908.1");

        assertEquals("registry-20260908.1",
                resolver.resolveForNewRequest("registry-20260908.1"));
        var sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).queryForObject(sql.capture(), eq(String.class),
                eq("registry-20260908.1"), eq("technology-registry/v1"));
        assertTrue(sql.getValue().contains("schema_version = ?"));
    }

    @Test
    void doesNotFallBackWhenTheDatabaseHasNoActiveSnapshot() {
        when(jdbc.queryForObject(anyString(), eq(String.class), anyString()))
                .thenThrow(new EmptyResultDataAccessException(1));

        var failure = assertThrows(CustomException.class,
                () -> resolver.resolveForNewRequest("technology-registry/v1"));

        assertEquals(ErrorCode.REGISTRY_UNAVAILABLE, failure.getErrorCode());
    }

    @Test
    void rejectsUnknownCompatibilityTokensInsteadOfLooseningContentVersions() {
        var failure = assertThrows(CustomException.class,
                () -> resolver.resolveForNewRequest("technology-registry/v2"));

        assertEquals(ErrorCode.REGISTRY_UNAVAILABLE, failure.getErrorCode());
    }

    @Test
    void databaseFailurePreservesThePublicUnavailableContract() {
        when(jdbc.queryForObject(anyString(), eq(String.class), anyString()))
                .thenThrow(new DataAccessResourceFailureException("private connection details"));

        var failure = assertThrows(CustomException.class,
                () -> resolver.resolveForNewRequest("technology-registry/v1"));

        assertEquals(ErrorCode.REGISTRY_UNAVAILABLE, failure.getErrorCode());
    }
}
