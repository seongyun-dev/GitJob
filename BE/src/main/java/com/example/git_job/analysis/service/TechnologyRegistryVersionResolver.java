package com.example.git_job.analysis.service;

import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.util.regex.Pattern;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Resolves a request-time Registry token to one immutable content version. */
@Component
@Slf4j
public class TechnologyRegistryVersionResolver {

    static final String SUPPORTED_SCHEMA_VERSION = "technology-registry/v1";
    private static final Pattern IMMUTABLE_VERSION =
            Pattern.compile("^registry-[0-9]{8}\\.[1-9][0-9]*$");

    private final JdbcTemplate jdbc;

    public TechnologyRegistryVersionResolver(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public String resolveForNewRequest(String requestedVersion) {
        if (requestedVersion == null || requestedVersion.isBlank()) {
            throw new CustomException(ErrorCode.REGISTRY_UNAVAILABLE);
        }

        String sql;
        Object[] parameters;
        if (SUPPORTED_SCHEMA_VERSION.equals(requestedVersion)) {
            // The alias row is the explicit administrative activation boundary.
            // Never infer "latest" from lexical or date ordering.
            sql = """
                    SELECT snapshot.registry_version
                    FROM technology_registry_alias alias
                    JOIN technology_registry snapshot
                      ON snapshot.schema_version = alias.schema_version
                     AND snapshot.registry_version = alias.registry_version
                    WHERE alias.schema_version = ?
                      AND snapshot.content_sha256 IS NOT NULL
                    """;
            parameters = new Object[] {requestedVersion};
        } else if (IMMUTABLE_VERSION.matcher(requestedVersion).matches()) {
            sql = """
                    SELECT registry_version
                    FROM technology_registry
                    WHERE registry_version = ?
                      AND schema_version = ?
                      AND content_sha256 IS NOT NULL
                    """;
            parameters = new Object[] {requestedVersion, SUPPORTED_SCHEMA_VERSION};
        } else {
            throw new CustomException(ErrorCode.REGISTRY_UNAVAILABLE);
        }

        try {
            String resolved = jdbc.queryForObject(sql, String.class, parameters);
            if (resolved == null || !IMMUTABLE_VERSION.matcher(resolved).matches()) {
                log.error("Registry unavailable: invalid approved snapshot metadata");
                throw new CustomException(ErrorCode.REGISTRY_UNAVAILABLE);
            }
            return resolved;
        } catch (EmptyResultDataAccessException missing) {
            log.warn("Registry unavailable: no approved snapshot; check import and activation");
            throw new CustomException(ErrorCode.REGISTRY_UNAVAILABLE);
        } catch (DataAccessException unavailable) {
            // JDBC messages/causes may expose SQL or connection configuration.
            log.error("Registry unavailable: database access failed errorType={}",
                    unavailable.getClass().getSimpleName());
            throw new CustomException(ErrorCode.REGISTRY_UNAVAILABLE);
        }
    }
}
