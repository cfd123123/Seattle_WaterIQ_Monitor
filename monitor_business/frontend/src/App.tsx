import axios, { isAxiosError } from 'axios'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useLocale } from './locale/LocaleContext'
import { t as translate, type Locale } from './locale/messages'
import { PUGET_DEMO_SITES } from './pugetDemoSites'
import './App.css'

type ApiResponse<T> = {
  code: string
  message: string
  data: T
}

type MapStationPoint = {
  stationId: number
  stationCode: string
  stationName: string
  province: string | null
  city: string | null
  latitude: number
  longitude: number
  externalId: string | null
  latestPollutionLevel: string | null
  latestSampleTime: string | null
  latestCreateTime: string | null
  openAlertCount: number
}

type AlertItem = {
  id: number
  stationId?: number | null
  status: string
  alertType?: string | null
  ruleCode?: string | null
  title: string
  severity: string
  pollutionLevel?: string | null
  detail?: string | null
  createdAt: string
}

type AlertDetailKv = Record<string, string>

type StationAlertTopItem = {
  station_id: number
  station_code: string
  station_name: string | null
  alert_count: number
  open_alert_count: number
}

type TrendPoint = {
  date: string
  /** Always 0 in trend API (legacy 11-param water check series deprecated). */
  checkCount?: number
  /** Total alerts that day (including types outside the four USGS buckets). */
  alertCount?: number
  flowDetectionCount?: number
  flowAnomalyCount?: number
  turbidityDetectionCount?: number
  turbidityAnomalyCount?: number
}

/** GET /api/stats/trend response body (Jackson camelCase by default). */
type StatsTrendApiData = {
  series?: TrendPoint[]
  points?: TrendPoint[]
  totalCheckCount?: number
  totalAlertCount?: number
  totalAiFailureCount?: number
  totalFlowDetectionCount?: number
  totalFlowAnomalyCount?: number
  totalTurbidityDetectionCount?: number
  totalTurbidityAnomalyCount?: number
  station_id?: number | null
}

type StatsOverviewApiData = {
  uptimeSeconds?: number
  uptimePercent30d?: number
}

type StationForm = {
  stationCode: string
  stationName: string
  province: string
  city: string
  latitude: string
  longitude: string
  externalId: string
}

/** GET /api/forecast series response `data` (Jackson snake_case keys from Python). */
type ForecastResult = {
  site_no: string
  parameter_cd: string
  horizon_hours: number
  forecast_available: boolean
  forecast_value: number | null
  model_version: string | null
  data_points_used: number | null
  reason: string | null
  series_last_timestamp: string | null
  history_days?: number
  history_points?: Array<{ timestamp: string; value: number }>
  forecast_points?: Array<{ timestamp: string; value: number }>
  forecast_pollution_level?: string | null
  forecast_alert_created?: boolean | null
  forecast_alert_reason?: string | null
}

type ForecastForm = {
  siteNo: string
  horizonHours: string
  ivCsvPath: string
}

/** `/api/usgs/turbidity-threshold/scan` response `data` (Jackson camelCase). */
type TurbidityThresholdScanResult = {
  stationsConsidered?: number
  alertsCreated?: number
  skippedNoData?: number
  skippedNoTrigger?: number
  skippedDuplicate?: number
  /** Registered stations with no valid 63680 in IV (skipped from scan). */
  skippedRegisteredNo63680InIv?: number
  summary?: string | null
}

/** `/api/usgs/anomaly/site-param/check` response `data`. */
type SiteParamAnomalyIvResult = {
  site_no?: string
  parameter_cd?: string
  anomaly_available?: boolean | null
  reason?: string | null
  samples_used?: number | null
  sample_timestamp?: string | null
  model_version?: string | null
  anomaly_score?: number | null
  threshold?: number | null
  is_anomaly?: boolean | null
  alert_created?: boolean | null
  alert_reason?: string | null
}

function forecastReasonLabel(locale: Locale, reason: string | null | undefined): string {
  if (!reason) return '—'
  const key = `forecast.seriesReason.${reason}`
  const tr = translate(locale, key)
  return tr !== key ? tr : reason
}

function forecastAlertReasonLabel(locale: Locale, reason: string | null | undefined): string {
  if (!reason) return '—'
  const key = `forecast.predAlertReason.${reason}`
  const tr = translate(locale, key)
  return tr !== key ? tr : reason
}

type AutoForecastSettingsDto = {
  enabled: boolean
  /** ISO string; if Jackson serializes time as array, may be number[] */
  last_run_at?: string | number[] | null
  last_run_summary?: string | null
  schedule_cron?: string | null
}

type ForecastPreviewPointDto = { timestamp: string; value: number }

type AutoForecastBatchItemDto = {
  site_no: string
  station_name?: string | null
  parameter_cd: string
  success: boolean
  forecast_available?: boolean | null
  forecast_value?: number | null
  reason?: string | null
  error_message?: string | null
  forecast_pollution_level?: string | null
  forecast_points_preview?: ForecastPreviewPointDto[] | null
}

type AutoForecastRunNowDto = {
  settings: AutoForecastSettingsDto
  batch_results: AutoForecastBatchItemDto[]
}

function paramCdLabel(locale: Locale, cd: string): string {
  if (cd === '00060') return translate(locale, 'forecast.param.flow00060')
  if (cd === '63680') return translate(locale, 'forecast.param.turb63680')
  if (cd === 'composite') return translate(locale, 'forecast.param.composite')
  return cd
}

function autoBatchRowStatus(locale: Locale, row: AutoForecastBatchItemDto): string {
  if (!row.success) return translate(locale, 'forecast.batchStatus.callFailed')
  if (row.forecast_available === true) return translate(locale, 'forecast.batchStatus.forecasted')
  return translate(locale, 'forecast.batchStatus.unavailable')
}

function AutoBatchSparkline({ pts }: { pts: ForecastPreviewPointDto[] | null | undefined }) {
  const list = pts ?? []
  if (list.length < 2) {
    return <span className="forecast-muted">—</span>
  }
  const data = list.map((p) => ({
    t: p.timestamp.length >= 16 ? p.timestamp.slice(5, 16) : p.timestamp,
    v: p.value,
  }))
  return (
    <div className="auto-batch-sparkline">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 0 }}>
          <Line
            type="monotone"
            dataKey="v"
            stroke="#2563eb"
            dot={false}
            strokeWidth={1.5}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Format last-run time: supports string or Jackson LocalDateTime-as-array [y,m,d,h,mi,s,nano]. */
