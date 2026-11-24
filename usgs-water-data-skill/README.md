# usgs-water-data — an Agent Skill for USGS water data

Lets Claude find USGS stream gages and pull their real-time sensor data (streamflow, gage height,
water temperature, turbidity, dissolved oxygen, pH, conductance) from the public
[NWIS web services](https://waterservices.usgs.gov/). No API key, no Python dependencies.

Ask things like:

- "What's the Cedar River near Landsburg flowing at right now?"
- "Find USGS sites measuring turbidity around Seattle."
- "Download the last 30 days of discharge for site 12117500 as CSV and plot it."

## Install

**Claude Code (plugin marketplace)**

```
/plugin marketplace add <your-github-user>/usgs-water-data-skill
/plugin install usgs-water-data@usgs-water-data
```

**Claude Code (manual)**: copy `skills/usgs-water-data/` into `~/.claude/skills/` (all projects)
or `<project>/.claude/skills/` (one project).

**claude.ai**: zip the `skills/usgs-water-data/` folder and upload it under
Settings → Capabilities → Skills. Network access to `waterservices.usgs.gov` must be allowed
in your code-execution settings.

## Layout

```
.claude-plugin/
  plugin.json          # plugin metadata
  marketplace.json     # lets this repo act as its own marketplace
skills/usgs-water-data/
  SKILL.md             # instructions Claude loads when the skill triggers
  scripts/find_sites.py
  scripts/fetch_iv.py
  references/parameter_codes.md
```

## Disclaimer

Data is provisional USGS real-time data. Not an official forecast or flood warning.

## License

MIT
