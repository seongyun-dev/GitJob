package com.example.git_job.analysis.event;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Objects;

/**
 * A declared dependency that matched no registry technology, observed once in
 * one repository.
 *
 * <p>Dependencies only. An import path has no reliable package boundary in Java
 * or C# -- org.springframework.web and org.springframework.data.redis sit at
 * different depths, so no fixed truncation is correct -- while a manifest entry
 * is already the unit an administrator would promote.</p>
 *
 * <p>occurrenceCount counts declarations inside this one repository, for example
 * one per module of a multi-module build. Ranking for the admin screen uses
 * distinct users instead: the question is how many people a technology would
 * serve, not how many lines mention it.</p>
 */
public record TechnologyCandidate(
        @JsonProperty("ecosystem") Ecosystem ecosystem,
        @JsonProperty("coordinate") String coordinate,
        @JsonProperty("scope") String scope,
        @JsonProperty("occurrence_count") int occurrenceCount
) {

    public enum Ecosystem { MAVEN, NPM, PYPI, NUGET }

    public TechnologyCandidate {
        ecosystem = Objects.requireNonNull(ecosystem, "ecosystem must not be null");
        if (coordinate == null || coordinate.isBlank()) {
            throw new IllegalArgumentException("coordinate must be non-blank");
        }
        if (occurrenceCount < 1) {
            throw new IllegalArgumentException("occurrenceCount must be at least 1");
        }
    }
}
