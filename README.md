# Darkbloom for Home Assistant

A Home Assistant integration for [Darkbloom](https://darkbloom.dev) provider
accounts. Tracks your earnings as a device with windowed earning-rate sensors.

One config entry per Darkbloom account. A coordinator polls
`/api/me/earnings` every 5 minutes (one request per poll), keeps a rolling
local cache (26 hours of rows + 8 days of hourly buckets, persisted across
restarts), and computes earning rates over rolling windows.

## Why the cache matters

Darkbloom's ledger API returns at most 1000 rows per page. At typical job
rates that page spans only a few hours, so a 24h window cannot be computed
exactly from the API alone. This integration accumulates rows locally, so the
12h/24h windows become exact after the integration has run for a day. Until
then, those windows are extrapolated from the visible data and marked with
`exact: false` in the sensor attributes.

## Entities

Device: **Darkbloom Provider Network**

| Entity | Unit | Description |
|---|---|---|
| `sensor.darkbloom_rate_1h` … `_24h` | `$/h` | Earning rate over the last 1/2/3/4/6/12/24 hours. Attributes: `earned_usd`, `work_usd`, `rewards_usd`, `jobs`, `exact`, `sources` (per-model breakdown), `data_as_of`. |
| `sensor.darkbloom_withdrawable_balance` | `USD` | Current withdrawable provider balance. |
| `sensor.darkbloom_lifetime_earnings` | `USD` | Lifetime earnings (total increasing). |
| `sensor.darkbloom_last_job` | timestamp | Most recent served job (freshness check). |

`base_reward` ledger rows are counted as rewards (excluded from `work_usd`),
not as jobs.

## Installation

### HACS (custom repository)

1. HACS → ⋮ (top right) → **Custom repositories**
2. Paste `https://github.com/anoopr/darkbloom-ha`, category **Integration**
3. Install **Darkbloom** from HACS, then restart Home Assistant

### Configuration

1. Settings → Devices & Services → **Add Integration** → **Darkbloom**
2. Paste your API key (`sk-db-...`)

The key is validated against the API and stored in HA's entry storage (not in
YAML). One entry per account; reinstalling keeps the cache, so window history
survives.

## Dashboard suggestions

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Earning rate
    entities:
      - sensor.darkbloom_rate_1h
      - sensor.darkbloom_rate_2h
      - sensor.darkbloom_rate_3h
      - sensor.darkbloom_rate_4h
      - sensor.darkbloom_rate_6h
      - sensor.darkbloom_rate_12h
      - sensor.darkbloom_rate_24h
  - type: statistic
    entity: sensor.darkbloom_rate_24h
    stat_type: mean
    period:
      rolling_window:
        duration:
          days: 7
  - type: history-graph
    title: Rate, past week
    hours_to_show: 168
    entities:
      - sensor.darkbloom_rate_24h
      - sensor.darkbloom_rate_12h
      - sensor.darkbloom_rate_1h
```

### Alert when the rate drops

```yaml
automation:
  - alias: Darkbloom rate low
    trigger:
      - platform: numeric_state
        entity_id: sensor.darkbloom_rate_1h
        below: 0.10
        for: "01:00:00"
    action:
      - service: notify.persistent_notification
        data:
          title: Darkbloom rate low
          message: "1h earning rate below $0.10/h for an hour."
```

## Notes

- API load: 1 request per 5 minutes (288/day), well within the console's
  rate limits; transient 503/429 responses just skip a poll and keep last
  values.
- The coordinator only ever reads. Your API key stays on your Home Assistant
  instance.
- Repository is private by design; HACS works with private repos as long as
  the GitHub account you logged into HACS with has access.

## License

MIT — see [LICENSE](LICENSE).
