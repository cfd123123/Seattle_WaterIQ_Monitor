import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.tsx'
import { LocaleProvider } from './locale/LocaleContext'
import './index.css'
import './theme-dark.css'
import 'leaflet/dist/leaflet.css'

{
  const saved = localStorage.getItem('water-theme')
  document.documentElement.dataset.theme = saved === 'light' ? 'light' : 'dark'
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <LocaleProvider>
        <App />
      </LocaleProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
