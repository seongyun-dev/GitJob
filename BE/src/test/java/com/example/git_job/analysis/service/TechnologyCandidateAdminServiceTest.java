package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.store.RegistryDraftStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore.Ranked;
import com.example.git_job.global.exceptions.CustomException;
import com.example.git_job.global.exceptions.ErrorCode;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * The decisions an administrator makes on the candidate list.
 *
 * <p>What is worth pinning here is that a decision either lands whole or not at
 * all: a candidate marked PROMOTED whose technology never reached the registry
 * disappears from the list without ever being registered, and nobody notices
 * because the row looks handled.</p>
 */
class TechnologyCandidateAdminServiceTest {

    private static final long ADMIN = 42L;
    private static final Instant SEEN = Instant.parse("2026-09-10T00:00:00Z");
    private static final String DRAFT = "registry-20260910.3";

    private TechnologyCandidateStore candidates;
    private RegistryDraftStore drafts;
    private TechnologyCandidateAdminService admin;

    @BeforeEach
    void setup() {
        candidates = mock(TechnologyCandidateStore.class);
        drafts = mock(RegistryDraftStore.class);
        admin = new TechnologyCandidateAdminService(candidates, drafts);
        when(drafts.openDraft(any())).thenReturn(DRAFT);
        when(candidates.decide(anyLong(), anyString(), any(), anyLong(), any(), any()))
                .thenReturn(true);
    }

    private Ranked candidate(String ecosystem, String coordinate, String status) {
        when(candidates.findById(1L)).thenReturn(Optional.of(new Ranked(
                1L, ecosystem, coordinate, "MAIN", status, 9, 12, 30, SEEN, SEEN)));
        return candidates.findById(1L).orElseThrow();
    }

    @Test
    @DisplayName("승격은 후보가 가진 좌표를 EXACT 매핑으로 초안에 넣는다")
    void promotionAddsAnExactMappingForTheObservedCoordinate() {
        // PREFIX 로 넓히면 아무도 쓰는 걸 본 적 없는 아티팩트까지 그 기술로
        // 판정된다. 관찰한 것보다 넓은 근거는 만들지 않는다.
        candidate("MAVEN", "io.jsonwebtoken:jjwt-api", "NEW");

        assertEquals("io-jsonwebtoken-jjwt-api",
                admin.promote(1L, null, null, null, ADMIN, null));

        verify(drafts).addTechnology(eq(DRAFT), eq("io-jsonwebtoken-jjwt-api"),
                eq("io.jsonwebtoken:jjwt-api"), eq(List.of("BACKEND")),
                eq("PACKAGE"), eq("MAVEN"), eq("io.jsonwebtoken:jjwt-api"), eq("EXACT"));
    }

    @Test
    @DisplayName("tech_id 를 안 주면 좌표에서 만든다")
    void anIdIsDerivedFromTheCoordinate() {
        // 좌표는 그대로 id 가 될 수 없다. 생태계마다 콜론, 슬래시, 점, @ 가 섞인다.
        candidate("NPM", "@nestjs/core", "NEW");

        admin.promote(1L, null, "NestJS", List.of("BACKEND"), ADMIN, null);

        verify(drafts).addTechnology(anyString(), eq("nestjs-core"), eq("NestJS"),
                any(), anyString(), anyString(), anyString(), anyString());
    }

    @Test
    @DisplayName("id 형식이 아니면 거절하고 아무것도 쓰지 않는다")
    void anIllFormedIdIsRefusedBeforeAnythingIsWritten() {
        candidate("MAVEN", "org.example:thing", "NEW");

        assertEquals(ErrorCode.INVALID_TECHNOLOGY_ID, assertThrows(CustomException.class,
                () -> admin.promote(1L, "Spring Boot!", null, null, ADMIN, null)).getErrorCode());

        verify(drafts, never()).addTechnology(anyString(), anyString(), anyString(),
                any(), anyString(), anyString(), anyString(), anyString());
        verify(candidates, never()).decide(anyLong(), anyString(), any(), anyLong(),
                any(), any());
    }

