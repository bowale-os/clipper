import { MOMENT_SORTS } from '../lib/moments'

/**
 * The order the clips grid is shown in: overall score, or hook. A plain two-way toggle
 * over the grid, using the same segmented control as the shape and captions pickers. The
 * line naming the active order lives in Studio, next to where this sits.
 */
function MomentSort({ value, onChange }) {
  return (
    <div className="sort-row">
      <span className="sort-label">Sort by</span>
      <div className="segmented" role="group" aria-label="Sort clips">
        {MOMENT_SORTS.map((sort) => (
          <button
            aria-pressed={value === sort.key}
            key={sort.key}
            onClick={() => onChange(sort.key)}
            type="button"
          >
            {sort.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export default MomentSort
