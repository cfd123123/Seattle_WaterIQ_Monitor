import axios, { isAxiosError } from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useLocale } from './locale/LocaleContext'
import { t as translate } from './locale/messages'

type ApiResponse<T> = {
  code: string
  message: string
  data: T
}

type CopilotSource = {
  type?: string
  ref?: string
  heading?: string | null
}

type CopilotChatResult = {
  answer?: string
  sources?: CopilotSource[]
  model?: string | null
  provider?: string
  usage?: Record<string, number> | null
  toolTrace?: string[]
  tool_trace?: string[]
  mode?: string
  sessionId?: string
  session_id?: string
}

type CopilotChatMessage = {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  meta?: {
    toolTrace?: string[]
    model?: string | null
    provider?: string
  }
}

const COPILOT_SESSION_KEY = 'copilot_session_id'
const COPILOT_MINIMIZED_KEY = 'copilot-widget-minimized'

const http = axios.create({ baseURL: '/api' })

function getOrCreateCopilotSessionId(): string {
  try {
    const existing = localStorage.getItem(COPILOT_SESSION_KEY)
    if (existing) return existing
    const id = crypto.randomUUID()
    localStorage.setItem(COPILOT_SESSION_KEY, id)
    return id
  } catch {
    return crypto.randomUUID()
  }
}

/** Puget sites with turbidity (63680) wired in this product (IV/features may vary). */
const COPILOT_TURBIDITY_SITES = [
  { siteNo: '12117500', name: 'Cedar River near Landsburg, WA' },
  { siteNo: '12147600', name: 'South Fork Tolt River near Index, WA' },
] as const

const COPILOT_WHICH_TURBIDITY_SITES_RE =
  /\b(which|what)\s+sites?\s+(have|with|monitor|track)\s+turbidity|sites?\s+with\s+turbidity|哪些.*(站|站点).*(浊度|63680)|浊度.*(哪些|哪几个).*(站|站点)|list.*turbidity.*sites?/i

const COPILOT_LIVE_DATA_KEYWORDS: RegExp[] = [
  /\bturbidity\b/i,
  /\b63680\b/,
  /\b浊度\b/,
  /\bntu\b/i,
  /\brecommend_?alert\b/i,
  /\b12\s*h\s*risk\b/i,
  /\brisk\s*forecast\b/i,
  /\btier\b/i,
  /\bsnapshot\b/i,
]

const COPILOT_FORECAST_RE = /\b(forecast|predict)\b/i
const COPILOT_FLOW_RE = /\b(flow|discharge|00060)\b/i

function extractSiteNoFromCopilotMessage(message: string): string | null {
  const match = message.match(/\b(\d{8})\b/)
  return match ? match[1] : null
}

function isWhichTurbiditySitesQuestion(message: string): boolean {
  return COPILOT_WHICH_TURBIDITY_SITES_RE.test(message)
}

function copilotQuestionNeedsSite(message: string): boolean {
  if (isWhichTurbiditySitesQuestion(message)) return false
  if (extractSiteNoFromCopilotMessage(message)) return false
  const lowered = message.toLowerCase()
  const docOnly =
    /\b(what is|explain|meaning|definition|policy|runbook|是什么|什么意思|解释)\b/.test(lowered) &&
    !/\b(right now|current|now|today|forecast|risk|tier|snapshot|recommend|当前|预测|风险)\b/.test(
      lowered
    )
  if (docOnly) return false
  if (COPILOT_LIVE_DATA_KEYWORDS.some((re) => re.test(message))) return true
  return COPILOT_FORECAST_RE.test(message) && COPILOT_FLOW_RE.test(message)
}

function buildTurbiditySitesCopilotAnswer(): string {
  const lines = COPILOT_TURBIDITY_SITES.map((s) => `${s.siteNo} (${s.name})`)
  return (
    'Turbidity (63680) monitoring is wired for these Puget Sound sites: ' +
    `${lines.join('; ')}. ` +
    'Other registered sites may lack 63680 in IV. Enter an 8-digit USGS site number in your question or set the site on the forecast page.'
  )
}

