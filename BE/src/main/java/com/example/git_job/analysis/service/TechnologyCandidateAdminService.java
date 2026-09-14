package com.example.git_job.analysis.service;

import com.example.git_job.analysis.store.RegistryDraftStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore.Ranked;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.regex.Pattern;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * What an administrator can do with the candidate list.
 *
 * <p>Promotion and rejection both end a candidate's review. Promotion also
 * writes into the registry, and that is why it goes through a draft rather
 * than the current version: an analysis event carries the version it was
 * judged with, so changing a published version rewrites the basis of results
 * that already exist.</p>
 *
 * <p>Every refusal is a {@link CustomException}. Returning a status the caller
 * has to interpret would put a second error shape next to the one the whole
 * API already uses, and the client only understands the one.</p>
 */
@Service
@RequiredArgsConstructor
public class TechnologyCandidateAdminService {

    private static final Logger log =
            LoggerFactory.getLogger(TechnologyCandidateAdminService.class);

    /** Same shape as the seeded ids: lowercase, digits and hyphens. */
    private static final Pattern TECH_ID = Pattern.compile("^[a-z0-9][a-z0-9-]{0,79}$");

    /** Package coordinates are what a candidate is, so this is the mapping it becomes. */
    private static final String MAPPING_TYPE = "PACKAGE";

    /** The statuses a candidate can still be decided from. */
    private static final List<String> UNDECIDED = List.of("NEW", "REVIEWING");

    private final TechnologyCandidateStore candidates;
    private final RegistryDraftStore drafts;

    public List<Ranked> list(int limit) {
        return candidates.topCandidates(Math.clamp(limit, 1, 200));
    }

    /**
     * Adds the candidate to the draft registry and marks it decided.
     *
     * <p>The mapping is {@code EXACT} on the coordinate the candidate already
     * is. A prefix would be broader than the evidence: nobody observed the
     * other artifacts it would match, and npm and PyPI have no prefix boundary
     * at all.</p>
     *
     * @return the technology id it was registered under
     */
    @Transactional
    public String promote(long candidateId, String techId, String displayName,
            List<String> jobDomains, long adminUserId, String note) {
        Ranked candidate = candidates.findById(candidateId).orElseThrow(
                () -> new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_NOT_FOUND));
        // Two administrators looking at the same list is the normal case, and
        // the second one gets a 409 rather than an error. The check further
        // down is for the narrow race where the row changes after this read.
        if (!UNDECIDED.contains(candidate.status())) {
            throw new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED);
        }
        String id = normalizeTechId(techId, candidate);
        Instant now = Instant.now();

        String draft = drafts.openDraft(now);
        drafts.addTechnology(draft, id,
                displayName == null || displayName.isBlank() ? candidate.coordinate() : displayName,
                jobDomains == null || jobDomains.isEmpty() ? List.of("BACKEND") : jobDomains,
                MAPPING_TYPE, candidate.ecosystem(), candidate.coordinate(), "EXACT");

        if (!candidates.decide(candidateId, "PROMOTED", id, adminUserId, note, now)) {
            // Someone decided it between the read and the write. The draft edit
            // is rolled back with this transaction rather than left half-applied:
            // otherwise the technology sits in the registry while the candidate
            // carries the other decision, and the next promotion adds it twice.
            throw new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED);
        }
        log.info("Candidate promoted: candidateId={}, techId={}, draft={}, by={}",
                candidateId, id, draft, adminUserId);
        return id;
    }

    /**
     * Marks the candidate as one not to register.
     *
     * <p>It keeps accumulating observations. That is deliberate: a rejection
     * made when three people used something should be reviewable when three
     * hundred do, and deleting the row would hide that.</p>
     */
    @Transactional
    public void reject(long candidateId, long adminUserId, String note) {
        if (candidates.findById(candidateId).isEmpty()) {
            throw new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_NOT_FOUND);
        }
        if (!candidates.decide(candidateId, "REJECTED", null, adminUserId, note, Instant.now())) {
            throw new CustomException(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED);
        }
        log.info("Candidate rejected: candidateId={}, by={}", candidateId, adminUserId);
    }

    /** Publishes the draft. Analyses requested after this use the new version. */
    @Transactional
    public String publishDraft() {
        String draft = drafts.draftVersion().orElseThrow(
                () -> new CustomException(ErrorCode.REGISTRY_DRAFT_EMPTY));
        drafts.publish(draft, Instant.now());
        log.info("Registry published: version={}", draft);
        return draft;
    }

    public RegistryStatus registryStatus() {
        return new RegistryStatus(drafts.currentVersion().orElse(null),
                drafts.draftVersion().orElse(null));
    }

    /**
     * The id the technology gets. Derived from the coordinate when the caller
     * does not supply one, because a coordinate is not a usable id -- it has a
     * colon, a slash or dots depending on the ecosystem.
     */
    private String normalizeTechId(String supplied, Ranked candidate) {
        String candidateId = supplied == null || supplied.isBlank()
                ? candidate.coordinate()
                        .toLowerCase(Locale.ROOT)
                        .replaceAll("^@", "")
                        .replaceAll("[^a-z0-9]+", "-")
                        .replaceAll("^-+|-+$", "")
                : supplied.trim();
        if (!TECH_ID.matcher(candidateId).matches()) {
            throw new CustomException(ErrorCode.INVALID_TECHNOLOGY_ID);
        }
        return candidateId;
    }

    public record RegistryStatus(String current, String draft) {
    }
}
