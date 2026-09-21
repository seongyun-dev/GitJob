package com.example.git_job.analysis.controller;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.example.git_job.analysis.service.AnalysisHistoryService;
import com.example.git_job.analysis.store.AnalysisHistoryStore;
import com.example.git_job.global.security.AuthenticatedUser;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * 마이페이지 분석 이력 응답 (B-FN-009, 화면 14).
 *
 * <p>여기서 붙잡는 것은 경로와 응답 모양이다. 화면 파서가 다섯 필드를 모두 요구하고
 * 상태는 일곱 값 중 하나여야 하므로, 하나라도 어긋나면 목록이 통째로 비어 보인다.</p>
 *
 * <p>경로를 테스트로 고정하는 이유가 따로 있다. `/api/v1/me/**`는 인증이 필요해
 * <b>경로가 없어도 401이 돌아온다</b> — curl로는 404와 401이 구분되지 않는다.</p>
 */
class AnalysisHistoryControllerTest {

    private static final Instant NOW = Instant.parse("2026-09-16T07:01:05Z");

    private AnalysisHistoryStore store;
    private AuthenticatedUser principal;
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        store = mock(AnalysisHistoryStore.class);
        principal = new AuthenticatedUser("42", "tester", "jti", NOW.plusSeconds(3600));
        mvc = MockMvcBuilders
                .standaloneSetup(new AnalysisHistoryController(new AnalysisHistoryService(store),
                        mock(com.example.git_job.analysis.service.AnalysisLatestBatchService.class)))
                .setCustomArgumentResolvers(new HandlerMethodArgumentResolver() {
                    @Override
                    public boolean supportsParameter(org.springframework.core.MethodParameter p) {
                        return p.getParameterType() == AuthenticatedUser.class;
                    }

                    @Override
                    public Object resolveArgument(org.springframework.core.MethodParameter p,
                            ModelAndViewContainer c,
                            org.springframework.web.context.request.NativeWebRequest r,
                            org.springframework.web.bind.support.WebDataBinderFactory f) {
                        return principal;
                    }
                }).build();
    }

    @Test
    @DisplayName("이력은 화면 계약 그대로 다섯 필드를 준다")
    void theHistoryCarriesEveryFieldTheScreenParses() throws Exception {
        when(store.page(42L, 0, 20)).thenReturn(List.of(new AnalysisHistoryStore.Row(
                "an_1", NOW, "codetree", "COMPLETED",
                List.of("Vue.js", "Vite"), "L1", 4)));
        when(store.count(42L)).thenReturn(1);

        mvc.perform(get("/api/v1/me/analyses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].analysisId").value("an_1"))
                .andExpect(jsonPath("$.data.items[0].analyzedAt").value("2026-09-16T07:01:05Z"))
                // 본인 소유자는 스토어가 뗀다. 남의 저장소라면 소유자까지 온다.
                .andExpect(jsonPath("$.data.items[0].repositories[0]").value("codetree"))
                .andExpect(jsonPath("$.data.items[0].resultText").value("기술 2 · 최고 L1"))
                // 저장된 COMPLETED 는 화면 어휘가 아니다. 진행 조회와 같은 함수로 접는다.
                .andExpect(jsonPath("$.data.items[0].status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.data.page").value(0))
                .andExpect(jsonPath("$.data.size").value(20))
                .andExpect(jsonPath("$.data.totalCount").value(1));
    }

    @Test
    @DisplayName("찾은 기술이 없으면 개수를 세지 않고 없다고 적는다")
    void anAnalysisThatFoundNothingSaysSo() throws Exception {
        // "기술 0"은 숫자를 세긴 했다는 인상을 준다. 아무것도 못 찾은 것과 다르다.
        when(store.page(anyLong(), anyInt(), anyInt())).thenReturn(List.of(
                new AnalysisHistoryStore.Row("an_2", NOW, "yoonseo-aa/algo", "SUCCEEDED", List.of(), null, 0)));

        mvc.perform(get("/api/v1/me/analyses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].resultText").value("확인된 기술 없음"));
    }

    @Test
    @DisplayName("저장소 이름이 없는 옛 기록은 빈 목록이다")
    void anOlderRecordWithoutARepositoryNameGetsAnEmptyList() throws Exception {
        // 식별자를 이름 자리에 넣으면 화면에 숫자가 저장소 이름처럼 찍힌다.
        when(store.page(anyLong(), anyInt(), anyInt())).thenReturn(List.of(
                new AnalysisHistoryStore.Row("an_3", NOW, null, "SUCCEEDED", List.of(), null, 0)));

        mvc.perform(get("/api/v1/me/analyses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].repositories").isEmpty());
    }

    @Test
    @DisplayName("끝나지 않은 분석은 결과를 적지 않는다")
    void anUnfinishedAnalysisHasNoResultText() throws Exception {
        when(store.page(anyLong(), anyInt(), anyInt())).thenReturn(List.of(
                new AnalysisHistoryStore.Row("an_4", NOW, "yoonseo-aa/algo", "COLLECTING", List.of(), null, 0)));

        mvc.perform(get("/api/v1/me/analyses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].status").value("RUNNING"))
                .andExpect(jsonPath("$.data.items[0].resultText").value("결과 없음"));
    }

    @Test
    @DisplayName("결과는 기술 개수와 닿은 최고 레벨이다")
    void theResultCountsTechnologiesAndNamesTheTopLevel() throws Exception {
        // 이름을 늘어놓으면 기술이 열 개 넘는 저장소에서 표 한 칸이 여러 줄이 된다.
        when(store.page(anyLong(), anyInt(), anyInt())).thenReturn(List.of(
                new AnalysisHistoryStore.Row("an_5", NOW, "yoonseo-aa/app", "SUCCEEDED",
                        List.of("Vue.js", "Vite", "Spring Boot", "Docker", "Redis"), "L2", 30)));

        mvc.perform(get("/api/v1/me/analyses"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.items[0].resultText").value("기술 5 · 최고 L2"));
    }

    @Test
    @DisplayName("쪽 크기는 범위 안으로 맞추고 offset 으로 옮긴다")
    void theRequestedPageIsClampedAndTranslatedToAnOffset() throws Exception {
        // 화면이 보낸 값이 그대로 LIMIT 이 되면 한 번의 요청이 표 전체를 끈다.
        mvc.perform(get("/api/v1/me/analyses?page=2&size=500")).andExpect(status().isOk());

        verify(store).page(42L, 100, 50);
    }
}
