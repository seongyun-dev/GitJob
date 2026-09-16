package com.example.git_job.analysis.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.example.git_job.analysis.service.TechnologyCandidateAdminService.CandidateFilter;
import com.example.git_job.analysis.store.RegistryDraftStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore;
import com.example.git_job.analysis.store.TechnologyCandidateStore.Detail;
import com.example.git_job.analysis.store.TechnologyCandidateStore.Observation;
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
    @DisplayName("이미 등록된 기술로 승격하면 매핑만 더한다")
    void promotingOntoAnExistingTechnologyOnlyAddsTheMapping() {
        // 좌표 여럿이 기술 하나인 것이 보통이다 — @vue/tsconfig 도 vue-tsc 도 Vue.js 다.
        // 초안은 CURRENT 의 복사본이라 이미 있는 기술을 다시 INSERT 하면 기본키
        // (tech_id, registry_version) 에 걸려 500 이 났다.
        candidate("NPM", "@vue/tsconfig", "NEW");
        when(drafts.hasTechnology(DRAFT, "vuejs")).thenReturn(true);

        assertEquals("vuejs", admin.promote(1L, "vuejs", "덮어쓰면 안 되는 이름",
                List.of("BACKEND"), ADMIN, null));

        verify(drafts).addMapping(DRAFT, "vuejs", "PACKAGE", "NPM", "@vue/tsconfig", "EXACT");
        // 표시명과 직무는 기술을 등록할 때 정해진 값이다. 나중에 붙는 좌표가
        // 다시 쓰면 자리잡은 기술의 이름이 빌드 플러그인 이름으로 바뀐다.
        verify(drafts, never()).addTechnology(anyString(), anyString(), anyString(),
                any(), anyString(), anyString(), anyString(), anyString());
    }

    @Test
    @DisplayName("이미 매핑된 좌표는 다시 승격되지 않는다")
    void aCoordinateThatIsAlreadyMappedIsRefused() {
        // 같은 좌표가 기술 둘로 해석되면 어느 쪽이 답인지를 해석 순서가 정한다.
        candidate("MAVEN", "org.springframework.kafka:spring-kafka", "NEW");
        when(drafts.hasMapping(DRAFT, "MAVEN", "org.springframework.kafka:spring-kafka"))
                .thenReturn(true);

        CustomException thrown = assertThrows(CustomException.class,
                () -> admin.promote(1L, "apache-kafka", null, null, ADMIN, null));

        assertEquals(ErrorCode.TECHNOLOGY_COORDINATE_ALREADY_MAPPED, thrown.getErrorCode());
        verify(drafts, never()).addMapping(anyString(), anyString(), anyString(),
                anyString(), anyString(), anyString());
        verify(drafts, never()).addTechnology(anyString(), anyString(), anyString(),
                any(), anyString(), anyString(), anyString(), anyString());
        verify(candidates, never()).decide(anyLong(), anyString(), any(), anyLong(), any(), any());
    }

    @Test
    @DisplayName("승격 화면이 고를 수 있는 기술은 초안 기준이다")
    void technologyOptionsComeFromTheRegistry() {
        // 방금 등록한 기술에도 바로 좌표를 더 붙일 수 있어야 하므로 CURRENT 가
        // 아니라 초안을 본다. 어느 버전을 읽을지는 스토어가 정한다.
        when(drafts.options()).thenReturn(List.of(
                new RegistryDraftStore.TechnologyOption("vuejs", "Vue.js")));

        assertEquals(List.of(new RegistryDraftStore.TechnologyOption("vuejs", "Vue.js")),
                admin.technologyOptions());
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
        admin.list(100000, CandidateFilter.UNDECIDED);
        admin.list(0, CandidateFilter.UNDECIDED);

        verify(candidates).topCandidates(200, List.of("NEW", "REVIEWING"));
        verify(candidates).topCandidates(1, List.of("NEW", "REVIEWING"));
    }

    @Test
    @DisplayName("결정이 끝난 후보는 따로 골라야 나온다")
    void decidedCandidatesAreAskedForSeparately() {
        // 기본 화면은 처리할 일이 쌓이는 큐다. 승격된 것이 거기 남으면 사용자 수로
        // 정렬되는 탓에 가장 많이 쓰이는 기술이 맨 위에 영구히 박힌다.
        admin.list(50, CandidateFilter.PROMOTED);
        admin.list(50, CandidateFilter.REJECTED);
        admin.list(50, CandidateFilter.ALL);

        verify(candidates).topCandidates(50, List.of("PROMOTED"));
        verify(candidates).topCandidates(50, List.of("REJECTED"));
        verify(candidates).topCandidates(50, List.of("NEW", "REVIEWING", "PROMOTED", "REJECTED"));
    }

    @Test
    @DisplayName("상세 조회는 후보와 최근 관찰을 함께 준다")
    void detailReturnsCandidateWithRecentObservations() {
        when(candidates.findDetail(1L)).thenReturn(Optional.of(new Detail(
                1L, "MAVEN", "io.jsonwebtoken:jjwt-api", "MAIN", "NEW",
                9, 12, 30, SEEN, SEEN, null, null, null)));
        when(candidates.observations(1L, 100)).thenReturn(List.of(
                new Observation("repo-1", "MAIN", 5, SEEN)));

        var detail = admin.detail(1L);

        assertEquals(1L, detail.candidate().candidateId());
        assertEquals(1, detail.observations().size());
        assertEquals("repo-1", detail.observations().get(0).repositoryId());
    }

    @Test
    @DisplayName("없는 후보의 상세는 NOT_FOUND 이고 관찰은 읽지 않는다")
    void detailOfUnknownCandidateIsNotFound() {
        when(candidates.findDetail(99L)).thenReturn(Optional.empty());

        assertEquals(ErrorCode.TECHNOLOGY_CANDIDATE_NOT_FOUND,
                assertThrows(CustomException.class,
                        () -> admin.detail(99L)).getErrorCode());
        verify(candidates, never()).observations(anyLong(), anyInt());
    }
}
