import type { ReactNode } from 'react'

/** Tiny renderer for the memory engine's simple markdown (docs/MEMORY.md §3,
 * §5): summary_md and digest content_md only ever use headings (#/##/###),
 * plain lines, `- ` bullets, `---` rules, *italics* and **bold**. Rendered as
 * React nodes (never innerHTML). Anything unrecognised falls back to a plain
 * paragraph — honest, never blank. */

function inline(text: string, keyBase: string): ReactNode[] {
  // Pairs only — a lone `*` (or the ★☆ star glyphs) stays literal.
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={`${keyBase}-${i}`}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={`${keyBase}-${i}`} className="font-serif">
          {part.slice(1, -1)}
        </em>
      )
    }
    return part
  })
}

export function Markdown({ text, className = '' }: { text: string; className?: string }) {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let bullets: string[] = []

  const flushBullets = (key: string) => {
    if (bullets.length === 0) return
    const items = bullets
    bullets = []
    blocks.push(
      <ul key={key} className="space-y-1 text-sm leading-relaxed text-ink">
        {items.map((b, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-ink-soft" aria-hidden>
              ·
            </span>
            <span>{inline(b, `${key}-${i}`)}</span>
          </li>
        ))}
      </ul>,
    )
  }

  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    const key = `b${i}`
    if (line.startsWith('- ')) {
      bullets.push(line.slice(2))
      return
    }
    flushBullets(`ul-${i}`)
    if (line === '') return
    if (line === '---') {
      blocks.push(<hr key={key} className="border-line" />)
    } else if (line.startsWith('### ')) {
      blocks.push(
        <p key={key} className="font-display text-xs font-medium tracking-[0.02em] text-ink-mid">
          {inline(line.slice(4), key)}
        </p>,
      )
    } else if (line.startsWith('## ')) {
      blocks.push(
        <p key={key} className="font-display text-sm font-medium text-ink">
          {inline(line.slice(3), key)}
        </p>,
      )
    } else if (line.startsWith('# ')) {
      blocks.push(
        <p key={key} className="font-display text-base font-medium text-ink">
          {inline(line.slice(2), key)}
        </p>,
      )
    } else {
      blocks.push(
        <p key={key} className="font-serif text-sm leading-relaxed text-ink">
          {inline(line, key)}
        </p>,
      )
    }
  })
  flushBullets('ul-end')

  return <div className={`space-y-2 ${className}`}>{blocks}</div>
}

/** summary_md always opens with its own `## <date>` heading; day cards show
 * the date in the card header instead, so strip the duplicate. */
export function stripLeadingHeading(text: string): string {
  const lines = text.split('\n')
  if (lines[0]?.startsWith('#')) {
    let i = 1
    while (i < lines.length && lines[i].trim() === '') i++
    return lines.slice(i).join('\n')
  }
  return text
}
