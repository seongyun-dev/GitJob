package com.example.git_job.compute.client;

/**
 * C 호출이 200이 아니었을 때의 이유 (S15P21E102-279).
 *
 * <p>C의 오류를 한 덩어리로 뭉개면 화면이 "계산 중"과 "서버가 죽었다"를 같은 말로
 * 표시하게 된다. 그 둘은 사용자가 할 일이 다르다 — 앞은 기다리면 되고 뒤는 다시 눌러야
 * 한다. 그래서 HTTP 상태 하나가 아니라 C가 보낸 {@code code}까지 보고 여기로 좁힌다.</p>
 *
 * <p>공개 API 응답으로의 변환표는 {@code docs/be/c-compute-public-api.md} §2-E에 있다.
 * 변환은 이 패키지가 아니라 서비스 층이 한다 — 같은 상태라도 화면마다 표시가 다르기
 * 때문이다(Trend의 미준비는 카드 하나의 "데이터 없음"이고, 매칭의 미준비는 화면 전체의
 * "준비 중"이다).</p>
 */
public enum CComputeStatus {

    /**
     * 202. 같은 event/selector의 계산이 아직 살아 있다. 같은 요청으로 재시도한다.
     *
     * <p>HTTP로는 성공이지만 결과가 없으므로 예외로 올린다. 호출부가 200 본문과
     * 202 본문을 구분해 파싱하게 두면 그 분기가 기능마다 복제된다.</p>
     */
    PREPARING,

    /** 404 {@code COHORT_NOT_PREPARED}/{@code TREND_NOT_PREPARED}. 입력 묶음이 아직 없다. */
    NOT_PREPARED,

    /** 409 {@code JOB_MATCHING_NOT_PREPARED}. Snapshot은 있으나 매칭 결과가 없는 구 결과다. */
    MATCHING_NOT_PREPARED,

    /** 404 {@code SNAPSHOT_NOT_FOUND}/{@code JOB_NOT_FOUND}. 타인 것과 없는 것을 구분하지 않는다. */
    NOT_FOUND,

    /** 409 {@code IDEMPOTENCY_CONFLICT}/{@code LEASE_LOST}. 같은 event의 내용·버전이 달라졌다. */
    CONFLICT,

    /** 422. 지원하지 않는 직무·필터·기술이다. 재시도해도 같다. */
    INVALID_INPUT,

    /** 413. 요청 본문이나 결과가 예산을 넘었다. 절단하지 않고 실패한 것이다. */
    TOO_LARGE,

    /**
     * 403 {@code EVIDENCE_SCOPE_MISMATCH}. Evidence의 소유자·분석이 event와 다르다.
     *
     * <p>사용자가 만들 수 있는 상태가 아니라 B가 요청을 잘못 만든 것이다. 재시도로
     * 낫지 않으므로 화면에 재시도를 권하지 않고 서버 오류로 올린다.</p>
     */
    SCOPE_MISMATCH,

    /** 500 {@code STORED_MATCHING_INTEGRITY_FAILED}. 저장된 결과가 깨졌다. 재시도로 낫지 않는다. */
    INTEGRITY_FAILED,

    /** 500 {@code COMPUTE_FAILED}. C가 같은 event로 재시도하라고 답한 경우다. */
    COMPUTE_FAILED,

    /**
     * 503, 401, 연결 실패, 타임아웃, 그리고 C 미설정.
     *
     * <p>넷을 한 값으로 묶는 이유는 화면이 할 일이 같기 때문이다(잠시 후 재시도).
     * 운영자가 구분해야 하므로 원인은 예외 메시지와 로그에 남긴다.</p>
     */
    UNAVAILABLE
}