function apiErrorMessage(e: unknown, fallback: string): string {
  if (isAxiosError(e)) {
    const status = e.response?.status
    const data = e.response?.data as ApiResponse<unknown> | Record<string, unknown> | string | undefined
    if (typeof data === 'string' && data.trim().length > 0) {
      const snippet = data.length > 280 ? `${data.slice(0, 277)}…` : data
      return status != null ? `${fallback}：${snippet}（HTTP ${status}）` : `${fallback}：${snippet}`
    }
    if (typeof data === 'object' && data != null && 'detail' in data) {
      const d = (data as { detail?: unknown }).detail
      const detailStr =
        typeof d === 'string'
          ? d
          : d != null && typeof JSON.stringify === 'function'
            ? JSON.stringify(d)
            : String(d)
      if (detailStr.length > 0) {
        return status != null ? `${detailStr}（HTTP ${status}）` : detailStr
      }
    }
    if (typeof data === 'object' && data != null && 'message' in data) {
      const msg = (data as ApiResponse<unknown>).message
      if (typeof msg === 'string' && msg.length > 0 && msg !== 'OK') {
        return status != null ? `${msg}（HTTP ${status}）` : msg
      }
    }
    if (e.code === 'ECONNABORTED') {
      return `${fallback}：请求超时。整批预测可能较久，请确认 Vite 代理/axios 已放宽超时，或改用 curl 直打 Spring。`
    }
    if (e.message === 'Network Error') {
      return `${fallback}：网络错误（请确认 Vite 与 Spring 已启动，且代理指向正确端口）。`
    }
    if (status != null) {
      return `${fallback}（HTTP ${status}）`
    }
  }
  return fallback
}

type CopilotWidgetProps = {
  /** Analytics forecast site field, or last-known site when on other routes. */
  siteNo?: string
}

