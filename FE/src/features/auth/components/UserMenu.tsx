import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useQueryClient } from '@tanstack/react-query'
import { logout } from '@/features/auth/api/me'
import type { Me } from '@/features/auth/api/me'
import { userMenuLinks } from '@/features/auth/model/userMenu'
import { synchronizeSessionCache } from '@/features/auth/sessionSync'

/**
 * 로그인 사용자 프로필 메뉴 · 티켓 S15P21E102-246.
 *
 * 헤더 우측에 **작은 원형 아바타 + 이름 + chevron** 을 놓고, 클릭하면 드롭다운을 연다.
 * 아바타는 사용자 영역을 구분하는 보조 요소라 작게(28px)·은은하게 둔다 — 사진 자체를
 * 강조하지 않는다. 마이페이지·로그아웃은 상단 메뉴가 아니라 이 드롭다운에 모은다.
 *
 * `tone`은 트리거(닫힌 상태)의 글자색만 바꾼다 — 랜딩은 유리 배경 위 흰 글씨(`light`),
 * 내부는 흰 배경 위 진한 글씨(`dark`). 아바타 크기·간격은 두 화면이 동일하고, 드롭다운
 * 패널 자체도 두 화면 모두 흰 카드로 같다.
 *
 * 이름은 `me.displayName`을 그대로 쓴다 — "님"을 붙이지 않는다. BE가 프로필 이름이
 * 없으면 GitHub 핸들로 대체하므로 빈 값은 아니지만, 혹시 비면 "사용자"로 접는다.
 * "GitHub 연결됨"은 `me.githubConnected`가 참일 때만 — 실제 데이터가 없으면 그리지 않는다.
 */

// 아바타 지름(px). 헤더 높이(71px)를 키우지 않는 작은 보조 요소. 크기·얇은 테두리는
// 인라인 style 로 준다 — Tailwind v4 가 임의값 유틸을 빌드에서 누락시키는 이슈를 피한다.
const AVATAR_SIZE = 28
const AVATAR_BORDER = '1px solid rgba(0, 0, 0, 0.06)'

function initial(name: string): string | null {
  const trimmed = name.trim()
  return trimmed.length > 0 ? trimmed.charAt(0).toUpperCase() : null
}

/** 이름조차 없을 때의 기본 사용자 아이콘. 아바타 원 안에서만 쓰인다. */
function UserGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <circle cx="12" cy="8" r="3.4" />
      <path d="M4.8 19.2c0-3.5 3.1-5.8 7.2-5.8s7.2 2.3 7.2 5.8Z" />
    </svg>
  )
}

/**
 * fallback 아바타: 이름 첫 글자(있으면), 이름도 없으면 기본 아이콘.
 * primary blue 아주 연한 배경 + primary 글씨. 이미지와 같은 지름이라 자리를 공유한다.
 */
function AvatarFallback({ name }: { name: string }) {
  const letter = initial(name)
  return (
    <span
      aria-hidden
      className="flex shrink-0 items-center justify-center rounded-full bg-tone-accent-bg text-[12px] font-semibold text-brand-600"
      style={{ width: AVATAR_SIZE, height: AVATAR_SIZE, border: AVATAR_BORDER }}
    >
      {letter ?? <UserGlyph />}
    </span>
  )
}

/**
 * 아바타. spec 의 fallback 우선순위 세 갈래를 모두 처리한다.
 *   1. avatarUrl 있고 로딩 성공 → GitHub 프로필 이미지
 *   2. avatarUrl 없음(null·빈 문자열) → 이름 첫 글자 fallback
 *   3. avatarUrl 있으나 로딩 실패(404·깨진 링크) → onError 로 fallback 전환
 * 어느 경우든 같은 지름의 원이라 헤더 높이·정렬·레이아웃이 흔들리지 않고, broken image
 * 아이콘이 노출되지 않는다. 외부 임의 이미지는 쓰지 않는다.
 */
function Avatar({ me }: { me: Me }) {
  const [failed, setFailed] = useState(false)
  const hasUrl = me.avatarUrl !== null && me.avatarUrl !== ''

  if (!hasUrl || failed) {
    return <AvatarFallback name={me.displayName} />
  }
  return (
    <img
      src={me.avatarUrl ?? undefined}
      alt=""
      className="shrink-0 rounded-full object-cover"
      style={{ width: AVATAR_SIZE, height: AVATAR_SIZE, border: AVATAR_BORDER }}
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  )
}

