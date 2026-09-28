import { useState } from 'react'
import { SiteFooter } from '@/app/layouts/SiteFooter'
import { BACKDROP } from '@/features/landing/backdrop'
import { RoleFitScene } from '@/features/landing/components/RoleFitScene'
import { ServiceIntro } from '@/features/landing/components/ServiceIntro'
import type { RoleKey } from '@/features/landing/roleFitData'
import '@/features/landing/landing.css'

/**
 * 메인 화면 · 티켓 S15P21E102-191, 직무적합 축 + Landing Redesign으로 개편.
 *
 * <h2>랜딩과 다른 화면이다</h2>
 *
 * `/` 는 스크롤 스토리(`LandingStory`, 티켓 298)가 갖고, 이 화면은 그 다음이다 —
 * 스토리가 "이 서비스가 무엇인가"를 말하고, 여기서 직무를 골라 그 직무가 요구하는
 * 기술을 실제로 본다. 스토리의 `바로 시작하기` 가 도착하는 곳이다.
 *
 * `AppLayout`을 쓰지 않는 유일한 화면이다. 배경 그라데이션이 화면 전체를 덮어야 하는데
 * AppLayout은 흰 배경에 `max-w-5xl` 본문을 강제한다. 로그인 후 화면들과 골격이 다르므로
 * 라우터에서 레이아웃 밖에 둔다.
 *
 * ## 다섯 장
 *
 *   1. 직무를 고르면 그 직무가 요구하는 기술이 뜨고, 내 칸은 비어 있다 (`RoleFitScene`)
 *   2. 01 · 무엇을 읽는가 — 저장소에서 근거를 찾는다
 *   3. 02 · 무엇과 만나는가 — 채용시장과 대조한다
 *   4. 03 · 다음에 무엇을 하는가 — 채우면 무엇이 열리는가
 *   5. 시작 지점과 하단바
 *
 * 2~5장은 확정 디자인 `GitJob Landing Redesign`의 장면을 옮긴 것이고 `ServiceIntro`가
 * 갖는다. 그 디자인의 첫 장면(Hero)은 쓰지 않는다 — 1장이 같은 자리를 직무 선택으로
 * 대신하고, 둘을 겹쳐 두면 같은 말을 두 번 하게 된다.
 *
 * ## 로그인 전 화면에서 숫자를 어떻게 다루나
 *
 * 이전 랜딩은 미리보기 패널에 `확인된 기술 14` · `전체 공고 매칭 87건` 같은 연출용
 * 고정값을 두었다. 로그인 전에는 조회할 사용자도 Snapshot도 없으므로 그 숫자들은
 * 아무것도 조회하지 않고 주장하는 값이었다.
 *
 * 이번 개편은 그 축을 뒤집었다. **시장 쪽 절반은 로그인과 무관하게 진짜다** —
 * 직무 분류는 C조 코호트 코드에서, 기술과 그 수는 Registry에서 온다. 사용자 쪽
 * 절반만 없으므로 그 칸을 지어내지 않고 비워 두고, 빈칸 자체가 CTA의 이유가 된다.
 * 2~5장의 막대와 카드도 값이 아니라 모양만 말한다(`serviceIntroData` 주석).
 */
export function MainPage() {
  /*
    고른 직무를 페이지가 들고 있는 이유는 첫 장이 바꾸고 다른 장이 읽을 수 있어야
    하기 때문이다. 지금은 첫 장만 쓰지만, 2~4장의 예시를 직무별로 나누게 되면 여기서
    바로 내려보낼 수 있다.

    라우터 쿼리(`?role=`)로 올리지 않았다. 로그인 전 둘러보기 상태라 공유하거나
    되돌아올 대상이 아니고, URL에 올리면 `/roles` 화면의 확정 직무 분류와 이름이
    겹쳐 보인다 — 그 분류는 아직 제품 결정이다(`roleFitData` 주석).
  */
  const [role, setRole] = useState<RoleKey>('BACKEND')

  return (
    /*
      배경을 이 컨테이너 한 곳에 둔다. 스크롤 컨테이너의 배경은 내용과 함께 움직이지
      않으므로(`background-attachment` 기본값) 모든 장이 같은 그라데이션 위를 지나가고
      이음매가 생기지 않는다. 섹션마다 배경을 주면 장이 바뀔 때 경계가 보인다.

      스냅 규칙은 `landing.css`의 `.lp-scroll`·`.lp-snap`에 있다.
    */
    <div className="lp-scroll relative w-full" style={{ background: BACKDROP }}>
      <RoleFitScene role={role} onRoleChange={setRole} />

      {/*
        하단바는 마지막 장 안으로 넘긴다. 여기서 `<ServiceIntro />` 뒤에 두면
        데스크톱 스크롤 스냅이 꼬리 요소를 붙잡아 두지 못한다 — 이유는
        `ServiceIntro`의 마지막 장 주석에 있다.

        `onDark`인 것은 이 페이지 배경이 짙은 그라데이션이기 때문이다. 기본 `light`를
        쓰면 진한 글씨가 배경에 묻힌다.
      */}
      <ServiceIntro footer={<SiteFooter tone="onDark" />} />
    </div>
  )
}
