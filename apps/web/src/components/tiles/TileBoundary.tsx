import { Component, type ReactNode } from 'react'

/** DESIGN §3's standing promise: tiles degrade independently and the bridge
 * never blanks because one source misbehaves. A render error inside one tile
 * (a payload shape the tile didn't expect, say) is contained to that tile
 * instead of unmounting the whole app. */
export class TileBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="rounded-lg border border-line bg-paper-mid px-4 py-3 text-xs text-ink-soft">
          This tile couldn’t draw — the rest of the bridge stands.
        </div>
      )
    }
    return this.props.children
  }
}
