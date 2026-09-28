import { useEffect, useRef, useState } from 'react'

/**
 * 장이 열릴 때 0에서 올라가는 숫자 · 티켓 S15P21E102-298.
 *
 * <h2>왜 숫자를 움직이나</h2>
 *
 * 다섯 장이 한 장씩 통째로 나타나기만 하면 화면이 슬라이드처럼 읽힌다. 이 랜딩에서
 * 각 장의 결론은 숫자 하나다 — `87`, `12`, `+15`. 그 숫자가 올라가는 동안 눈이 거기
 * 머무르고, 장의 요점이 어디인지가 움직임으로 드러난다.
 *
 * <h2>왜 한 번만 도나</h2>
 *
 * `run` 이 켜질 때 한 번 돌고 끝난다. 되돌아 올라갔다 다시 내려올 때마다 숫자가 0부터
 * 다시 세면 읽던 사람이 방금 읽은 값을 잃는다.
 *
 * 움직임을 줄이도록 설정한 사용자에게는 최종값을 바로 보여준다. 숫자가 튀는 것은
 * 장식이 아니라 어지럼의 원인이 될 수 있다.
 */
export function CountUp({
  value,
  run,
  durationMs = 900,
  prefix = '',
  suffix = '',
  className,
}: {
  value: number
  /** 이 장이 화면에 들어왔는가. */
  run: boolean
  durationMs?: number
  prefix?: string
  suffix?: string
  className?: string
}) {
  const [shown, setShown] = useState(0)
  const done = useRef(false)

  useEffect(() => {
    if (!run || done.current) {
      return
    }
    done.current = true

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(value)
      return
    }

    let frame = 0
    const started = performance.now()
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / durationMs)
      // 끝에서 천천히 멈춘다. 선형으로 세면 마지막 숫자가 갑자기 끊긴 것처럼 보인다.
      const eased = 1 - Math.pow(1 - progress, 3)
      setShown(Math.round(value * eased))
      if (progress < 1) {
        frame = requestAnimationFrame(tick)
      }
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [run, value, durationMs])

  return (
    <span className={className}>
      {prefix}
      {shown}
      {suffix}
    </span>
  )
}
