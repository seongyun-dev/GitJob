import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { AppProviders } from '@/app/providers'
import { AppRouter } from '@/app/router'
import './index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('#root 엘리먼트를 찾지 못했습니다.')
}

createRoot(container).render(
  <StrictMode>
    <AppProviders>
      <AppRouter />
    </AppProviders>
  </StrictMode>,
)
