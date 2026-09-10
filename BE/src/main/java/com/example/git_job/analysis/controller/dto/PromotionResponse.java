package com.example.git_job.analysis.controller.dto;

import com.example.git_job.analysis.service.TechnologyCandidateAdminService.RegistryStatus;

/**
 * What a promotion produced.
 *
 * <p>{@code techId} is here because the administrator usually does not supply
 * one -- it is derived from the coordinate -- and the screen has to show what
 * the technology ended up being called.</p>
 */
public record PromotionResponse(String techId, RegistryStatus registry) {
}
