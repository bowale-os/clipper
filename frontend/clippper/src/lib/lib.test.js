import { describe, expect, it } from 'vitest'

import { ApiError } from '../services/api'
import { getReadableError } from './errors'
import {
  formatBytes,
  formatClock,
  formatDate,
  getFileExtension,
  getVideoId,
  parseTimecode,
  toScore,
} from './format'
import { DEFAULT_MOMENT_SORT, getMomentScore, MOMENT_SORTS, sortMoments } from './moments'
import { countByStatus, flattenVideos, VIDEO_STATUSES } from './videos'

describe('formatBytes', () => {
  it.each([
    [0, 'Unknown size'],
    [undefined, 'Unknown size'],
    [500, '500 B'],
    [1024, '1.0 KB'],
    [1536, '1.5 KB'],
    [10 * 1024, '10 KB'],
    [5 * 1024 ** 2, '5.0 MB'],
    [2.5 * 1024 ** 3, '2.5 GB'],
    [5 * 1024 ** 4, '5120 GB'],
  ])('%s -> %s', (input, expected) => {
    expect(formatBytes(input)).toBe(expected)
  })
})

describe('formatClock', () => {
  it.each([
    [0, undefined, '00:00'],
    [59, undefined, '00:59'],
    [75, undefined, '01:15'],
    [3599, undefined, '59:59'],
    [3600, undefined, '01:00:00'],
    [3725.9, undefined, '01:02:05'],
    [75, { includeHours: true }, '00:01:15'],
    [-5, undefined, '00:00'],
    [Number.NaN, undefined, '00:00'],
    ['abc', undefined, '00:00'],
    [null, undefined, '00:00'],
    ['90', undefined, '01:30'],
  ])('%s %j -> %s', (input, options, expected) => {
    expect(formatClock(input, options)).toBe(expected)
  })
})

describe('parseTimecode', () => {
  it.each([
    ['90', 90],
    ['1:30', 90],
    ['01:02:30', 3750],
    ['0:05', 5],
    ['1.5', 1.5],
    ['  2:00  ', 120],
    [90, 90],
  ])('reads %j as %s seconds', (input, expected) => {
    expect(parseTimecode(input)).toBe(expected)
  })

  it.each(['', '   ', null, undefined, 'abc', '1:2:3:4', '1::2', ':30', '1:', '-5', '1e3', '1,5'])(
    'rejects %j',
    (input) => {
      expect(parseTimecode(input)).toBeNaN()
    },
  )

  it('round-trips with formatClock', () => {
    for (const seconds of [0, 7, 65, 3600, 5000]) {
      expect(parseTimecode(formatClock(seconds, { includeHours: true }))).toBe(seconds)
    }
  })
})

describe('formatDate', () => {
  it('handles missing and invalid input', () => {
    expect(formatDate(null)).toBe('No date')
    expect(formatDate('')).toBe('No date')
    expect(formatDate('not a date')).toBe('not a date')
  })

  it('formats a real date with its year', () => {
    expect(formatDate('2026-03-15T12:00:00Z')).toMatch(/2026/)
  })
})

describe('toScore', () => {
  it.each([
    [0.876, 88],
    [0, 0],
    [1, 100],
    ['0.5', 50],
  ])('%s -> %s', (input, expected) => {
    expect(toScore(input)).toBe(expected)
  })

  it.each([undefined, 'x', Number.NaN, Infinity])('is null for %s', (input) => {
    expect(toScore(input)).toBeNull()
  })

  it('treats null as zero (a missing rating reads as 0)', () => {
    expect(toScore(null)).toBe(0)
  })
})

describe('getVideoId / getFileExtension', () => {
  it('prefers _id, then id, then video_id', () => {
    expect(getVideoId({ _id: 'a', id: 'b', video_id: 'c' })).toBe('a')
    expect(getVideoId({ id: 'b', video_id: 'c' })).toBe('b')
    expect(getVideoId({ video_id: 'c' })).toBe('c')
    expect(getVideoId({})).toBe('')
    expect(getVideoId(null)).toBe('')
  })

  it('reads short extensions and falls back to "video"', () => {
    expect(getFileExtension('talk.mp4')).toBe('mp4')
    expect(getFileExtension('archive.tar.gz')).toBe('gz')
    expect(getFileExtension('noextensionatall')).toBe('video')
    expect(getFileExtension(undefined)).toBe('video')
  })
})

