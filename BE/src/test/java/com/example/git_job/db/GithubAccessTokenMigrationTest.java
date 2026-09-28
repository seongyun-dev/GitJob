package com.example.git_job.db;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.sql.DriverManager;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.FlywayException;
import org.flywaydb.core.api.MigrationVersion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.postgresql.PostgreSQLContainer;

@EnabledIf("com.example.git_job.support.DockerAvailable#check")
class GithubAccessTokenMigrationTest {

    @Test
    @DisplayName("V12는 이관되지 않은 GitHub 토큰이 있으면 평문 컬럼을 삭제하지 않는다")
    void migrationStopsBeforeDroppingAnExistingToken() throws Exception {
        try (var postgres = new PostgreSQLContainer("postgres:16.4-alpine")) {
            postgres.start();

            var beforeEncryption = Flyway.configure()
                    .dataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())
                    .locations("classpath:db/migration")
                    .target(MigrationVersion.fromVersion("11"))
                    .load();
            beforeEncryption.migrate();

            try (var connection = DriverManager.getConnection(
                    postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
                 var insert = connection.prepareStatement("""
                         INSERT INTO "user" (github_id, github_login, name, access_token)
                         VALUES (?, ?, ?, ?)
                         """)) {
                insert.setLong(1, 1001L);
                insert.setString(2, "migration-user");
                insert.setString(3, "Migration User");
                insert.setString(4, "existing-github-token");
                insert.executeUpdate();
            }

            var fullMigration = Flyway.configure()
                    .dataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())
                    .locations("classpath:db/migration")
                    .load();

            var failure = assertThrows(FlywayException.class, fullMigration::migrate);
            assertTrue(failure.getMessage().contains("V12 cannot drop user.access_token"));

            try (var connection = DriverManager.getConnection(
                    postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword())) {
                assertTrue(columnExists(connection, "access_token"));
                assertFalse(columnExists(connection, "access_token_enc"));
            }
        }
    }

    private static boolean columnExists(java.sql.Connection connection, String columnName)
            throws Exception {
        try (var query = connection.prepareStatement("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'user'
                      AND column_name = ?
                )
                """)) {
            query.setString(1, columnName);
            try (var result = query.executeQuery()) {
                result.next();
                return result.getBoolean(1);
            }
        }
    }
}