    @Test
    @DisplayName("이미 처리된 후보는 초안을 건드리지 않고 409 로 끝난다")
    void anAlreadyDecidedCandidateIsNotPromotedAgain() {
        // 관리자 둘이 같은 목록을 보고 있는 건 정상이다. 두 번째 사람에게는
        // 오류가 아니라 지금 상태를 보여주면 된다.
        candidate("MAVEN", "org.example:thing", "PROMOTED");

        assertEquals(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED,
                assertThrows(CustomException.class,
                        () -> admin.promote(1L, null, null, null, ADMIN, null)).getErrorCode());

        verifyNoInteractions(drafts);
    }

    @Test
    @DisplayName("읽은 뒤 누가 먼저 처리했으면 초안 편집까지 되돌린다")
    void aRaceAfterTheReadRollsBackTheDraftEdit() {
        // 여기서 그냥 넘어가면 기술은 초안에 들어갔는데 후보는 다른 사람의
        // 결정대로 남아, 같은 기술이 두 번 등록될 수 있다.
        candidate("MAVEN", "org.example:thing", "NEW");
        when(candidates.decide(anyLong(), anyString(), any(), anyLong(), any(), any()))
                .thenReturn(false);

        assertEquals(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED,
                assertThrows(CustomException.class,
                        () -> admin.promote(1L, null, null, null, ADMIN, null)).getErrorCode());
        // 초안 편집이 실제로 일어난 뒤에 걸린 경우라야 롤백을 말할 수 있다.
        verify(drafts).addTechnology(anyString(), anyString(), anyString(), any(),
                anyString(), anyString(), anyString(), anyString());
    }

    @Test
    @DisplayName("없는 후보는 승격도 거절도 NOT_FOUND 다")
    void anUnknownCandidateIsNotFound() {
        when(candidates.findById(99L)).thenReturn(Optional.empty());

        assertEquals(ErrorCode.TECHNOLOGY_CANDIDATE_NOT_FOUND,
                assertThrows(CustomException.class,
                        () -> admin.promote(99L, null, null, null, ADMIN, null)).getErrorCode());
        assertEquals(ErrorCode.TECHNOLOGY_CANDIDATE_NOT_FOUND,
                assertThrows(CustomException.class,
                        () -> admin.reject(99L, ADMIN, null)).getErrorCode());
        verifyNoInteractions(drafts);
    }

    @Test
    @DisplayName("거절은 결정 사유를 남기고 초안은 그대로 둔다")
    void rejectionRecordsTheReasonAndLeavesTheRegistryAlone() {
        candidate("PYPI", "left-pad", "NEW");

        admin.reject(1L, ADMIN, "라이브러리가 아니라 예제 코드");

        ArgumentCaptor<String> status = ArgumentCaptor.forClass(String.class);
        ArgumentCaptor<String> note = ArgumentCaptor.forClass(String.class);
        verify(candidates).decide(eq(1L), status.capture(), eq(null), eq(ADMIN),
                note.capture(), any());
        assertEquals("REJECTED", status.getValue());
        assertEquals("라이브러리가 아니라 예제 코드", note.getValue());
        verifyNoInteractions(drafts);
    }

    @Test
    @DisplayName("두 번째 거절은 첫 결정을 덮어쓰지 않는다")
    void aSecondRejectionDoesNotOverwriteTheFirst() {
        candidate("PYPI", "left-pad", "REJECTED");
        when(candidates.decide(anyLong(), anyString(), any(), anyLong(), any(), any()))
                .thenReturn(false);

        assertEquals(ErrorCode.TECHNOLOGY_CANDIDATE_ALREADY_DECIDED,
                assertThrows(CustomException.class,
                        () -> admin.reject(1L, ADMIN, "다른 사유")).getErrorCode());
    }

    @Test
    @DisplayName("발행할 초안이 없으면 발행은 거절된다")
    void publishingWithoutADraftIsRefused() {
        when(drafts.draftVersion()).thenReturn(Optional.empty());

        assertEquals(ErrorCode.REGISTRY_DRAFT_EMPTY, assertThrows(CustomException.class,
                () -> admin.publishDraft()).getErrorCode());
        verify(drafts, never()).publish(anyString(), any());
    }

    @Test
    @DisplayName("목록 개수는 범위 안으로 맞춘다")
    void theListSizeIsClamped() {
        // 화면이 보낸 값이 그대로 LIMIT 이 되면 한 번의 요청이 테이블 전체를 끈다.
        admin.list(100000);
        admin.list(0);

        verify(candidates).topCandidates(200);
        verify(candidates).topCandidates(1);
    }
}
