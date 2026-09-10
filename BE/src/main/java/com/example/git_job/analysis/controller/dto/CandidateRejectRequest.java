package com.example.git_job.analysis.controller.dto;

/**
 * The note is why this is a body rather than a bare POST: a rejection that
 * nobody explained is one the next administrator has to make again.
 */
public record CandidateRejectRequest(String note) {
}