export function UserMenu({ me, tone = 'dark' }: { me: Me; tone?: 'light' | 'dark' }) {
  const [open, setOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const displayName = me.displayName.trim() === '' ? '사용자' : me.displayName

  // 바깥 클릭·Escape 로 닫는다. pointerdown 을 쓰는 것은 click 보다 먼저 발생해
  // 링크 클릭과 경합하지 않기 때문이다.
  useEffect(() => {
    if (!open) {
      return
    }
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current !== null && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  async function onLogout() {
    setLoggingOut(true)
    try {
      await logout()
    } catch {
      // 서버 오류가 나도 클라이언트는 로그아웃 상태로 둔다 — 쿠키가 남아도 다음 요청이
      // 401 이면 어차피 로그아웃으로 읽힌다. 사용자를 로그인 상태에 붙잡아 두지 않는다.
    }
    // 저장소·분석·Evidence 캐시는 사용자 범위다. 다음 로그인 계정이 이전
    // 사용자의 비공개 저장소 이름이나 판정을 잠깐이라도 보지 않게 전부 비운다.
    await synchronizeSessionCache(queryClient, window.localStorage, null)
    setOpen(false)
    navigate('/')
  }

  const triggerText = tone === 'light' ? 'text-white' : 'text-brand-ink-soft'

  return (
    <div ref={rootRef} className="relative">
      {/*
        아바타 + 이름 + chevron 전체가 하나의 클릭 영역이다(아바타만 따로 클릭되지 않는다).
        간격은 spec대로 avatar↔이름 8px(이름 ml-2), 이름↔chevron 6px(chevron ml-1.5).
        아바타가 왼쪽 원이라 pl 은 작게(4px), 오른쪽은 chevron 여유로 pr-2.5.
      */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        className={`flex items-center rounded-full py-1 pr-2.5 pl-1 text-[14px] font-medium transition-colors ${triggerText} ${
          tone === 'light' ? 'hover:bg-white/10' : 'hover:bg-brand-line/40'
        }`}
      >
        <Avatar me={me} />
        <span className="ml-2 max-w-[140px] truncate">{displayName}</span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 20 20"
          fill="none"
          aria-hidden
          className={`ml-1.5 transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path d="M5 7.5 10 12.5 15 7.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          id={menuId}
          role="menu"
          className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-[14px] border border-brand-line bg-white text-brand-ink shadow-[0_12px_28px_rgba(25,47,81,0.14)]"
        >
          {/* 사용자 요약. 이름은 강조, GitHub 연결은 작은 회색 보조 텍스트. */}
          <div className="px-4 py-3">
            <p className="truncate text-[14px] font-[750] text-brand-ink">{displayName}</p>
            {me.githubConnected && (
              <p className="mt-0.5 text-[12px] text-brand-faint">GitHub 연결됨</p>
            )}
          </div>

          <div className="border-t border-brand-line" />

          {/*
            이동 항목은 `model/userMenu`가 정한다 · 티켓 317. 관리자에게만 `모니터링`이
            하나 더 붙는데, 누구에게 무엇이 보이는지는 화면을 띄우지 않고 확인할 수
            있어야 하는 규칙이라 컴포넌트 밖에 뒀다.

            관리자 진입로가 여기 생긴 이유는 그 전까지 로그인 직후 자동 이동이 유일한
            길이어서다(`AuthCallbackPage`). 서비스 화면으로 한 번 나오면 주소를 직접
            쳐야 콘솔로 돌아갈 수 있었다.
          */}
          {userMenuLinks(me).map((link) => (
            <Link
              key={link.id}
              to={link.to}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block px-4 py-2.5 text-[13.5px] text-brand-ink-soft transition-colors hover:bg-[#F6F8FC]"
            >
              {link.label}
            </Link>
          ))}

          <div className="border-t border-brand-line" />

          {/* 로그아웃은 강조하지 않는다. destructive red 대신 muted 회색. */}
          <button
            type="button"
            role="menuitem"
            onClick={onLogout}
            disabled={loggingOut}
            className="block w-full px-4 py-2.5 text-left text-[13.5px] text-brand-muted transition-colors hover:bg-[#F6F8FC] disabled:opacity-60"
          >
            {loggingOut ? '로그아웃 중…' : '로그아웃'}
          </button>
        </div>
      )}
    </div>
  )
}
