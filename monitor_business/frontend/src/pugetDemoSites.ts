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
