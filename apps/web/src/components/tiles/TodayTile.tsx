import type { Dashboard, WeatherDay } from '../../dashboard'
import { Tile, TileEmpty } from './Tile'

/** Tile 1 — Today (DESIGN §3.1): date, weather glyph strip (home/office),
 * briefing, Japan countdown chip while active. The coach's face — clay
 * left-border. The briefing composes from Phase 6; until then the tile says
 * so quietly (COACH §5 voice). */

function WeatherGlyph({ code }: { code: number }) {
  // WMO weather codes -> one small woodblock-flat glyph (currentColor).
  const cls = 'h-4 w-4'
  if (code <= 1) {
    return (
      <svg viewBox="0 0 20 20" aria-hidden className={cls}>
        <circle cx="10" cy="10" r="4" fill="currentColor" />
        <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <line x1="10" y1="2" x2="10" y2="4" />
          <line x1="10" y1="16" x2="10" y2="18" />
          <line x1="2" y1="10" x2="4" y2="10" />
          <line x1="16" y1="10" x2="18" y2="10" />
        </g>
      </svg>
    )
  }
  if (code <= 3 || code === 45 || code === 48) {
    return (
      <svg viewBox="0 0 20 20" aria-hidden className={cls}>
        <path
          d="M5.5 14a3.5 3.5 0 0 1 .6-6.95A4.5 4.5 0 0 1 14.7 8.6 3 3 0 0 1 14 14.5Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinejoin="round"
        />
      </svg>
    )
  }
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) {
    return (
      <svg viewBox="0 0 20 20" aria-hidden className={cls}>
        <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
          <line x1="10" y1="4" x2="10" y2="16" />
          <line x1="4.8" y1="7" x2="15.2" y2="13" />
          <line x1="15.2" y1="7" x2="4.8" y2="13" />
        </g>
      </svg>
    )
  }
  if (code >= 95) {
    return (
      <svg viewBox="0 0 20 20" aria-hidden className={cls}>
        <path d="M11 3 5.5 11.5H9L8 17l6.5-8.5H11Z" fill="currentColor" />
      </svg>
    )
  }
  // drizzle/rain/showers
  return (
    <svg viewBox="0 0 20 20" aria-hidden className={cls}>
      <path
        d="M5.5 11a3.5 3.5 0 0 1 .6-6.95A4.5 4.5 0 0 1 14.7 5.6 3 3 0 0 1 14 11.5Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
      <g stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
        <line x1="7" y1="13.5" x2="6.2" y2="16" />
        <line x1="10.5" y1="13.5" x2="9.7" y2="16" />
        <line x1="14" y1="13.5" x2="13.2" y2="16" />
      </g>
    </svg>
  )
}

function WeatherChip({ place, day }: { place: string; day: WeatherDay }) {
  const summary = `${place}: high ${Math.round(day.temp_max)}°, low ${Math.round(day.temp_min)}°, ${day.precip_prob}% chance of rain`
  return (
    <span
      role="img"
      aria-label={summary}
      title={summary}
      className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper px-2.5 py-1 text-xs text-ink-mid"
    >
      <span className="text-sky" aria-hidden>
        <WeatherGlyph code={day.weathercode} />
      </span>
      <span className="font-medium">{place}</span>
      <span className="font-mono text-[11px]">
        {Math.round(day.temp_max)}° / {Math.round(day.temp_min)}°
      </span>
      {day.precip_prob >= 30 && <span className="font-mono text-[11px] text-sky">{day.precip_prob}%</span>}
    </span>
  )
}

export function TodayTile({ data }: { data: Dashboard }) {
  const dateLabel = new Date(`${data.date}T12:00:00`).toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
  const weather = data.weather

  return (
    <Tile title="Today" accent ariaLabel={`Today, ${dateLabel}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-serif text-lg text-ink">{dateLabel}</span>
        {data.japan && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-clay/10 px-2.5 py-1 text-xs font-medium text-clay">
            <span aria-hidden>⛩</span>
            {data.japan.days_to_go === 0 ? 'Japan — it’s on' : `Japan in ${data.japan.days_to_go} days`}
          </span>
        )}
      </div>

      {weather ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {weather.home && <WeatherChip place="Home" day={weather.home} />}
          {weather.office && <WeatherChip place="Office" day={weather.office} />}
        </div>
      ) : (
        <p className="mt-3 text-xs text-ink-soft">No forecast on hand yet.</p>
      )}

      {data.briefing ? (
        <p className="mt-3 whitespace-pre-wrap font-serif text-sm leading-relaxed text-ink">{data.briefing}</p>
      ) : (
        <TileEmpty>The coach starts composing your morning briefing in a later phase.</TileEmpty>
      )}
    </Tile>
  )
}
