/* The two orders the clip grid can be shown in, and the rules for applying them.
   Everything reads from the `scores` the detector writes (see backend/app/tasks/detect.py):
   `final` is the blended overall score, `hook` is how strong the opening is. The other
   ratings exist on the moment but are deliberately not offered here. */

// One entry per button. The "Sorted by" label beside the toggle plus the pressed
// button name the active order, so no separate spelled-out line is needed.
export const MOMENT_SORTS = [
  { key: 'final', label: 'Overall score' },
  { key: 'hook', label: 'Hook' },
]

export const DEFAULT_MOMENT_SORT = 'final'

// A moment missing the rating we're sorting on drops below every rated one instead of
// landing wherever a 0 would put it. Real scores are 0..1, so -1 is always last.
function scoreValue(moment, key) {
  const value = Number(moment?.scores?.[key])
  return Number.isFinite(value) ? value : -1
}

/**
 * A new array of moments ordered by one rating, best first.
 *
 * Ties break on the overall score, then on where the clip sits in the video. Without that
 * two clips with the same hook score could swap places on every poll while the grid is
 * still filling in, and the whole thing would look like it was shuffling on its own.
 */
export function sortMoments(moments, key) {
  const list = Array.isArray(moments) ? moments : []

  return [...list].sort(
    (a, b) =>
      scoreValue(b, key) - scoreValue(a, key) ||
      scoreValue(b, 'final') - scoreValue(a, 'final') ||
      Number(a?.start_sec || 0) - Number(b?.start_sec || 0),
  )
}

/**
 * The raw 0..1 score a tile's badge should show for the active order. Falls back to the
 * overall score when the sorted-on rating is missing, so a badge never comes out blank on
 * an older clip that predates the rating.
 */
export function getMomentScore(moment, key) {
  const value = Number(moment?.scores?.[key])
  if (Number.isFinite(value)) {
    return value
  }
  return Number(moment?.scores?.final)
}
