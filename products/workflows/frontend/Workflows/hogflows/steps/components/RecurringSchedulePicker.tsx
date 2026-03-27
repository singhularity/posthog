import { useMemo, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    LemonButton,
    LemonCalendarSelectInput,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTag,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import {
    buildSummary,
    computePreviewOccurrences,
    DEFAULT_STATE,
    FREQUENCY_OPTIONS,
    getNthWeekdayOfMonth,
    NTH_LABELS,
    parseRRuleToState,
    stateToRRule,
    WEEKDAY_FULL_LABELS,
    WEEKDAY_PILL_LABELS,
} from './rrule-helpers'
import type { ScheduleState } from './rrule-helpers'

type ScheduleConfig = {
    rrule: string
    starts_at: string
    timezone?: string
}

interface RecurringSchedulePickerProps {
    schedule?: ScheduleConfig | null
    onChange: (schedule: ScheduleConfig | null) => void
}

const VISIBLE_HEAD = 4
const VISIBLE_TAIL = 1

function OccurrencesList({ occurrences, isFinite }: { occurrences: Date[]; isFinite: boolean }): JSX.Element {
    const total = occurrences.length
    const needsCollapse = isFinite && total > VISIBLE_HEAD + VISIBLE_TAIL + 1
    const lastIndex = total - 1

    const renderRow = (date: Date, i: number): JSX.Element => {
        const isFirst = i === 0
        const isLast = isFinite && i === lastIndex

        return (
            <div key={i} className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                    <span
                        className={`w-2 h-2 rounded-full shrink-0 ${
                            isFirst ? 'bg-warning' : isLast ? 'bg-danger' : 'bg-border'
                        }`}
                    />
                    <span className={isFirst || isLast ? 'font-semibold' : 'text-muted'}>
                        {dayjs(date).utc().format('dddd, MMMM D YYYY · h:mm A')}
                    </span>
                </div>
                {isFirst && (
                    <LemonTag type="warning" size="small">
                        next
                    </LemonTag>
                )}
                {isLast && !isFirst && (
                    <LemonTag type="danger" size="small">
                        last
                    </LemonTag>
                )}
            </div>
        )
    }

    if (needsCollapse) {
        const head = occurrences.slice(0, VISIBLE_HEAD)
        const tail = occurrences.slice(-VISIBLE_TAIL)
        const hiddenCount = total - VISIBLE_HEAD - VISIBLE_TAIL

        return (
            <>
                {head.map((date, i) => renderRow(date, i))}
                <div className="text-xs text-muted italic pl-4">
                    ...{hiddenCount} more occurrence{hiddenCount > 1 ? 's' : ''}...
                </div>
                {tail.map((date, i) => renderRow(date, total - VISIBLE_TAIL + i))}
            </>
        )
    }

    return (
        <>
            {occurrences.map((date, i) => renderRow(date, i))}
            {!isFinite && <div className="text-xs text-muted italic pl-4">...continues indefinitely</div>}
        </>
    )
}

export function RecurringSchedulePicker({ schedule, onChange }: RecurringSchedulePickerProps): JSX.Element {
    // A schedule with COUNT=1 is a one-time run, not a recurring schedule
    const isOneTime = schedule?.rrule === 'FREQ=DAILY;COUNT=1'
    const isRepeating = !!schedule && !isOneTime
    const [state, setState] = useState<ScheduleState>(() =>
        schedule && !isOneTime ? parseRRuleToState(schedule.rrule) : { ...DEFAULT_STATE }
    )

    // Keep start date in local state so it persists when toggling repeat off
    const [localStartsAt, setLocalStartsAt] = useState<string | null>(schedule?.starts_at || null)
    const [localTimezone] = useState<string>(schedule?.timezone || dayjs.tz.guess())

    const startsAt = schedule?.starts_at || localStartsAt
    const timezone = schedule?.timezone || localTimezone

    const emitChange = (newState: ScheduleState, newStartsAt: string | null, newTimezone: string): void => {
        if (!newStartsAt) {
            return
        }
        const rrule = stateToRRule(newState, newStartsAt)
        onChange({ rrule, starts_at: newStartsAt, timezone: newTimezone })
    }

    const previewOccurrences = useMemo(() => {
        if (!isRepeating || !startsAt) {
            return []
        }
        return computePreviewOccurrences(state, startsAt)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        isRepeating,
        startsAt,
        state.frequency,
        state.interval,
        state.weekdays,
        state.monthlyMode,
        state.endType,
        state.endDate,
        state.endCount,
    ])

    const summary = isRepeating ? buildSummary(state, startsAt) : null

    const monthlyDayLabel = startsAt ? `Day ${dayjs(startsAt).date()}` : 'Day N'
    const monthlyNthLabel = startsAt
        ? (() => {
              const { n, weekday } = getNthWeekdayOfMonth(dayjs(startsAt))
              return `${NTH_LABELS[n - 1]} ${WEEKDAY_FULL_LABELS[weekday]}`
          })()
        : 'Nth weekday'

    return (
        <div className="flex flex-col gap-3 w-full">
            <div className="flex items-center gap-2">
                <div className="flex-1 min-w-0">
                    <LemonCalendarSelectInput
                        buttonProps={{ fullWidth: true }}
                        clearable
                        value={startsAt ? dayjs(startsAt) : null}
                        onChange={(date) => {
                            const newStartsAt = date ? date.toISOString() : null
                            setLocalStartsAt(newStartsAt)
                            if (newStartsAt) {
                                if (isRepeating) {
                                    emitChange(state, newStartsAt, timezone)
                                } else {
                                    // One-time schedule: emit COUNT=1
                                    onChange({
                                        rrule: 'FREQ=DAILY;COUNT=1',
                                        starts_at: newStartsAt,
                                        timezone,
                                    })
                                }
                            } else {
                                onChange(null)
                            }
                        }}
                        granularity="minute"
                        selectionPeriod="upcoming"
                        showTimeToggle={false}
                    />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <span className="text-muted text-sm">Repeat</span>
                    <LemonSwitch
                        checked={isRepeating}
                        onChange={(checked) => {
                            const startDate = localStartsAt || startsAt || new Date().toISOString()
                            setLocalStartsAt(startDate)
                            if (checked) {
                                emitChange(state, startDate, timezone)
                            } else if (startDate) {
                                // Downgrade to one-time schedule
                                onChange({
                                    rrule: 'FREQ=DAILY;COUNT=1',
                                    starts_at: startDate,
                                    timezone,
                                })
                            }
                        }}
                    />
                </div>
            </div>
            {startsAt && (
                <div className="text-xs text-muted -mt-1">
                    Timezone: {dayjs.tz.guess()} · Scheduled for: {dayjs(startsAt).format('MMMM D, YYYY [at] h:mm A')}
                </div>
            )}

            {isRepeating && (
                <>
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-muted">Every</span>
                        <LemonInput
                            type="number"
                            min={1}
                            max={365}
                            size="small"
                            value={state.interval}
                            onChange={(val) => {
                                const newState = { ...state, interval: val || 1 }
                                setState(newState)
                                emitChange(newState, startsAt, timezone)
                            }}
                            className="w-14"
                        />
                        <LemonSelect
                            size="small"
                            value={state.frequency}
                            options={FREQUENCY_OPTIONS}
                            onChange={(val) => {
                                const newState = { ...state, frequency: val as FrequencyOption }
                                setState(newState)
                                emitChange(newState, startsAt, timezone)
                            }}
                        />
                        {(state.frequency === 'weekly' || state.frequency === 'monthly') && (
                            <span className="text-muted">on</span>
                        )}
                        {state.frequency === 'weekly' && (
                            <div className="flex gap-0.5">
                                {WEEKDAY_PILL_LABELS.map((label, index) => (
                                    <LemonButton
                                        key={WEEKDAY_LABELS[index]}
                                        size="small"
                                        type={state.weekdays.includes(index) ? 'primary' : 'secondary'}
                                        tooltip={WEEKDAY_FULL_LABELS[index]}
                                        onClick={() => {
                                            const newWeekdays = state.weekdays.includes(index)
                                                ? state.weekdays.filter((d) => d !== index)
                                                : [...state.weekdays, index].sort()
                                            const newState = { ...state, weekdays: newWeekdays }
                                            setState(newState)
                                            emitChange(newState, startsAt, timezone)
                                        }}
                                    >
                                        {label}
                                    </LemonButton>
                                ))}
                            </div>
                        )}
                        {state.frequency === 'monthly' && (
                            <div className="flex gap-1">
                                <LemonButton
                                    size="small"
                                    type={state.monthlyMode === 'day_of_month' ? 'primary' : 'secondary'}
                                    onClick={() => {
                                        const newState = { ...state, monthlyMode: 'day_of_month' as MonthlyMode }
                                        setState(newState)
                                        emitChange(newState, startsAt, timezone)
                                    }}
                                >
                                    {monthlyDayLabel}
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type={state.monthlyMode === 'nth_weekday' ? 'primary' : 'secondary'}
                                    onClick={() => {
                                        const newState = { ...state, monthlyMode: 'nth_weekday' as MonthlyMode }
                                        setState(newState)
                                        emitChange(newState, startsAt, timezone)
                                    }}
                                >
                                    {monthlyNthLabel}
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    type={state.monthlyMode === 'last_day' ? 'primary' : 'secondary'}
                                    onClick={() => {
                                        const newState = { ...state, monthlyMode: 'last_day' as MonthlyMode }
                                        setState(newState)
                                        emitChange(newState, startsAt, timezone)
                                    }}
                                >
                                    Last day
                                </LemonButton>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-muted">Ends</span>
                        <div className="flex gap-1">
                            {(
                                [
                                    { value: 'never', label: 'Never' },
                                    { value: 'on_date', label: 'On date' },
                                    { value: 'after_count', label: 'After' },
                                ] as const
                            ).map((opt) => (
                                <LemonButton
                                    key={opt.value}
                                    size="small"
                                    type={state.endType === opt.value ? 'primary' : 'secondary'}
                                    onClick={() => {
                                        const newState = { ...state, endType: opt.value }
                                        setState(newState)
                                        emitChange(newState, startsAt, timezone)
                                    }}
                                >
                                    {opt.label}
                                </LemonButton>
                            ))}
                        </div>
                        {state.endType === 'after_count' && (
                            <>
                                <LemonInput
                                    type="number"
                                    min={1}
                                    max={999}
                                    size="small"
                                    value={state.endCount}
                                    onChange={(val) => {
                                        const newState = { ...state, endCount: val || 1 }
                                        setState(newState)
                                        emitChange(newState, startsAt, timezone)
                                    }}
                                    className="w-16"
                                />
                                <span className="text-muted text-sm">occurrences</span>
                            </>
                        )}
                        {state.endType === 'on_date' && (
                            <div className="shrink-0">
                                <LemonCalendarSelectInput
                                    value={state.endDate ? dayjs(state.endDate) : null}
                                    onChange={(date) => {
                                        const newState = { ...state, endDate: date ? date.toISOString() : null }
                                        setState(newState)
                                        emitChange(newState, startsAt, timezone)
                                    }}
                                    granularity="day"
                                    selectionPeriod="upcoming"
                                    buttonProps={{ size: 'small' }}
                                />
                            </div>
                        )}
                    </div>

                    {state.frequency === 'monthly' &&
                        state.monthlyMode === 'day_of_month' &&
                        startsAt &&
                        dayjs(startsAt).date() >= 29 && (
                            <div className="text-xs text-warning">
                                Some months don't have a {dayjs(startsAt).format('Do')}. Those months will be skipped.
                                Use "Last day" to run on the last day of every month instead.
                            </div>
                        )}

                    <div className="border rounded-lg p-3 bg-bg-light">
                        {summary && (
                            <div className="flex items-center gap-2 mb-3">
                                <IconCalendar className="text-muted shrink-0" />
                                <span className="text-sm">{summary}</span>
                            </div>
                        )}

                        {previewOccurrences.length > 0 && (
                            <div>
                                <div className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">
                                    {state.endType !== 'never'
                                        ? `${previewOccurrences.length} occurrences`
                                        : 'Next occurrences'}
                                </div>
                                <div className="space-y-1.5">
                                    <OccurrencesList
                                        occurrences={previewOccurrences}
                                        isFinite={state.endType !== 'never'}
                                    />
                                </div>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    )
}
