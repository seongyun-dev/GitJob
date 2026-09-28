package com.example.git_job.compute.service;

/**
 * 공개 API와 C의 페이징 규약을 잇는다 (S15P21E102-279).
 *
 * <p>공개 API는 {@code page}가 1-base이고 C는 0-base다. 화면과 C 사이 어딘가에서 한 번은
 * 바꿔야 하는데, 그것을 FE에 맡기면 FE가 C의 규약을 알아야 하고 목록마다 다른 파서가
 * 생긴다. 그래서 BE가 바꾼다.</p>
 *
 * <p>{@code size} 상한 50은 C의 제약이다. 넘겨 보내면 422가 나는데, 그 422는 사용자의
 * 잘못이 아니라 우리가 검증을 빠뜨린 것이므로 여기서 자른다.</p>
 */
public final class ComputePaging {

    public static final int DEFAULT_PER_PAGE = 20;
    /** C의 {@code size} 상한. 이 값을 넘기면 C가 422로 거절한다. */
    public static final int MAX_PER_PAGE = 50;

    private ComputePaging() {
    }

    /** 1-base 페이지 번호. 0이나 음수는 첫 쪽으로 본다. */
    public static int page(Integer page) {
        return page == null || page < 1 ? 1 : page;
    }

    public static int perPage(Integer perPage) {
        if (perPage == null || perPage < 1) {
            return DEFAULT_PER_PAGE;
        }
        return Math.min(perPage, MAX_PER_PAGE);
    }

    /** C가 받는 0-base 오프셋 페이지. */
    public static int toComputePage(int page) {
        return page - 1;
    }
}