export default function CopilotWidget({ siteNo = '' }: CopilotWidgetProps) {
  const { locale, t } = useLocale()
  const location = useLocation()
  const [copilotExpanded, setCopilotExpanded] = useState(false)
  const [copilotQuestion, setCopilotQuestion] = useState('')
  const [copilotLoading, setCopilotLoading] = useState(false)
  const [copilotErr, setCopilotErr] = useState<string | null>(null)
  const [copilotMessages, setCopilotMessages] = useState<CopilotChatMessage[]>([])
  const [copilotSessionId, setCopilotSessionId] = useState(getOrCreateCopilotSessionId)
  const copilotHistoryRef = useRef<HTMLDivElement | null>(null)

  const minimizeCopilot = useCallback(() => {
    setCopilotExpanded(false)
    localStorage.setItem(COPILOT_MINIMIZED_KEY, 'true')
  }, [])

  const expandCopilot = useCallback(() => {
    setCopilotExpanded(true)
    localStorage.setItem(COPILOT_MINIMIZED_KEY, 'false')
  }, [])

  useEffect(() => {
    if (location.pathname !== '/analytics') return
    if (localStorage.getItem(COPILOT_MINIMIZED_KEY) === 'true') return
    const timer = window.setTimeout(() => setCopilotExpanded(true), 1500)
    return () => window.clearTimeout(timer)
  }, [location.pathname])

  useEffect(() => {
    if (!copilotExpanded) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') minimizeCopilot()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [copilotExpanded, minimizeCopilot])

  const clearCopilotChat = useCallback(() => {
    setCopilotMessages([])
    setCopilotErr(null)
    setCopilotQuestion('')
    const nextId = crypto.randomUUID()
    try {
      localStorage.setItem(COPILOT_SESSION_KEY, nextId)
    } catch {
      /* ignore storage errors */
    }
    setCopilotSessionId(nextId)
  }, [])

  useEffect(() => {
    if (!copilotExpanded) return
    const el = copilotHistoryRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [copilotMessages, copilotLoading, copilotExpanded])

  async function submitCopilotChat() {
    const question = copilotQuestion.trim()
    if (!question) {
      setCopilotErr(translate(locale, 'copilot.questionRequired'))
      return
    }
    const pageSite = siteNo.trim()
    const messageSite = extractSiteNoFromCopilotMessage(question)
    const site = pageSite || messageSite || ''

    if (isWhichTurbiditySitesQuestion(question)) {
      const now = Date.now()
      setCopilotMessages((prev) => [
        ...prev,
        { role: 'user', content: question, timestamp: now },
        { role: 'assistant', content: buildTurbiditySitesCopilotAnswer(), timestamp: now + 1 },
      ])
      setCopilotQuestion('')
      setCopilotErr(null)
      return
    }

    if (copilotQuestionNeedsSite(question) && !site) {
      setCopilotErr(translate(locale, 'copilot.siteRequiredForTurbidity'))
      return
    }

    const history = copilotMessages.map((m) => ({ role: m.role, content: m.content }))
    const userMsg: CopilotChatMessage = {
      role: 'user',
      content: question,
      timestamp: Date.now(),
    }
    setCopilotMessages((prev) => [...prev, userMsg])
    setCopilotQuestion('')
    setCopilotLoading(true)
    setCopilotErr(null)
    try {
      const body: {
        message: string
        siteNo?: string
        sessionId: string
        history: Array<{ role: string; content: string }>
      } = {
        message: question,
        sessionId: copilotSessionId,
        history,
      }
      if (site) body.siteNo = site
      const res = await http.post<ApiResponse<CopilotChatResult>>('/assistant/chat', body, {
        timeout: 180_000,
      })
      const data = res.data.data
      const answer = data?.answer?.trim() ?? ''
      const returnedSession = data?.sessionId ?? data?.session_id
      if (returnedSession && returnedSession !== copilotSessionId) {
        setCopilotSessionId(returnedSession)
        try {
          localStorage.setItem(COPILOT_SESSION_KEY, returnedSession)
        } catch {
          /* ignore storage errors */
        }
      }
      if (answer) {
        const toolTrace = data?.toolTrace ?? data?.tool_trace
        setCopilotMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: answer,
            timestamp: Date.now(),
            meta: {
              toolTrace,
              model: data?.model,
              provider: data?.provider,
            },
          },
        ])
      }
    } catch (e) {
      setCopilotErr(apiErrorMessage(e, translate(locale, 'errors.copilotFailed')))
    } finally {
      setCopilotLoading(false)
    }
  }

  return (
    <div className="copilot-widget">
      {copilotExpanded ? (
        <div
          className="copilot-widget__panel"
          role="dialog"
          aria-labelledby="copilot-widget-title"
        >
          <div className="copilot-widget__head">
            <h3 id="copilot-widget-title">{t('copilot.title')}</h3>
            <div className="copilot-widget__head-actions">
              {copilotMessages.length > 0 && (
                <button
                  type="button"
                  className="copilot-widget__clear"
                  onClick={clearCopilotChat}
                  disabled={copilotLoading}
                >
                  {t('copilot.clearChat')}
                </button>
              )}
              <button
                type="button"
                className="copilot-widget__minimize"
                onClick={minimizeCopilot}
                aria-label={t('copilot.minimizeAria')}
              >
                −
              </button>
            </div>
          </div>
          <div className="copilot-widget__body">
            <div
              className="copilot-history"
              ref={copilotHistoryRef}
              role="log"
              aria-label={t('copilot.historyLabel')}
              aria-live="polite"
            >
              {copilotMessages.map((msg) => (
                <div
                  key={`${msg.role}-${msg.timestamp}`}
                  className={`copilot-bubble copilot-bubble--${msg.role}`}
                >
                  <p className="copilot-bubble__content">{msg.content}</p>
                </div>
              ))}
              {copilotLoading && (
                <p className="copilot-loading forecast-muted" role="status">
                  {t('copilot.loading')}
                </p>
              )}
            </div>
            {copilotErr && (
              <div className="forecast-err">
                {copilotErr}
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => void submitCopilotChat()}
                  disabled={copilotLoading}
                  style={{ marginLeft: 8 }}
                >
                  {t('common.retry')}
                </button>
              </div>
            )}
            <label className="copilot-input-label" htmlFor="copilot-question-input">
              {t('copilot.inputLabel')}
            </label>
            <div className="copilot-input-row">
              <textarea
                id="copilot-question-input"
                className="copilot-input"
                rows={3}
                placeholder={t('copilot.placeholder')}
                value={copilotQuestion}
                onChange={(e) => setCopilotQuestion(e.target.value)}
                disabled={copilotLoading}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault()
                    void submitCopilotChat()
                  }
                }}
              />
              <button type="button" onClick={() => void submitCopilotChat()} disabled={copilotLoading}>
                {copilotLoading ? t('copilot.sending') : t('copilot.send')}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="copilot-widget__fab"
          onClick={expandCopilot}
          aria-label={t('copilot.expandFabAria')}
        >
          <svg className="copilot-widget__fab-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="currentColor"
              d="M4 4h16a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-5.5l-3.7 3.7a1 1 0 0 1-1.7-.7V16H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"
            />
          </svg>
          {t('copilot.fabLabel')}
        </button>
      )}
    </div>
  )
}
