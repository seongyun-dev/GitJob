/**
 * 스크롤 스토리 다섯 장의 고정값 · 확정 디자인 `GitJob Landing Storytelling v2`.
 *
 * 배경·글자색을 컴포넌트가 아니라 여기 모은 이유는 **헤더와 인디케이터가 장의 밝기를
 * 따라가야** 하기 때문이다. 밝은 장 위에서 흰 글씨를 쓰면 로고가 사라진다. 장마다
 * 색을 적어 두고 헤더가 현재 장의 `chrome` 을 읽는다.
 */

/** 장 위에 얹히는 헤더·인디케이터의 색 계열. */
export type ChromeTone = 'onDark' | 'onLight'

export interface Scene {
  id: string
  /** 인디케이터에 적는 이름. */
  label: string
  /** 화면 낭독기가 읽는 이름. */
  title: string
  background: string
  chrome: ChromeTone
}

export const SCENES: readonly Scene[] = [
  {
    id: 's1',
    label: 'PROBLEM',
    title: '01 Problem',
    chrome: 'onDark',
    background: [
      /*
        맨 위의 어두운 겹. 원본 그라데이션은 전부 밝은 웜 그레이(명도 70% 안팎)라
        그 위의 흰 제목이 배경에 녹았다 — 대비가 2:1 남짓으로 접근성 기준(4.5:1)에도
        못 미쳤다. 색조는 그대로 두고 명도만 눌러 흰 글씨가 뜨게 한다. 가운데를 더
        깊게 해서 시선이 제목에 모이고, 다음 장(다크 네이비)으로 넘어가는 낙차도 준다.
      */
      'radial-gradient(1000px 720px at 50% 50%, rgba(23,35,58,.42), rgba(23,35,58,.18) 62%, transparent 78%)',
      'linear-gradient(180deg, rgba(23,35,58,.22), rgba(23,35,58,.10) 45%, rgba(23,35,58,.26))',
      'linear-gradient(100deg, rgba(60,50,48,.14), transparent 58%)',
      'radial-gradient(900px 700px at 80% 18%, rgba(158,184,221,.55), transparent 64%)',
      'radial-gradient(760px 620px at 0% 100%, rgba(166,148,138,.95), transparent 66%)',
      'linear-gradient(112deg, #a9998f 0%, #b3a69c 26%, #bcb8b7 50%, #c0c0c5 64%, #b4c2d8 86%, #a9bcd9 100%)',
    ].join(','),
  },
  {
    id: 's2',
    label: 'EVIDENCE',
    title: '02 Evidence',
    chrome: 'onDark',
    background: [
      'radial-gradient(900px 600px at 82% 0%, rgba(91,141,255,.28), transparent 62%)',
      'radial-gradient(700px 500px at 8% 100%, rgba(91,141,255,.16), transparent 60%)',
      'linear-gradient(165deg, #162A4A 0%, #101A2E 100%)',
    ].join(','),
  },
  {
    id: 's3',
    label: 'JOB MATCH',
    title: '03 Job Match',
    chrome: 'onLight',
    background: [
      'radial-gradient(800px 560px at 92% 0%, rgba(175,200,255,.35), transparent 60%)',
      'linear-gradient(180deg, #F7F9FC 0%, #EDF2FA 100%)',
    ].join(','),
  },
  {
    id: 's4',
    label: 'WHAT-IF',
    title: '04 What-if',
    chrome: 'onLight',
    background: [
      'radial-gradient(900px 600px at 50% 40%, rgba(255,255,255,.55), transparent 65%)',
      'linear-gradient(180deg, #EDF3FC 0%, #DEE9F8 55%, #C9D9F1 100%)',
    ].join(','),
  },
  {
    id: 's5',
    label: 'START',
    title: '05 Start',
    chrome: 'onDark',
    background: [
      'radial-gradient(800px 560px at 50% 30%, rgba(91,141,255,.2), transparent 65%)',
      'linear-gradient(180deg, #172A4A 0%, #101A2E 100%)',
    ].join(','),
  },
]

/*
  랜딩이 가는 곳(`MAIN_PATH`)과 랜딩 자신의 경로(`INTRO_PATH`)는
  `features/landing/model/landingEntry` 로 옮겼다(티켓 S15P21E102-310). 둘은 `/` 진입
  판정의 두 결과라, 그 판정과 같은 파일에 있어야 어디로 갈 수 있는지가 한눈에 읽힌다.
*/