describe('sortMoments', () => {
  const moments = [
    { id: 'a', scores: { final: 0.5, hook: 0.9 }, start_sec: 30 },
    { id: 'b', scores: { final: 0.8, hook: 0.2 }, start_sec: 10 },
    { id: 'c', scores: { final: 0.8, hook: 0.2 }, start_sec: 5 },
    { id: 'd', scores: {}, start_sec: 1 },
  ]

  it('orders by the chosen rating, best first', () => {
    expect(sortMoments(moments, 'final').map((m) => m.id)).toEqual(['c', 'b', 'a', 'd'])
    expect(sortMoments(moments, 'hook').map((m) => m.id)).toEqual(['a', 'c', 'b', 'd'])
  })

  it('breaks ties by overall score and then by position so the grid never shuffles', () => {
    const tied = [
      { id: 'late', scores: { final: 0.7, hook: 0.5 }, start_sec: 90 },
      { id: 'early', scores: { final: 0.7, hook: 0.5 }, start_sec: 3 },
    ]
    expect(sortMoments(tied, 'hook').map((m) => m.id)).toEqual(['early', 'late'])
  })

  it('puts unrated moments last and does not mutate its input', () => {
    const copy = JSON.stringify(moments)
    sortMoments(moments, 'hook')
    expect(JSON.stringify(moments)).toBe(copy)
    expect(sortMoments(moments, 'hook').at(-1).id).toBe('d')
  })

  it('tolerates bad input', () => {
    expect(sortMoments(null, 'final')).toEqual([])
    expect(sortMoments(undefined, 'final')).toEqual([])
    expect(sortMoments([null, { scores: { final: 1 } }], 'final')).toHaveLength(2)
  })

  it('offers overall score first and hook second', () => {
    expect(MOMENT_SORTS.map((s) => s.key)).toEqual(['final', 'hook'])
    expect(DEFAULT_MOMENT_SORT).toBe('final')
  })
})

describe('getMomentScore', () => {
  it('returns the requested rating', () => {
    expect(getMomentScore({ scores: { final: 0.4, hook: 0.9 } }, 'hook')).toBe(0.9)
  })

  it('falls back to the overall score when the rating is missing', () => {
    expect(getMomentScore({ scores: { final: 0.4 } }, 'hook')).toBe(0.4)
  })

  it('is NaN when there is nothing to show', () => {
    expect(getMomentScore({}, 'hook')).toBeNaN()
    expect(getMomentScore(null, 'final')).toBeNaN()
  })
})

describe('flattenVideos / countByStatus', () => {
  it('flattens the grouped response newest first', () => {
    const data = {
      ready_videos: [{ video_id: 'old', status: 'ready', created_at: '2026-01-01T00:00:00Z' }],
      processing_videos: [{ video_id: 'new', status: 'processing', created_at: '2026-02-01T00:00:00Z' }],
      error_videos: [{ video_id: 'mid', status: 'error', created_at: '2026-01-15T00:00:00Z' }],
    }
    expect(flattenVideos(data).map((v) => v.video_id)).toEqual(['new', 'mid', 'old'])
  })

  it('copes with missing groups, nulls and undated rows', () => {
    expect(flattenVideos(null)).toEqual([])
    expect(flattenVideos({})).toEqual([])
    expect(flattenVideos({ ready_videos: 'nope' })).toEqual([])
    expect(flattenVideos({ ready_videos: [{ video_id: 'x' }] })).toHaveLength(1)
  })

  it('knows every status the backend can send', () => {
    expect(VIDEO_STATUSES).toEqual(['ready', 'processing', 'uploaded', 'uploading', 'error'])
  })

  it('counts by status', () => {
    expect(countByStatus([{ status: 'ready' }, { status: 'ready' }, { status: 'error' }, null])).toEqual({
      ready: 2,
      error: 1,
      undefined: 1,
    })
    expect(countByStatus([])).toEqual({})
  })
})

describe('getReadableError', () => {
  it('asks the user to slow down on 429, with the wait', () => {
    const wait = (sec) => getReadableError(new ApiError('x', { status: 429, retryAfterSec: sec }))
    expect(wait(30)).toMatch(/30 seconds/)
    expect(wait(1)).toMatch(/1 second\./)
    expect(wait(0.2)).toMatch(/a moment/)
    expect(wait(undefined)).toMatch(/a moment/)
    expect(wait(120)).toMatch(/2 minutes/)
    expect(wait(60)).toMatch(/1 minute\./)
  })

  it('hides server internals on 5xx', () => {
    const message = getReadableError(new ApiError('Traceback: secret', { status: 503 }))
    expect(message).not.toMatch(/secret/)
    expect(message).toMatch(/our end/)
  })

  it('shows the API message for client errors, with a fallback', () => {
    expect(getReadableError(new ApiError('Video not found', { status: 404 }))).toBe('Video not found')
    expect(getReadableError(new ApiError('', { status: 400 }), 'Fallback')).toBe('Fallback')
  })

  it('handles plain errors and unknown values', () => {
    expect(getReadableError(new Error('boom'))).toBe('boom')
    expect(getReadableError('weird')).toBe('Something went wrong.')
    expect(getReadableError(null, 'Custom')).toBe('Custom')
  })
})