function formatAutoForecastLastRunAt(value: unknown): string | null {
  if (value == null) return null
  if (typeof value === 'string') {
    const t = value.trim()
    return t.length > 0 ? t : null
  }
  if (Array.isArray(value) && value.length >= 3) {
    const y = Number(value[0])
    const mo = Number(value[1])
    const d = Number(value[2])
    const h = value.length > 3 ? Number(value[3]) : 0
    const mi = value.length > 4 ? Number(value[4]) : 0
    const s = value.length > 5 ? Number(value[5]) : 0
    if (![y, mo, d, h, mi, s].every((n) => Number.isFinite(n))) return null
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${String(y).padStart(4, '0')}-${pad(mo)}-${pad(d)} ${pad(h)}:${pad(mi)}:${pad(s)}`
  }
  return null
}

function siteParamAnomalyReasonLabel(locale: Locale, reason: string | null | undefined): string {
  if (!reason) return '—'
  const key = `forecast.anomalyReason.${reason}`
  const tr = translate(locale, key)
  return tr !== key ? tr : reason
}

const EMPTY_STATION_FORM: StationForm = {
  stationCode: '',
  stationName: '',
  province: '',
  city: '',
  latitude: '',
  longitude: '',
  externalId: '',
}

function apiErrorMessage(e: unknown, fallback: string): string {
  if (isAxiosError(e)) {
    const status = e.response?.status
    const data = e.response?.data as ApiResponse<unknown> | Record<string, unknown> | string | undefined
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

/** Show ISO timestamps in tables as YYYY-MM-DD HH:mm:ss to limit column width. */
function formatShortDateTime(iso: string | null | undefined): string {
  if (iso == null || typeof iso !== 'string') return '—'
  const s = iso.trim()
  if (s.length >= 19) {
    return `${s.slice(0, 10)} ${s.slice(11, 19)}`
  }
  return s || '—'
}

function formatUptimePercentLabel(percent: number | null | undefined): string {
  if (percent == null || !Number.isFinite(percent) || percent < 0) return '—'
  const capped = Math.min(100, Math.max(0, percent))
  return `${capped.toFixed(1)}%`
}

function parseAlertDetail(detail: string | null | undefined): AlertDetailKv {
  const out: AlertDetailKv = {}
  if (!detail) return out
  for (const seg of detail.split(',')) {
    const i = seg.indexOf('=')
    if (i <= 0) continue
    const k = seg.slice(0, i).trim()
    const v = seg.slice(i + 1).trim()
    if (k) out[k] = v
  }
  return out
}

function alertRuleLabel(locale: Locale, ruleCode: string | null | undefined): string {
  const r = (ruleCode || '').trim().toUpperCase()
  if (!r) return '—'
  const key = `forecast.rule.${r}`
  const tr = translate(locale, key)
  return tr !== key ? tr : r
}

function alertStationLabel(a: AlertItem, stationList: MapStationPoint[]): string {
  const id = a.stationId
  if (id == null) return '—'
  const s = stationList.find((x) => x.stationId === id)
  if (!s) return String(id)
  const name = s.stationName != null && s.stationName.trim() !== '' ? s.stationName.trim() : ''
  return name !== '' ? `${s.stationCode} · ${name}` : s.stationCode
}

function alertParameterCd(a: AlertItem): string {
  const d = parseAlertDetail(a.detail)
  const fromDetail = (d.parameter_cd || '').trim()
  if (fromDetail) return fromDetail
  const title = (a.title || '').toLowerCase()
  if (title.includes('00060') || title.includes('流量') || title.includes('flow') || title.includes('discharge'))
    return '00060'
  if (title.includes('63680') || title.includes('浊度') || title.includes('turbidity')) return '63680'
  return '—'
}

function alertObservedValue(a: AlertItem): string {
  const d = parseAlertDetail(a.detail)
  const v = d.forecast_value || d.score || d.ntu_last || d.pollution_level
  return v && v !== '' ? v : '—'
}

function alertThresholdValue(a: AlertItem): string {
  const d = parseAlertDetail(a.detail)
  const t = d.threshold || d.threshold_warn || d.threshold_critical
  return t && t !== '' ? t : '—'
}

function alertModelLabel(a: AlertItem): string {
  const d = parseAlertDetail(a.detail)
  const m = d.model
  return m && m !== '' ? m : '—'
}

function formatRelativeTime(iso: string, locale: Locale): string {
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return '—'
  const diffSec = Math.floor((Date.now() - t) / 1000)
  if (diffSec < 0) return formatShortDateTime(iso)
  if (diffSec < 60) return locale === 'zh' ? '刚刚' : 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return locale === 'zh' ? `${diffMin} 分钟前` : `${diffMin} min ago`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return locale === 'zh' ? `${diffH} 小时前` : `${diffH} hours ago`
  const diffD = Math.floor(diffH / 24)
  if (diffD < 14) return locale === 'zh' ? `${diffD} 天前` : `${diffD} days ago`
  return formatShortDateTime(iso)
}

function aggregateWorstQualityLabel(stations: MapStationPoint[], locale: Locale): string {
  const levels = stations
    .map((s) => (s.latestPollutionLevel || '').trim().toLowerCase())
    .filter(Boolean)
  if (levels.length === 0) return translate(locale, 'dashboard.qualityUnknown')
  const order = ['very poor', 'poor', 'moderate', 'good', 'excellent']
  const keys = [
    'dashboard.qualityVeryPoor',
    'dashboard.qualityPoor',
    'dashboard.qualityModerate',
    'dashboard.qualityGood',
    'dashboard.qualityExcellent',
  ] as const
  let worst = 4
  for (const l of levels) {
    const idx = order.indexOf(l)
    if (idx >= 0) worst = Math.min(worst, idx)
  }
  return translate(locale, keys[worst])
}

function alertCategoryBadge(locale: Locale, a: AlertItem): string {
  const p = alertParameterCd(a)
  if (p === '00060') return locale === 'zh' ? '流量' : 'Flow'
  if (p === '63680') return locale === 'zh' ? '浊度' : 'Turbidity'
  const r = (a.ruleCode || '').toUpperCase()
  if (r.includes('TURB') || r.includes('63680')) return locale === 'zh' ? '浊度' : 'Turbidity'
  if (r.includes('00060') || r.includes('FLOW')) return locale === 'zh' ? '流量' : 'Flow'
  if (r.includes('FORECAST')) return locale === 'zh' ? '水质' : 'Quality'
  return locale === 'zh' ? '告警' : 'Alert'
}

function alertSeverityDotClass(severity: string | undefined): string {
  const s = (severity || '').toUpperCase()
  if (
    s.includes('CRITICAL') ||
    s.includes('HIGH') ||
    s.includes('严重') ||
    s.includes('危急')
  ) {
    return 'alert-card__dot--critical'
  }
  return 'alert-card__dot--warn'
}

function statusPillClass(level: string | null | undefined): string {
  const n = (level || '').trim().toLowerCase()
  if (n === 'excellent') return 'status-pill status-pill--excellent'
  if (n === 'good') return 'status-pill status-pill--good'
  if (n === 'moderate') return 'status-pill status-pill--moderate'
  if (n === 'poor') return 'status-pill status-pill--poor'
  if (n === 'very poor') return 'status-pill status-pill--verypoor'
  return 'status-pill status-pill--muted'
}

function NavIconDash({ className }: { className?: string }) {
  return (
    <svg className={className} width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M4 19V5M4 19h16M10 19V11h4v8"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M7 14l3-3 3 2 4-5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function NavIconMap({ className }: { className?: string }) {
  return (
    <svg className={className} width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M9 19l-6 2V5l6-2 6 2 6-2v16l-6 2-6-2z"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinejoin="round"
      />
      <path
        d="M15 5v14M9 3v14"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  )
}

function NavIconChart({ className }: { className?: string }) {
  return (
    <svg className={className} width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 20V10M10 20V4M16 20v-8M22 20V14" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
    </svg>
  )
}

const http = axios.create({ baseURL: '/api' })

function pollutionColor(level?: string | null): string {
  const norm = (level || '').trim().toLowerCase()
  if (norm === 'excellent') return '#22c55e'
  if (norm === 'good') return '#84cc16'
  if (norm === 'moderate') return '#facc15'
  if (norm === 'poor') return '#f97316'
  if (norm === 'very poor') return '#ef4444'
  return '#94a3b8'
}

/** Registered stations: color by level; no reading yet uses solid blue (vs grey demo circles). */
function registeredStationPathOptions(s: MapStationPoint): {
  color: string
  fillColor: string
  fillOpacity: number
  weight: number
} {
  const level = s.latestPollutionLevel
  if (level != null && String(level).trim() !== '') {
    const c = pollutionColor(level)
    return { color: c, fillColor: c, fillOpacity: 0.55, weight: 2 }
  }
  return {
    color: '#2563eb',
    fillColor: '#93c5fd',
    fillOpacity: 0.7,
    weight: 2,
  }
}

function formatDateISO(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function build7dTrendPath(stationId: number | null): string {
  const now = new Date()
  const from = new Date(now)
  from.setDate(now.getDate() - 6)
  const q = `from=${formatDateISO(from)}&to=${formatDateISO(now)}&granularity=day`
  return stationId == null ? `/stats/trend?${q}` : `/stats/trend?${q}&stationId=${stationId}`
}

type Theme = 'dark' | 'light'

function App() {
  const { locale, setLocale, t } = useLocale()
  const navigate = useNavigate()
  const location = useLocation()
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof document === 'undefined') return 'light'
    const saved = localStorage.getItem('water-theme')
    if (saved === 'light' || saved === 'dark') return saved
    return 'light'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('water-theme', theme)
  }, [theme])

  useEffect(() => {
    if (location.pathname === '/stations' && location.hash === '#add') {
      window.setTimeout(() => {
        document.getElementById('station-form-anchor')?.scrollIntoView({ behavior: 'smooth' })
      }, 80)
    }
  }, [location.pathname, location.hash])
  const [stations, setStations] = useState<MapStationPoint[]>([])
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [stationAlertTop, setStationAlertTop] = useState<StationAlertTopItem[]>([])
  /** null = all-station chart; non-null = filtered by map-selected station */
  const [trendScopeStation, setTrendScopeStation] = useState<{ stationId: number; label: string } | null>(null)
  const [trendScopeLoading, setTrendScopeLoading] = useState(false)
  const [trendScopeErr, setTrendScopeErr] = useState<string | null>(null)
  /** Totals from same API batch as the chart (tell “all zeros” vs no data for this station). */
  const [trendTotals, setTrendTotals] = useState<{
    totalAlertCount: number
    totalFlowDetectionCount: number
    totalFlowAnomalyCount: number
    totalTurbidityDetectionCount: number
    totalTurbidityAnomalyCount: number
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [systemUptimeLabel, setSystemUptimeLabel] = useState<string>('—')
  const [form, setForm] = useState<StationForm>({ ...EMPTY_STATION_FORM })
  const [editingStationCode, setEditingStationCode] = useState<string | null>(null)
  const [forecastStationPick, setForecastStationPick] = useState<string>('')
  const [forecastForm, setForecastForm] = useState<ForecastForm>({
    siteNo: '12117000',
    horizonHours: '12',
    ivCsvPath: '',
  })
  const [forecastParam, setForecastParam] = useState<'00060' | '63680'>('00060')
  const [forecastResult, setForecastResult] = useState<ForecastResult | null>(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastErr, setForecastErr] = useState<string | null>(null)
  /** Single active anomaly result: switching flow/turbidity clears the other branch. */
  const [siteParamAnomalyResult, setSiteParamAnomalyResult] = useState<SiteParamAnomalyIvResult | null>(
    null
  )
  const [siteParamAnomalyActiveCd, setSiteParamAnomalyActiveCd] = useState<'00060' | '63680' | null>(
    null
  )
  const [siteParamAnomalyLoading, setSiteParamAnomalyLoading] = useState<'00060' | '63680' | null>(
    null
  )
  const [siteParamAnomalyErr, setSiteParamAnomalyErr] = useState<string | null>(null)
  const [autoForecastSettings, setAutoForecastSettings] = useState<AutoForecastSettingsDto | null>(null)
  const [autoForecastSaving, setAutoForecastSaving] = useState(false)
  const [autoForecastRunLoading, setAutoForecastRunLoading] = useState(false)
  /** One-line hint after “run batch now” so feedback is visible without only “last run” block. */
  const [autoForecastRunHint, setAutoForecastRunHint] = useState<string | null>(null)
  /** Last batch rows from “run now” (table + sparklines). */
  const [autoForecastBatchResults, setAutoForecastBatchResults] = useState<AutoForecastBatchItemDto[] | null>(null)
  const [ivRefreshDays, setIvRefreshDays] = useState('30')
  const [ivRunChecksAfter, setIvRunChecksAfter] = useState(false)
  const [ivRefreshLoading, setIvRefreshLoading] = useState(false)
  const [ivRefreshErr, setIvRefreshErr] = useState<string | null>(null)
  const [ivRefreshResult, setIvRefreshResult] = useState<{
    rows: number
    start: string
    end: string
    out: string
    mode?: string
    incrementalRowsNew?: number
  } | null>(null)
  const [turbidityScanLoading, setTurbidityScanLoading] = useState(false)
  const [turbidityScanErr, setTurbidityScanErr] = useState<string | null>(null)
  const [turbidityScanResult, setTurbidityScanResult] = useState<TurbidityThresholdScanResult | null>(null)

  /** Normalize + coerce numbers; avoids Recharts skipping lines on undefined (snake_case fallback). */
  const trendChartData = useMemo(
    () =>
      trend.map((p) => {
        const row = p as TrendPoint & Record<string, unknown>
        return {
          ...p,
          flowDetectionCount: Number(
            row.flowDetectionCount ?? row.flow_detection_count ?? 0
          ),
          flowAnomalyCount: Number(row.flowAnomalyCount ?? row.flow_anomaly_count ?? 0),
          turbidityDetectionCount: Number(
            row.turbidityDetectionCount ?? row.turbidity_detection_count ?? 0
          ),
          turbidityAnomalyCount: Number(
            row.turbidityAnomalyCount ?? row.turbidity_anomaly_count ?? 0
          ),
        }
      }),
    [trend]
  )

  const trendYAxisMax = useMemo(() => {
    let m = 0
    for (const p of trendChartData) {
      m = Math.max(
        m,
        p.flowDetectionCount,
        p.flowAnomalyCount,
        p.turbidityDetectionCount,
        p.turbidityAnomalyCount
      )
    }
    return Math.max(1, m)
  }, [trendChartData])

  const totalOpenAlerts = useMemo(
    () => stations.reduce((acc, s) => acc + (Number(s.openAlertCount) || 0), 0),
    [stations]
  )

  const qualitySummaryLabel = useMemo(
    () => aggregateWorstQualityLabel(stations, locale),
    [stations, locale]
  )

  const applyTrendApiData = useCallback((body: StatsTrendApiData | undefined) => {
    setTrend(body?.series ?? body?.points ?? [])
    setTrendTotals({
      totalAlertCount: body?.totalAlertCount ?? 0,
      totalFlowDetectionCount: body?.totalFlowDetectionCount ?? 0,
      totalFlowAnomalyCount: body?.totalFlowAnomalyCount ?? 0,
      totalTurbidityDetectionCount: body?.totalTurbidityDetectionCount ?? 0,
      totalTurbidityAnomalyCount: body?.totalTurbidityAnomalyCount ?? 0,
    })
  }, [])

  const forecastTrend = useMemo(() => {
    if (!forecastResult?.forecast_available) return []
    const history = forecastResult.history_points || []
    const future = forecastResult.forecast_points || []
    if (history.length === 0 && future.length === 0) return []
    const rows: Array<{ time: string; actual?: number; predicted?: number }> = history.map((p) => ({
      time: p.timestamp,
      actual: p.value,
    }))
    if (history.length > 0) {
      const last = history[history.length - 1]
      rows.push({ time: last.timestamp, predicted: last.value })
    }
    rows.push(
      ...future.map((p) => ({
        time: p.timestamp,
        predicted: p.value,
      }))
    )
    return rows
  }, [forecastResult])

  async function loadTrendForStation(stationId: number | null, label: string | null) {
    if (stationId == null) {
      setTrendScopeStation(null)
      setTrendScopeErr(null)
      setTrend([])
      setTrendTotals(null)
      return
    }
    setTrendScopeLoading(true)
    setTrendScopeErr(null)
    try {
      const path = build7dTrendPath(stationId)
      const trendRes = await http.get<ApiResponse<StatsTrendApiData>>(path)
      const trendBody = trendRes.data.data
      applyTrendApiData(trendBody)
      if (stationId != null) {
        const lab =
          label != null && label.trim() !== ''
            ? label.trim()
            : `${translate(locale, 'forecast.stationPrefix')} #${stationId}`
        setTrendScopeStation({ stationId, label: lab })
      } else {
        setTrendScopeStation(null)
      }
    } catch (e) {
      setTrendScopeErr(apiErrorMessage(e, translate(locale, 'errors.trendLoadFailed')))
      setTrendTotals(null)
    } finally {
      setTrendScopeLoading(false)
    }
  }

  useEffect(() => {
    void http
      .get<ApiResponse<AutoForecastSettingsDto>>('/forecast/auto-settings')
      .then((r) => setAutoForecastSettings(r.data.data))
      .catch(() => setAutoForecastSettings(null))
  }, [])

  async function saveAutoForecastEnabled(enabled: boolean) {
    setAutoForecastSaving(true)
    setForecastErr(null)
    try {
      const res = await http.put<ApiResponse<AutoForecastSettingsDto>>('/forecast/auto-settings', {
        enabled,
      })
      setAutoForecastSettings(res.data.data)
    } catch (e) {
      setForecastErr(apiErrorMessage(e, translate(locale, 'errors.saveAutoForecastFailed')))
    } finally {
      setAutoForecastSaving(false)
    }
  }

  async function runAutoForecastBatchNow() {
    setAutoForecastRunLoading(true)
    setForecastErr(null)
    setAutoForecastRunHint(null)
    setAutoForecastBatchResults(null)
    try {
      const res = await http.post<ApiResponse<AutoForecastRunNowDto>>(
        '/forecast/auto-settings/run-now',
        {},
        { timeout: 1_800_000 }
      )
      const body = res.data?.data
      if (body?.settings != null) {
        const next = body.settings
        setAutoForecastSettings((prev) => ({
          ...(prev ?? { enabled: next.enabled }),
          ...next,
          schedule_cron: next.schedule_cron ?? prev?.schedule_cron ?? null,
          last_run_at: next.last_run_at ?? prev?.last_run_at,
          last_run_summary: next.last_run_summary ?? prev?.last_run_summary,
        }))
        const sum = next.last_run_summary?.trim()
        setAutoForecastRunHint(
          sum && sum.length > 0
            ? `${translate(locale, 'forecast.batchHintDone')}${sum}`
            : translate(locale, 'forecast.batchHintFooter')
        )
        setAutoForecastBatchResults(body.batch_results ?? [])
      } else {
        setAutoForecastRunHint(translate(locale, 'forecast.batchNoSettings'))
        setAutoForecastBatchResults([])
      }
    } catch (e) {
      setForecastErr(apiErrorMessage(e, translate(locale, 'errors.runBatchFailed')))
    } finally {
      setAutoForecastRunLoading(false)
    }
  }

  const refreshAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    setTrendScopeStation(null)
    setTrendScopeErr(null)
    setTrend([])
    setTrendTotals(null)
    try {
      const [stationsRes, alertsRes, topRes, overviewRes] = await Promise.all([
        http.get<ApiResponse<MapStationPoint[]>>('/map/stations'),
        http.get<ApiResponse<{ content: AlertItem[] }>>('/alerts?page=0&size=8'),
        http.get<ApiResponse<{ items?: StationAlertTopItem[] }>>('/stats/station-alert-top?days=7&topN=8'),
        http.get<ApiResponse<StatsOverviewApiData>>('/stats/overview'),
      ])
      setStations(stationsRes.data.data || [])
      setAlerts(alertsRes.data.data?.content || [])
      setStationAlertTop(topRes.data.data?.items || [])
      setSystemUptimeLabel(formatUptimePercentLabel(overviewRes.data.data?.uptimePercent30d))
    } catch (e) {
      console.error('[monitor-ui] 初始数据加载失败', e)
      if (isAxiosError(e)) {
        const code = e.code
        const msg = e.message
        const st = e.response?.status
        console.error('[monitor-ui] axios detail', { code, message: msg, httpStatus: st, url: e.config?.url })
      }
      setError(apiErrorMessage(e, translate(locale, 'errors.backendUnreachable')))
      setStationAlertTop([])
      setSystemUptimeLabel('—')
    } finally {
      setLoading(false)
    }
  }, [locale])

  async function refreshIvCsv() {
    const d = Number(ivRefreshDays.trim())
    if (!Number.isFinite(d) || d < 1 || d > 90) {
      setIvRefreshErr(translate(locale, 'errors.ivDaysInvalid'))
      return
    }
    setIvRefreshLoading(true)
    setIvRefreshErr(null)
    setIvRefreshResult(null)
    try {
      const res = await http.post<
        ApiResponse<{
          rows: number
          start: string
          end: string
          out: string
          mode?: string
          incrementalRowsNew?: number
        }>
      >('/usgs/iv/refresh', { days: d, runChecksAfterRefresh: ivRunChecksAfter })
      const data = res.data.data
      setIvRefreshResult({
        rows: data.rows,
        start: data.start,
        end: data.end,
        out: data.out,
        mode: data.mode,
        incrementalRowsNew: data.incrementalRowsNew,
      })
      if (ivRunChecksAfter) {
        await refreshAll()
      }
    } catch {
      setIvRefreshErr(translate(locale, 'errors.ivRefreshFailed'))
    } finally {
      setIvRefreshLoading(false)
    }
  }

  async function scanTurbidityThreshold() {
    setTurbidityScanLoading(true)
    setTurbidityScanErr(null)
    setTurbidityScanResult(null)
    try {
      const res = await http.post<ApiResponse<TurbidityThresholdScanResult>>('/usgs/turbidity-threshold/scan')
      setTurbidityScanResult(res.data.data ?? null)
      const alertsRes = await http.get<ApiResponse<{ content: AlertItem[] }>>('/alerts?page=0&size=8')
      setAlerts(alertsRes.data.data?.content || [])
    } catch (e) {
      setTurbidityScanErr(
        apiErrorMessage(e, translate(locale, 'errors.turbidityScanFailed'))
      )
    } finally {
      setTurbidityScanLoading(false)
    }
  }

  async function submitForecast() {
    if (!forecastForm.siteNo.trim()) {
      setForecastErr(translate(locale, 'errors.siteNoRequired'))
      return
    }
    const h = Number(forecastForm.horizonHours)
    if (!Number.isFinite(h) || h < 1 || h > 168) {
      setForecastErr(translate(locale, 'errors.horizonInvalid'))
      return
    }
    setForecastLoading(true)
    setForecastErr(null)
    setForecastResult(null)
    setSiteParamAnomalyErr(null)
    setSiteParamAnomalyResult(null)
    setSiteParamAnomalyActiveCd(null)
    try {
      const body: Record<string, string | number> = {
        site_no: forecastForm.siteNo.trim(),
        parameter_cd: forecastParam,
        horizon_hours: h,
      }
      const p = forecastForm.ivCsvPath.trim()
      if (p) body.iv_csv_path = p
      const res = await http.post<ApiResponse<ForecastResult>>('/forecast/series', {
        ...body,
        history_days: 10,
      })
      setForecastResult(res.data.data)
    } catch (e) {
      setForecastErr(apiErrorMessage(e, translate(locale, 'errors.forecastRequestFailed')))
    } finally {
      setForecastLoading(false)
    }
  }

  async function submitSiteParamAnomaly(parameterCd: '00060' | '63680') {
    if (!forecastForm.siteNo.trim()) {
      setSiteParamAnomalyErr(translate(locale, 'errors.siteNoRequired'))
      return
    }
    setSiteParamAnomalyLoading(parameterCd)
    setSiteParamAnomalyErr(null)
    setSiteParamAnomalyActiveCd(parameterCd)
    setSiteParamAnomalyResult(null)
    try {
      const body: Record<string, string> = {
        site_no: forecastForm.siteNo.trim(),
        parameter_cd: parameterCd,
      }
      const p = forecastForm.ivCsvPath.trim()
      if (p) body.iv_csv_path = p
      const res = await http.post<ApiResponse<SiteParamAnomalyIvResult>>(
        '/usgs/anomaly/site-param/check',
        body
      )
      setSiteParamAnomalyResult(res.data.data)
      if (trendScopeStation != null) {
        void loadTrendForStation(trendScopeStation.stationId, trendScopeStation.label)
      }
    } catch (e) {
      setSiteParamAnomalyErr(apiErrorMessage(e, translate(locale, 'errors.anomalyCheckFailed')))
      setSiteParamAnomalyResult(null)
      setSiteParamAnomalyActiveCd(null)
    } finally {
      setSiteParamAnomalyLoading(null)
    }
  }

  async function submitStation() {
    if (!form.stationCode?.trim() || !form.latitude || !form.longitude) {
      setError(translate(locale, 'errors.stationFieldsRequired'))
      return
    }
    const body = {
      stationCode: form.stationCode.trim(),
      stationName: (form.stationName || form.stationCode).trim(),
      province: form.province?.trim() || null,
      city: form.city?.trim() || null,
      latitude: Number(form.latitude),
      longitude: Number(form.longitude),
      externalId: form.externalId.trim() || null,
    }
    setError(null)
    try {
      if (editingStationCode) {
        await http.put(`/stations/${encodeURIComponent(editingStationCode)}`, body)
      } else {
        await http.post('/stations', body)
      }
      setEditingStationCode(null)
      setForm({ ...EMPTY_STATION_FORM })
      await refreshAll()
    } catch (e) {
      setError(apiErrorMessage(e, translate(locale, 'errors.stationSaveFailed')))
    }
  }

  async function deleteStation(stationCode: string) {
    const code = stationCode.trim()
    if (!code) return
    if (
      !window.confirm(translate(locale, 'errors.deleteConfirm').replace('{{code}}', code))
    ) {
      return
    }
    setError(null)
    try {
      await http.delete(`/stations/${encodeURIComponent(code)}`)
      if (editingStationCode === code) {
        setEditingStationCode(null)
        setForm({ ...EMPTY_STATION_FORM })
      }
      await refreshAll()
    } catch (e) {
      setError(apiErrorMessage(e, translate(locale, 'errors.deleteFailed')))
    }
  }

  function loadStationForEdit(s: MapStationPoint) {
    setError(null)
    setEditingStationCode(s.stationCode)
    setForm({
      stationCode: s.stationCode,
      stationName: s.stationName || '',
      province: s.province || '',
      city: s.city || '',
      latitude: String(s.latitude),
      longitude: String(s.longitude),
      externalId: s.externalId != null ? String(s.externalId) : '',
    })
  }

  function cancelStationEdit() {
    setEditingStationCode(null)
    setForm({ ...EMPTY_STATION_FORM })
  }

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  /** Demo grey points hidden when a registered station uses the same USGS externalId. */
  const demoSitesOnMap = useMemo(() => {
    const reg = new Set(
      stations
        .map((s) => (s.externalId != null ? String(s.externalId).trim() : ''))
        .filter(Boolean)
    )
    return PUGET_DEMO_SITES.filter((d) => !reg.has(d.externalId))
  }, [stations])

  /** Map center: mean of registered stations, else demo sites, else Puget Sound default. */
  const mapCenter: [number, number] = useMemo(() => {
    if (stations.length > 0) {
      const lat = stations.reduce((a, s) => a + s.latitude, 0) / stations.length
      const lng = stations.reduce((a, s) => a + s.longitude, 0) / stations.length
      return [lat, lng]
    }
    if (demoSitesOnMap.length > 0) {
      const lat = demoSitesOnMap.reduce((a, s) => a + s.latitude, 0) / demoSitesOnMap.length
      const lng = demoSitesOnMap.reduce((a, s) => a + s.longitude, 0) / demoSitesOnMap.length
      return [lat, lng]
    }
    return [47.52, -121.85]
  }, [stations, demoSitesOnMap])

  const mapZoom = useMemo(() => {
    if (stations.length === 0 && demoSitesOnMap.length > 0) return 9
    if (stations.length === 0) return 8
    if (stations.length === 1) return 9
    return 8
  }, [stations.length, demoSitesOnMap.length])

  return (
    <main className="page">
      <header className="header header--wm">
        <div className="header-brand-row">
          <div className="header-left-cluster">
            <div className="header-brand">
              <div className="header-logo" aria-hidden>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 3s6 6.2 6 11.2a6 6 0 1 1-12 0C6 9.2 12 3 12 3z"
                    fill="currentColor"
                    opacity="0.95"
                  />
                </svg>
              </div>
              <div className="header-brand-text">
                <div className="header-brand-name">{t('app.brandName')}</div>
                <div className="header-brand-sub">{t('app.subtitle')}</div>
              </div>
            </div>
            <nav className="app-nav app-nav--pill" aria-label={t('common.navAria')}>
              <NavLink className="app-nav__link" to="/" end>
                <NavIconDash className="app-nav__icon" />
                {t('nav.home')}
              </NavLink>
              <NavLink className="app-nav__link" to="/stations">
                <NavIconMap className="app-nav__icon" />
                {t('nav.stations')}
              </NavLink>
              <NavLink className="app-nav__link" to="/analytics">
                <NavIconChart className="app-nav__icon" />
                {t('nav.analytics')}
              </NavLink>
            </nav>
          </div>
          <div className="header-actions">
            <div className="theme-toggle-group" role="group" aria-label={t('common.themeAria')}>
              <button
                type="button"
                className={`theme-toggle ${theme === 'light' ? 'theme-toggle--active' : ''}`}
                onClick={() => setTheme('light')}
              >
                {t('common.themeLight')}
              </button>
              <button
                type="button"
                className={`theme-toggle ${theme === 'dark' ? 'theme-toggle--active' : ''}`}
                onClick={() => setTheme('dark')}
              >
                {t('common.themeDark')}
              </button>
            </div>
            <label className="lang-select-wrap">
              <span className="visually-hidden">{t('common.langSelectAria')}</span>
              <select
                className="lang-select"
                value={locale}
                onChange={(e) => setLocale(e.target.value as 'zh' | 'en')}
                aria-label={t('common.langSelectAria')}
              >
                <option value="zh">{t('common.langZh')}</option>
                <option value="en">{t('common.langEn')}</option>
              </select>
            </label>
            <button
              type="button"
              onClick={() => void refreshAll()}
              disabled={loading}
              aria-busy={loading}
              aria-label={t('common.refreshDashAria')}
            >
              {loading ? t('common.refreshing') : t('common.refresh')}
            </button>
          </div>
        </div>
      </header>

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      <Routes>
        <Route
          path="/"
          element={
            <>
              <section className="kpi-grid" aria-label="KPI">
                <div className="kpi-card">
                  <div className="kpi-card__icon kpi-card__icon--stations" aria-hidden />
                  <div className="kpi-card__body">
                    <span className="kpi-card__label">{t('dashboard.kpiStations')}</span>
                    <span className="kpi-card__value">{stations.length}</span>
                  </div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-card__icon kpi-card__icon--alerts" aria-hidden />
                  <div className="kpi-card__body">
                    <span className="kpi-card__label">{t('dashboard.kpiAlerts')}</span>
                    <span className="kpi-card__value">{totalOpenAlerts}</span>
                  </div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-card__icon kpi-card__icon--quality" aria-hidden />
                  <div className="kpi-card__body">
                    <span className="kpi-card__label">{t('dashboard.kpiQuality')}</span>
                    <span className="kpi-card__value kpi-card__value--text">{qualitySummaryLabel}</span>
                  </div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-card__icon kpi-card__icon--uptime" aria-hidden />
                  <div className="kpi-card__body">
                    <span className="kpi-card__label">{t('dashboard.kpiUptime')}</span>
                    <span className="kpi-card__value">{systemUptimeLabel}</span>
                  </div>
                </div>
              </section>

      <div className="dashboard-split">
        <div className="card map-card">
          <h3>{t('dashboard.mapTitle')}</h3>
          <p className="map-card-hint">
            {stations.length === 0 ? (
              t('map.emptyHint')
            ) : (
              <>
                {t('map.legend')}
                <strong>{t('map.legendStrong')}</strong>
                {t('map.legendAfter')}
              </>
            )}
          </p>
          <MapContainer
            key={`${mapCenter[0].toFixed(4)},${mapCenter[1].toFixed(4)}`}
            center={mapCenter}
            zoom={mapZoom}
            style={{ height: 380, width: '100%' }}
          >
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            {demoSitesOnMap.map((d) => (
              <CircleMarker
                key={`demo-${d.externalId}`}
                center={[d.latitude, d.longitude]}
                radius={7}
                pathOptions={{
                  color: '#64748b',
                  fillColor: '#94a3b8',
                  fillOpacity: 0.45,
                  weight: 2,
                  dashArray: '4 3',
                }}
              >
                <Popup>
                  <strong>{t('map.demoTitle')}</strong>
                  <br />
                  {d.name}
                  <br />
                  USGS：<code>{d.externalId}</code>
                  <br />
                  <span className="map-popup-muted">{t('map.demoNote')}</span>
                </Popup>
              </CircleMarker>
            ))}
            {stations.map((s) => (
              <CircleMarker
                key={s.stationId}
                center={[s.latitude, s.longitude]}
                radius={9}
                pathOptions={registeredStationPathOptions(s)}
                eventHandlers={{
                  click: () => {
                    void loadTrendForStation(s.stationId, s.stationName || s.stationCode)
                  },
                }}
              >
                <Popup>
                  <strong>{s.stationName || s.stationCode}</strong>
                  <br />
                  <span className="map-popup-muted">
                    {t('map.registeredLine')}
                    {s.stationCode}
                  </span>
                  <br />
                  {s.city || '-'} / {s.province || '-'}
                  <br />
                  {t('map.latestLevel')}
                  {s.latestPollutionLevel || t('map.noLevelYet')}
                  <br />
                  {t('map.openAlerts')}
                  {s.openAlertCount}
                  <br />
                  USGS：{s.externalId || '—'}
                  <br />
                  <span className="map-popup-muted">{t('map.popupNote')}</span>
                  <button
                    type="button"
                    className="map-popup-trend-btn"
                    onClick={(ev) => {
                      ev.preventDefault()
                      ev.stopPropagation()
                      void loadTrendForStation(s.stationId, s.stationName || s.stationCode)
                    }}
                  >
                    {t('map.popupTrendBtn')}
                  </button>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
          <div className="map-legend-bar" aria-label={t('dashboard.mapLegendTitle')}>
            <span>
              <i className="map-leg map-leg--excellent" />
              {t('dashboard.qualityExcellent')}
            </span>
            <span>
              <i className="map-leg map-leg--good" />
              {t('dashboard.qualityGood')}
            </span>
            <span>
              <i className="map-leg map-leg--moderate" />
              {t('dashboard.qualityModerate')}
            </span>
            <span>
              <i className="map-leg map-leg--poor" />
              {t('dashboard.qualityPoor')}
            </span>
            <span>
              <i className="map-leg map-leg--verypoor" />
              {t('dashboard.qualityVeryPoor')}
            </span>
          </div>
        </div>

        <div className="card alerts-feed">
          <div className="alerts-feed__head">
            <h3>{t('dashboard.recentAlerts')}</h3>
            <span className="alerts-feed__bell" aria-hidden>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 22a2 2 0 002-2H10a2 2 0 002 2zm6-6V11a6 6 0 10-12 0v5l-2 2h16l-2-2z"
                  stroke="currentColor"
                  strokeWidth="1.5"
                />
              </svg>
            </span>
          </div>
          <div className="alerts-feed__list">
            {alerts.slice(0, 8).map((a) => (
              <article key={a.id} className="alert-card">
                <span className={`alert-card__dot ${alertSeverityDotClass(a.severity)}`} />
                <div className="alert-card__main">
                  <div className="alert-card__row1">
                    <span className="alert-card__place">{alertStationLabel(a, stations)}</span>
                    <span className="alert-card__time">{formatRelativeTime(a.createdAt, locale)}</span>
                  </div>
                  <div className="alert-card__row2">
                    <span className="alert-card__tag">{alertCategoryBadge(locale, a)}</span>
                  </div>
                  <p className="alert-card__desc">
                    {a.title && a.title.trim() !== '' ? a.title : t('dashboard.alertFallbackTitle')}
                  </p>
                </div>
              </article>
            ))}
            {alerts.length === 0 && <p className="alerts-feed__empty">{t('alertTable.empty')}</p>}
          </div>
        </div>
      </div>

      <section className="card trend-card trend-card--wide">
        <div className="trend-card-head">
          <h3>{t('dashboard.trendTitleShort')}</h3>
            {trendScopeStation != null && (
              <button
                type="button"
                className="btn-secondary trend-reset-btn"
                disabled={trendScopeLoading}
                onClick={() => void loadTrendForStation(null, null)}
              >
                {t('trend.resetAll')}
              </button>
            )}
          </div>
          {trendScopeStation == null ? (
            <div className="chart-empty">{t('trend.clickStationPrompt')}</div>
          ) : (
            <>
              <p className="chart-caption trend-scope-caption">
                <>
                  {t('trend.scopeStation')}
                  <strong>{trendScopeStation.label}</strong>（<code>stationId={trendScopeStation.stationId}</code>
                  {t('trend.scopeStationAfter')}
                </>
              </p>
              <p className="chart-caption trend-legend-usgs">
                <span className="trend-legend-group">
                  <span className="swatch swatch-flow-det" /> {t('trend.lineFlowDet')}
                </span>
                <span className="trend-legend-group">
                  <span className="swatch swatch-flow-if" /> {t('trend.lineFlowIf')}
                </span>
                <span className="trend-legend-group">
                  <span className="swatch swatch-turb-det" /> {t('trend.lineTurbDet')}
                </span>
                <span className="trend-legend-group">
                  <span className="swatch swatch-turb-anom" /> {t('trend.lineTurbAnom')}
                </span>
                {trendScopeLoading ? <span className="trend-loading-inline">{t('trend.loading')}</span> : null}
              </p>
              {trendScopeErr != null && <p className="trend-scope-err">{trendScopeErr}</p>}
              {trendTotals != null && (
                <p className="trend-totals-line forecast-muted">
                  {t('trend.totalsPrefix')}
                  <strong>{trendTotals.totalFlowDetectionCount}</strong>
                  {t('trend.totalsMid1')}
                  <strong>{trendTotals.totalFlowAnomalyCount}</strong>
                  {t('trend.totalsMid2')}
                  <strong>{trendTotals.totalTurbidityDetectionCount}</strong>
                  {t('trend.totalsMid3')}
                  <strong>{trendTotals.totalTurbidityAnomalyCount}</strong>
                  {' · '}
                  {t('trend.totalsAlerts')}
                  <strong>{trendTotals.totalAlertCount}</strong>
                  {`${t('trend.scopeStationParen')}${trendScopeStation.stationId}${t('trend.scopeStationCloseParen')}`}
                </p>
              )}
              {trend.length === 0 ? (
                <div className="chart-empty">
                  <>
                    {t('trend.emptyStation')}
                    {trendScopeStation.label}
                    {t('trend.emptyStationAfter')}
                  </>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart
                    data={trendChartData}
                    margin={{ top: 8, right: 12, left: 4, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.25)" />
                    <XAxis dataKey="date" tick={{ fill: 'var(--wm-text-muted)', fontSize: 11 }} />
                    <YAxis
                      allowDecimals={false}
                      domain={[0, trendYAxisMax]}
                      tick={{ fill: 'var(--wm-text-muted)', fontSize: 11 }}
                    />
                    <Tooltip
                      contentStyle={{
                        background: 'var(--wm-bg-elevated)',
                        border: '1px solid var(--wm-border)',
                        borderRadius: 8,
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      type="linear"
                      dataKey="flowDetectionCount"
                      stroke="#38bdf8"
                      strokeWidth={2}
                      dot={{ r: 3, strokeWidth: 1, fill: '#38bdf8' }}
                      activeDot={{ r: 5 }}
                      isAnimationActive={false}
                      name={t('trend.lineFlowDet')}
                    />
                    <Line
                      type="linear"
                      dataKey="flowAnomalyCount"
                      stroke="#7dd3fc"
                      strokeDasharray="6 4"
                      strokeWidth={2}
                      dot={{ r: 3, strokeWidth: 1, fill: '#7dd3fc' }}
                      activeDot={{ r: 5 }}
                      isAnimationActive={false}
                      name={t('trend.lineFlowIf')}
                    />
                    <Line
                      type="linear"
                      dataKey="turbidityDetectionCount"
                      stroke="#34d399"
                      strokeWidth={2}
                      dot={{ r: 3, strokeWidth: 1, fill: '#34d399' }}
                      activeDot={{ r: 5 }}
                      isAnimationActive={false}
                      name={t('trend.lineTurbDet')}
                    />
                    <Line
                      type="linear"
                      dataKey="turbidityAnomalyCount"
                      stroke="#6ee7b7"
                      strokeDasharray="6 4"
                      strokeWidth={2}
                      dot={{ r: 3, strokeWidth: 1, fill: '#6ee7b7' }}
                      activeDot={{ r: 5 }}
                      isAnimationActive={false}
                      name={t('trend.lineTurbAnom')}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </>
          )}
      </section>
            </>
          }
        />
        <Route
          path="/analytics"
          element={
            <>
              <h1 className="analytics-page-title">{t('analytics.pageTitle')}</h1>
              <section className="station-form forecast-panel forecast-panel--analytics">
        <h3 className="forecast-card-heading">{t('analytics.forecastCardTitle')}</h3>
        <p className="analytics-card-desc">{t('analytics.forecastCardDesc')}</p>
        <div className="auto-forecast-row">
          <div className="auto-forecast-actions">
            <label className="auto-forecast-label">
              <input
                type="checkbox"
                checked={autoForecastSettings?.enabled ?? false}
                disabled={autoForecastSettings == null || autoForecastSaving}
                onChange={(e) => void saveAutoForecastEnabled(e.target.checked)}
              />
              {autoForecastSaving ? t('forecast.savingAuto') : t('forecast.enableServerAuto')}
            </label>
            <button
              type="button"
              className="btn-secondary auto-forecast-run-now"
              disabled={autoForecastSettings == null || autoForecastRunLoading || autoForecastSaving}
              onClick={() => void runAutoForecastBatchNow()}
            >
              {autoForecastRunLoading ? t('forecast.runningBatch') : t('forecast.runBatchNow')}
            </button>
          </div>
          {autoForecastRunHint != null && autoForecastRunHint !== '' && (
            <p className="auto-forecast-run-hint" role="status">
              {autoForecastRunHint}
            </p>
          )}
          <p className="auto-forecast-desc forecast-muted">
            {t('forecast.autoA1')}
            <strong>{t('forecast.autoA2')}</strong>
            {t('forecast.autoA3')}
            <code>horizon_hours=24</code>
            {t('forecast.autoA4')}
            <code>history_days=10</code>
            {t('forecast.autoA5')}
          </p>
          {autoForecastSettings?.schedule_cron != null && autoForecastSettings.schedule_cron !== '' && (
            <p className="forecast-muted">
              {t('forecast.scheduleLabel')}
              <code>{autoForecastSettings.schedule_cron}</code>
              {t('forecast.scheduleSuffix')}
            </p>
          )}
          {(() => {
            const lastRunLabel = formatAutoForecastLastRunAt(autoForecastSettings?.last_run_at)
            const sumText = autoForecastSettings?.last_run_summary?.trim() ?? ''
            if (lastRunLabel == null && sumText === '') return null
            return (
              <p className="forecast-muted auto-forecast-last">
                {t('forecast.lastRunPrefix')}
                {lastRunLabel ?? '—'}
                {sumText !== '' ? ` — ${sumText}` : ''}
              </p>
            )
          })()}
        </div>
        {autoForecastBatchResults !== null && (
          <div className="auto-batch-results">
            <div className="auto-batch-results-header">
              <h4 className="auto-batch-results-title">{t('forecast.batchResultsTitle')}</h4>
              <button
                type="button"
                className="btn-secondary auto-batch-results-dismiss"
                onClick={() => {
                  setAutoForecastBatchResults(null)
                  setAutoForecastRunHint(null)
                }}
              >
                {t('forecast.hideBatchResults')}
              </button>
            </div>
            <p className="forecast-muted auto-batch-results-note">
              {t('forecast.batchNoteBefore')}
              <strong>{t('forecast.batchNoteStrong')}</strong>
              {t('forecast.batchNoteAfter')}
              <code>site_no</code>
              {t('forecast.batchNoteAfter2')}
            </p>
            {autoForecastBatchResults.length === 0 ? (
              <p className="forecast-muted">
                {t('forecast.batchEmptyBefore')}
                <strong>{t('forecast.batchEmptyStrong')}</strong>
                {t('forecast.batchEmptyAfter')}
              </p>
            ) : (
              <div className="auto-batch-table-wrap">
                <table className="station-table station-table--compact auto-batch-table">
                  <thead>
                    <tr>
                      <th>{t('forecast.thStation')}</th>
                      <th>{t('forecast.thName')}</th>
                      <th>{t('forecast.thParam')}</th>
                      <th>{t('forecast.thStatus')}</th>
                      <th>{t('forecast.thForecastValue')}</th>
                      <th>{t('forecast.thLevel')}</th>
                      <th>{t('forecast.thTrend')}</th>
                      <th>{t('forecast.thNote')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {autoForecastBatchResults.map((row) => (
                      <tr key={`${row.site_no}-${row.parameter_cd}`}>
                        <td>
                          <code>{row.site_no}</code>
                        </td>
                        <td>{row.station_name != null && row.station_name.trim() !== '' ? row.station_name : '—'}</td>
                        <td>{paramCdLabel(locale, row.parameter_cd)}</td>
                        <td>{autoBatchRowStatus(locale, row)}</td>
                        <td>
                          {row.forecast_value != null && Number.isFinite(row.forecast_value)
                            ? row.forecast_value.toFixed(3)
                            : '—'}
                        </td>
                        <td>
                          {row.forecast_pollution_level != null && row.forecast_pollution_level.trim() !== '' ? (
                            <span
                              className="auto-batch-level-pill"
                              style={{
                                background: pollutionColor(row.forecast_pollution_level),
                                color: '#0f172a',
                              }}
                            >
                              {row.forecast_pollution_level}
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td>
                          <AutoBatchSparkline pts={row.forecast_points_preview} />
                        </td>
                        <td className="auto-batch-desc-cell">
                          {!row.success
                            ? row.error_message ?? '—'
                            : forecastReasonLabel(locale, row.reason)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <p className="forecast-hint">
          {t('forecast.hintH01')}
          <code>/api/forecast/series</code>
          {t('forecast.hintH02')}
          <strong>{t('forecast.hintH03')}</strong>
          {t('forecast.hintH04')}
          <strong>{t('forecast.hintH05')}</strong>
          {t('forecast.hintH06')}
          <strong>{t('forecast.hintH07')}</strong>
          {t('forecast.hintH08')}
          <code>ai_service/data/usgs_puget_iv.csv</code>
          {t('forecast.hintH09')}
          <strong>{t('forecast.hintH10')}</strong>
          {t('forecast.hintH11')}
          {t('forecast.hintH12')}
          <code>/api/usgs/anomaly/site-param/check</code>
          {t('forecast.hintH13')}
          <strong>{t('forecast.hintH14')}</strong>
          {t('forecast.hintH15')}
          {t('forecast.hintH16')}
          <strong>{t('forecast.hintH17')}</strong>
          {t('forecast.hintH18')}
          <code>/api/usgs/turbidity-threshold/scan</code>
          {t('forecast.hintH19')}
        </p>
        <h4 className="analytics-subhead">{t('analytics.opsTitle')}</h4>
        <div className="iv-refresh-row">
          <label className="iv-refresh-label" htmlFor="iv-refresh-days">
            {t('forecast.ivBacktrackDays')}
          </label>
          <input
            id="iv-refresh-days"
            type="number"
            min={1}
            max={90}
            className="iv-refresh-days-input"
            value={ivRefreshDays}
            onChange={(e) => setIvRefreshDays(e.target.value)}
            disabled={ivRefreshLoading}
          />
          <button
            type="button"
            className="iv-refresh-btn"
            onClick={() => void refreshIvCsv()}
            disabled={ivRefreshLoading}
          >
            {ivRefreshLoading ? t('forecast.ivRefreshing') : t('forecast.ivRefreshBtn')}
          </button>
          <label className="iv-refresh-check">
            <input
              type="checkbox"
              checked={ivRunChecksAfter}
              onChange={(e) => setIvRunChecksAfter(e.target.checked)}
              disabled={ivRefreshLoading}
            />
            {t('forecast.ivCheckAfter')}
            <strong>{t('forecast.ivCheckAfterStrong')}</strong>
            {t('forecast.ivCheckAfterEnd')}
          </label>
          <span className="iv-refresh-note">
            {t('forecast.ivCheckNote')} <code>externalId</code>
            {t('forecast.ivCheckNoteCode')}
          </span>
          <button
            type="button"
            className="iv-refresh-btn iv-refresh-btn--secondary"
            onClick={() => void scanTurbidityThreshold()}
            disabled={turbidityScanLoading || ivRefreshLoading}
            title={t('forecast.turbidityScanTitle')}
          >
            {turbidityScanLoading ? t('forecast.turbidityScanning') : t('forecast.turbidityScanBtn')}
          </button>
        </div>
        {turbidityScanErr && <div className="forecast-err">{turbidityScanErr}</div>}
        {turbidityScanResult && (
          <div className="iv-refresh-result">
            <span>
              {t('forecast.turbidityScanLine1')}
              <strong>{turbidityScanResult.stationsConsidered ?? '—'}</strong>
              {turbidityScanResult.skippedRegisteredNo63680InIv != null &&
                turbidityScanResult.skippedRegisteredNo63680InIv > 0 && (
                  <>
                    {t('forecast.turbidityScanSkippedReg')}
                    <strong>{turbidityScanResult.skippedRegisteredNo63680InIv}</strong>
                  </>
                )}
              {t('forecast.turbidityScanLine2')}
              <strong>{turbidityScanResult.alertsCreated ?? 0}</strong>
              {t('forecast.turbidityScanLine3')}
              {turbidityScanResult.skippedNoData ?? 0}
              {t('forecast.turbidityScanLine4')}
              {turbidityScanResult.skippedNoTrigger ?? 0}
              {t('forecast.turbidityScanLine5')}
              {turbidityScanResult.skippedDuplicate ?? 0}
            </span>
            {turbidityScanResult.summary != null && turbidityScanResult.summary.trim() !== '' && (
              <span className="iv-refresh-note">（{turbidityScanResult.summary}）</span>
            )}
          </div>
        )}
        {ivRefreshErr && <div className="forecast-err">{ivRefreshErr}</div>}
        {ivRefreshResult && (
          <div className="iv-refresh-result">
            <span>
              {t('forecast.ivWritten')}
              <strong>{ivRefreshResult.rows}</strong>
              {t('forecast.ivWrittenRows')}
              {ivRefreshResult.start}
              {t('forecast.ivWrittenTilde')}
              {ivRefreshResult.end}
              {t('forecast.ivCommaBeforeMode')}
              {ivRefreshResult.mode === 'overwrite' ? t('forecast.ivModeOverwrite') : t('forecast.ivModeWrite')}
              {locale === 'en' ? ')' : '）'}
            </span>
            {ivRefreshResult.incrementalRowsNew != null && (
              <span>
                {t('forecast.ivIncremental')}
                <strong>{ivRefreshResult.incrementalRowsNew}</strong>
                {t('forecast.ivIncrementalEnd')}
              </span>
            )}
            <code className="iv-refresh-path">{ivRefreshResult.out}</code>
          </div>
        )}
        <div className="forecast-station-pick">
          <label htmlFor="forecast-pick">{t('forecast.registeredPick')}</label>
          <select
            id="forecast-pick"
            value={forecastStationPick}
            onChange={(e) => {
              const v = e.target.value
              setForecastStationPick(v)
              if (v) {
                setForecastForm((p) => ({ ...p, siteNo: v }))
              }
            }}
          >
            <option value="">{t('forecast.manualSiteNo')}</option>
            {stations
              .filter((s) => s.externalId && String(s.externalId).trim() !== '')
              .map((s) => (
                <option key={s.stationId} value={String(s.externalId).trim()}>
                  {s.stationName || s.stationCode} ({s.externalId})
                </option>
              ))}
          </select>
        </div>
        <div className="forecast-param-pick">
          <span className="forecast-param-pick-label">{t('forecast.metricLabel')}</span>
          <label className="forecast-radio">
            <input
              type="radio"
              name="forecast-param"
              checked={forecastParam === '00060'}
              onChange={() => setForecastParam('00060')}
              disabled={forecastLoading}
            />
            {t('forecast.flow00060')}
          </label>
          <label className="forecast-radio">
            <input
              type="radio"
              name="forecast-param"
              checked={forecastParam === '63680'}
              onChange={() => setForecastParam('63680')}
              disabled={forecastLoading}
            />
            {t('forecast.turb63680')}
          </label>
        </div>
        <div className="forecast-grid">
          <input
            placeholder={t('forecast.phSiteNo')}
            value={forecastForm.siteNo}
            onChange={(e) => {
              setForecastStationPick('')
              setForecastForm((p) => ({ ...p, siteNo: e.target.value }))
            }}
          />
          <input
            placeholder={t('forecast.phHorizon')}
            value={forecastForm.horizonHours}
            onChange={(e) =>
              setForecastForm((p) => ({ ...p, horizonHours: e.target.value }))
            }
          />
          <input
            className="forecast-optional"
            placeholder={t('forecast.phIvPath')}
            value={forecastForm.ivCsvPath}
            onChange={(e) =>
              setForecastForm((p) => ({ ...p, ivCsvPath: e.target.value }))
            }
          />
          <button type="button" onClick={() => void submitForecast()} disabled={forecastLoading}>
            {forecastLoading ? t('forecast.forecasting') : t('forecast.generateForecast')}
          </button>
        </div>
        <div className="anomaly-from-iv-row anomaly-dual-row">
          <button
            type="button"
            className={`anomaly-from-iv-btn${siteParamAnomalyActiveCd === '00060' && siteParamAnomalyResult ? ' anomaly-from-iv-btn--active' : ''}`}
            onClick={() => void submitSiteParamAnomaly('00060')}
            disabled={!!siteParamAnomalyLoading || forecastLoading}
          >
            {siteParamAnomalyLoading === '00060' ? t('forecast.flowAnomalyRunning') : t('forecast.flowAnomalyBtn')}
          </button>
          <button
            type="button"
            className={`anomaly-from-iv-btn${siteParamAnomalyActiveCd === '63680' && siteParamAnomalyResult ? ' anomaly-from-iv-btn--active' : ''}`}
            onClick={() => void submitSiteParamAnomaly('63680')}
            disabled={!!siteParamAnomalyLoading || forecastLoading}
          >
            {siteParamAnomalyLoading === '63680' ? t('forecast.turbAnomalyRunning') : t('forecast.turbAnomalyBtn')}
          </button>
          <span className="anomaly-from-iv-note">
            {t('forecast.anomalyNoteBefore')}
            <code>site_no</code>
            {t('forecast.anomalyNoteAfter')}
            <code>iv_csv_path</code>
            {t('forecast.anomalyNoteEnd')}
          </span>
        </div>
        {forecastErr && <div className="forecast-err">{forecastErr}</div>}
        {siteParamAnomalyErr && <div className="forecast-err">{siteParamAnomalyErr}</div>}
        {siteParamAnomalyActiveCd != null && (
          <div className="forecast-result anomaly-result anomaly-result--single">
            {siteParamAnomalyLoading === siteParamAnomalyActiveCd && siteParamAnomalyResult == null ? (
              <p className="anomaly-result-loading">
                {siteParamAnomalyActiveCd === '00060'
                  ? t('forecast.anomalyLoadingFlow')
                  : t('forecast.anomalyLoadingTurb')}
              </p>
            ) : siteParamAnomalyResult != null ? (
              (() => {
                const cd = siteParamAnomalyActiveCd
                const r = siteParamAnomalyResult
                return (
                  <>
                    <div className="forecast-kv">
                      <span>
                        {cd === '00060' ? t('forecast.anomalyBanner00060') : t('forecast.anomalyBanner63680')}
                      </span>
                      <strong>{r.anomaly_available ? t('forecast.yes') : t('forecast.no')}</strong>
                    </div>
                    {!r.anomaly_available ? (
                      <div className="forecast-kv anomaly-impute-note">
                        <span>{t('forecast.note')}</span>
                        <span className="forecast-muted">{siteParamAnomalyReasonLabel(locale, r.reason)}</span>
                      </div>
                    ) : (
                      <>
                        <div className="forecast-kv">
                          <span>{t('forecast.sampleTime')}</span>
                          <span className="forecast-muted">{r.sample_timestamp ?? '—'}</span>
                        </div>
                        <div className="forecast-kv">
                          <span>{t('forecast.hoursUsed')}</span>
                          <strong>{r.samples_used ?? '—'}</strong>
                        </div>
                        <div className="forecast-kv">
                          <span>{t('forecast.isAnomaly')}</span>
                          <strong>{r.is_anomaly ? t('forecast.yes') : t('forecast.no')}</strong>
                        </div>
                        <div className="forecast-kv">
                          <span>{t('forecast.scoreThreshold')}</span>
                          <strong>
                            {r.anomaly_score ?? '—'} / {r.threshold ?? '—'}
                          </strong>
                        </div>
                        <div className="forecast-kv">
                          <span>{t('forecast.model')}</span>
                          <code>{r.model_version ?? '—'}</code>
                        </div>
                        <div className="forecast-kv">
                          <span>{t('forecast.alert')}</span>
                          <strong>
                            {r.alert_created
                              ? t('forecast.alertWritten')
                              : translate(locale, 'forecast.alertNotWrittenTpl').replace(
                                  '{{reason}}',
                                  siteParamAnomalyReasonLabel(locale, r.alert_reason)
                                )}
                          </strong>
                        </div>
                      </>
                    )}
                  </>
                )
              })()
            ) : null}
          </div>
        )}
        {forecastResult && (
          <div className="forecast-result">
            <div className="forecast-kv">
              <span>{t('forecast.available')}</span>
              <strong>{forecastResult.forecast_available ? t('forecast.yes') : t('forecast.no')}</strong>
            </div>
            {forecastResult.forecast_available ? (
              <>
                <div className="forecast-kv">
                  <span>{t('forecast.forecastValue')}</span>
                  <strong>{forecastResult.forecast_value ?? '—'}</strong>
                </div>
                <div className="forecast-kv">
                  <span>{t('forecast.model')}</span>
                  <code>{forecastResult.model_version ?? '—'}</code>
                </div>
                <div className="forecast-kv">
                  <span>{t('forecast.hoursUsed')}</span>
                  <strong>{forecastResult.data_points_used ?? '—'}</strong>
                </div>
                <div className="forecast-kv">
                  <span>{t('forecast.seriesEnd')}</span>
                  <span className="forecast-muted">{forecastResult.series_last_timestamp ?? '—'}</span>
                </div>
                <div className="forecast-kv">
                  <span>{t('forecast.predLevel')}</span>
                  <strong>{forecastResult.forecast_pollution_level ?? '—'}</strong>
                </div>
                <div className="forecast-kv">
                  <span>{t('forecast.alertOutcome')}</span>
                  <strong>
                    {forecastResult.forecast_alert_created
                      ? t('forecast.alertGenerated')
                      : translate(locale, 'forecast.alertNotGenTpl').replace(
                          '{{reason}}',
                          forecastAlertReasonLabel(locale, forecastResult.forecast_alert_reason)
                        )}
                  </strong>
                </div>
                {forecastTrend.length > 0 && (
                  <div className="forecast-trend-wrap">
                    <div className="forecast-trend-title">
                      {t('forecast.trendTitle')}
                      {forecastResult.horizon_hours}
                      {t('forecast.trendTitleEnd')}
                    </div>
                    <ResponsiveContainer width="100%" height={220}>
                      <LineChart data={forecastTrend}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="time" hide />
                        <YAxis />
                        <Tooltip />
                        <Legend />
                        <Line
                          type="monotone"
                          dataKey="actual"
                          stroke="#38bdf8"
                          dot={false}
                          name={t('forecast.chartHistory')}
                          connectNulls
                        />
                        <Line
                          type="monotone"
                          dataKey="predicted"
                          stroke="#fb923c"
                          strokeDasharray="6 4"
                          dot={false}
                          name={t('forecast.chartForecast')}
                          connectNulls
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </>
            ) : (
              <div className="forecast-kv anomaly-impute-note">
                <span>{t('forecast.reason')}</span>
                <span className="forecast-muted">{forecastReasonLabel(locale, forecastResult.reason)}</span>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="card analytics-trend-hint">
        <h3 className="analytics-trend-hint__title">{t('analytics.historicalTitle')}</h3>
        <p className="analytics-trend-hint__body">{t('analytics.trendSameAsDashboard')}</p>
        <p className="analytics-trend-hint__link">
          <Link to="/">{t('analytics.goDashboardForTrend')}</Link>
        </p>
      </section>

      <div className="card analytics-topn">
          <h3>{t('topN.title')}</h3>
          <p className="chart-caption">{t('topN.caption')}</p>
          <table>
            <thead>
              <tr>
                <th>{t('topN.rank')}</th>
                <th>{t('topN.station')}</th>
                <th>{t('topN.name')}</th>
                <th>{t('topN.totalAlerts')}</th>
                <th>{t('topN.open')}</th>
              </tr>
            </thead>
            <tbody>
              {stationAlertTop.map((it, idx) => (
                <tr key={it.station_id}>
                  <td>{idx + 1}</td>
                  <td>
                    <code>{it.station_code}</code>
                  </td>
                  <td>{it.station_name || '—'}</td>
                  <td>{it.alert_count}</td>
                  <td>{it.open_alert_count}</td>
                </tr>
              ))}
              {stationAlertTop.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    {t('topN.empty')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

      <section className="card" aria-labelledby="heading-latest-alerts-analytics">
        <h3 id="heading-latest-alerts-analytics">{t('alerts.latest')}</h3>
        <div className="alert-table-wrap">
          <table className="alert-table">
            <thead>
              <tr>
                <th>{t('alertTable.id')}</th>
                <th>{t('alertTable.station')}</th>
                <th>{t('alertTable.status')}</th>
                <th>{t('alertTable.severity')}</th>
                <th>{t('alertTable.rule')}</th>
                <th>{t('alertTable.param')}</th>
                <th>{t('alertTable.value')}</th>
                <th>{t('alertTable.threshold')}</th>
                <th>{t('alertTable.model')}</th>
                <th>{t('alertTable.summary')}</th>
                <th>{t('alertTable.time')}</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td>{alertStationLabel(a, stations)}</td>
                  <td>{a.status}</td>
                  <td>{a.severity}</td>
                  <td>{alertRuleLabel(locale, a.ruleCode)}</td>
                  <td>{paramCdLabel(locale, alertParameterCd(a))}</td>
                  <td>{alertObservedValue(a)}</td>
                  <td>{alertThresholdValue(a)}</td>
                  <td>{alertModelLabel(a)}</td>
                  <td className="alert-table__summary" title={a.title || undefined}>
                    {a.title}
                  </td>
                  <td className="alert-table__time">{formatShortDateTime(a.createdAt)}</td>
                </tr>
              ))}
              {alerts.length === 0 && (
                <tr>
                  <td colSpan={11} className="empty">
                    {t('alertTable.empty')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
            </>
          }
        />
        <Route
          path="/stations"
          element={
            <>
              <div className="stations-page-head">
                <h2 className="stations-page-title">{t('stations.waterQualityTitle')}</h2>
                <button
                  type="button"
                  className="btn-station-add"
                  onClick={() => navigate('/stations#add')}
                >
                  {t('stations.addStationCta')}
                </button>
              </div>
              <section className="station-form" id="station-form-anchor">
                <h3>{t('stations.pageTitle')}</h3>
                <p className="station-form-hint">{t('stations.hint')}</p>
                {editingStationCode && (
                  <p className="station-form-editing">
                    {t('stations.editing')}：<code>{editingStationCode}</code>
                    {t('stations.codeLocked')}
                    <button type="button" className="btn-text" onClick={cancelStationEdit}>
                      {t('stations.cancel')}
                    </button>
                  </p>
                )}
                <div className="form-grid">
                  {(
                    [
                      ['stationCode', '站点编码*'],
                      ['stationName', '站点名称'],
                      ['province', '省份'],
                      ['city', '城市'],
                      ['latitude', '纬度*'],
                      ['longitude', '经度*'],
                      ['externalId', 'USGS site_no(可选)'],
                    ] as const
                  ).map(([key, label]) => (
                    <input
                      key={key}
                      placeholder={label}
                      disabled={key === 'stationCode' && !!editingStationCode}
                      value={form[key]}
                      onChange={(e) =>
                        setForm((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                    />
                  ))}
                  <div className="station-form-actions">
                    <button type="button" onClick={() => void submitStation()}>
                      {editingStationCode ? t('stations.save') : t('stations.add')}
                    </button>
                    {editingStationCode && (
                      <button type="button" className="btn-secondary" onClick={cancelStationEdit}>
                        {t('stations.cancelEdit')}
                      </button>
                    )}
                  </div>
                </div>
                <div className="station-roster">
                  <h4>{t('stations.rosterDb')}</h4>
                  <p className="station-roster-api-hint">
                    {t('stations.rosterApi')} <code>GET /api/map/stations</code>；<code>GET /api/stations</code> ·{' '}
                    <a href="http://127.0.0.1:8080/swagger-ui.html" target="_blank" rel="noreferrer">
                      {t('stations.swagger')}
                    </a>
                  </p>
                  {stations.length === 0 ? (
                    <p className="station-roster-empty">{t('stations.empty')}</p>
                  ) : (
                    <div className="station-table-wrap">
                      <table className="station-table">
                        <thead>
                          <tr>
                            <th>{t('stations.colCode')}</th>
                            <th>{t('stations.colName')}</th>
                            <th>{t('stations.colLocation')}</th>
                            <th>{t('stations.colStatus')}</th>
                            <th>{t('stations.colAlerts')}</th>
                            <th>{t('stations.actions')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stations.map((s) => (
                            <tr key={s.stationId}>
                              <td>
                                <code className="station-code-chip">{s.stationCode}</code>
                              </td>
                              <td>{s.stationName || '—'}</td>
                              <td className="station-loc-cell">
                                {s.latitude.toFixed(4)}, {s.longitude.toFixed(4)}
                              </td>
                              <td>
                                <span className={statusPillClass(s.latestPollutionLevel)}>
                                  {s.latestPollutionLevel || '—'}
                                </span>
                              </td>
                              <td
                                className={
                                  s.openAlertCount > 0 ? 'station-alerts--hot' : 'station-alerts--none'
                                }
                              >
                                {s.openAlertCount > 0 ? s.openAlertCount : t('stations.alertsNone')}
                              </td>
                              <td className="station-table-actions">
                                <button
                                  type="button"
                                  className="btn-table btn-table-primary"
                                  onClick={() => loadStationForEdit(s)}
                                >
                                  {t('stations.viewDetails')}
                                </button>
                                <button
                                  type="button"
                                  className="btn-table btn-table-danger"
                                  onClick={() => void deleteStation(s.stationCode)}
                                >
                                  {t('stations.delete')}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <h4>{t('stations.demoIvTitle')}</h4>
                  <p className="station-roster-muted">{t('stations.demoIvHint')}</p>
                  <div className="station-table-wrap">
                    <table className="station-table station-table--compact">
                      <thead>
                        <tr>
                          <th>USGS site_no</th>
                          <th>名称</th>
                        </tr>
                      </thead>
                      <tbody>
                        {PUGET_DEMO_SITES.map((d) => (
                          <tr key={d.externalId}>
                            <td>
                              <code>{d.externalId}</code>
                            </td>
                            <td>{d.name}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            </>
          }
        />
      </Routes>
    </main>
  )
}

export default App
