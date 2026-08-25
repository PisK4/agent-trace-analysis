import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

function App() {
  return <main className="boot-empty">ATA</main>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
