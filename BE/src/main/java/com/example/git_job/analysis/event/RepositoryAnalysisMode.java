package com.example.git_job.analysis.event;

/**
 * Repository analysis scope requested from the Python worker.
 */
public enum RepositoryAnalysisMode {
    /** Analyze files at one immutable commit. */
    SNAPSHOT,

    /** Analyze files and a separately bounded contribution history. */
    CONTRIBUTION
}
