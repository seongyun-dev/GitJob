package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * What the run saw. Operational rather than user facing: a sudden drop in
 * filesParsed across analyses means an extractor broke, and without these
 * numbers that looks the same as repositories getting simpler.
 */
public record AnalysisStats(
        @JsonProperty("files_parsed") int filesParsed,
        @JsonProperty("files_skipped") int filesSkipped,
        @JsonProperty("import_count") int importCount,
        @JsonProperty("dependency_count") int dependencyCount,
        @JsonProperty("bytes_on_disk") long bytesOnDisk,
        @JsonProperty("duration_ms") long durationMs
) {
}
