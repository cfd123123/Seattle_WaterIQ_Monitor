/**
 * Demo coordinates (approx WGS84) aligned with `site_no` in ai_service/config/usgs_puget_default_sites.json.
 * Shown on the map when no registered stations exist; demo markers for the same externalId hide after registration.
 */
export type PugetDemoSite = {
  externalId: string
  name: string
  latitude: number
  longitude: number
}

/** Static fallback when GET /api/demo/puget-sites is unavailable; also used to fill missing map coordinates by site_no. */
export const PUGET_DEMO_SITES: PugetDemoSite[] = [
  {
    externalId: '12117000',
    name: 'Snoqualmie River near Snoqualmie, WA',
    latitude: 47.528,
    longitude: -121.825,
  },
  {
    externalId: '12141300',
    name: 'Green River below Howard Hanson Dam at Palmer, WA',
    latitude: 47.276,
    longitude: -121.616,
  },
  {
    externalId: '12145500',
    name: 'Green River near Auburn, WA',
    latitude: 47.298,
    longitude: -122.234,
  },
  {
    externalId: '12175500',
    name: 'Raging River near Fall City, WA',
    latitude: 47.567,
    longitude: -121.908,
  },
  {
    externalId: '12147600',
    name: 'Green River at Duwamish Gardens, WA',
    latitude: 47.522,
    longitude: -122.305,
  },
]

type ApiPugetRow = {
  site_no?: string
  name?: string
  latitude?: number
  longitude?: number
}

/**
 * Builds demo-site rows from AI config JSON. Uses {@link PUGET_DEMO_SITES} for coordinates when the API omits lat/lon.
 */
export function mergePugetSitesFromApi(sites: unknown[] | undefined, fallback: PugetDemoSite[]): PugetDemoSite[] {
  if (!sites || !Array.isArray(sites) || sites.length === 0) {
    return fallback
  }
  const out: PugetDemoSite[] = []
  for (const row of sites) {
    if (!row || typeof row !== 'object') continue
    const r = row as ApiPugetRow
    const id = String(r.site_no ?? '').trim()
    if (!id) continue
    const fb = fallback.find((p) => p.externalId === id)
    const lat = typeof r.latitude === 'number' ? r.latitude : fb?.latitude ?? 47.52
    const lng = typeof r.longitude === 'number' ? r.longitude : fb?.longitude ?? -122.2
    const name = typeof r.name === 'string' && r.name.trim() !== '' ? r.name.trim() : fb?.name ?? id
    out.push({ externalId: id, name, latitude: lat, longitude: lng })
  }
  return out.length > 0 ? out : fallback
}
