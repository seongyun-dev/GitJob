package com.example.git_job.auth.controller.dto;

/**
 * 현재 로그인 사용자 요약 · 티켓 S15P21E102-246.
 *
 * <p>헤더의 프로필 영역이 쓰는 최소 정보다. FE는 이 응답의 유무(200/401)로 로그인
 * 여부를 판정하고, 값으로 이름·아바타·GitHub 연결 상태를 그린다.</p>
 *
 * <p>{@code displayName}은 프로필 이름({@code user.name})이 있으면 그것을, 없으면 GitHub
 * 핸들({@code github_login})을 쓴다 — {@code user.name}은 핸들을 담지 않기로 한 계약이라
 * (S15P21E102-153) 비어 있을 수 있고, 그때 화면에 빈 이름이 뜨지 않도록 여기서 접는다.
 * 둘 다 비는 경우는 없다(핸들은 NOT NULL). {@code avatarUrl}은 없을 수 있어 FE가 첫 글자
 * fallback을 그린다.</p>
 */
public record MeResponse(String displayName, String avatarUrl, boolean githubConnected) {}
