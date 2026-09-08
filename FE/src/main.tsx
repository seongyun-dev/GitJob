import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('#root 엘리먼트를 찾지 못했습니다.')
}

// 앱 구성(라우터·Provider·레이아웃)은 후속 태스크에서 붙인다.
createRoot(container).render(
  <StrictMode>
    <p className="p-6 text-tone-neutral">GitJob</p>
  </StrictMode>,
)
