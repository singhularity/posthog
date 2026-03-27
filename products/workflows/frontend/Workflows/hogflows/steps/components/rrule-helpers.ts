import { RRule, Frequency } from 'rrule'

import { dayjs } from 'lib/dayjs'

export type FrequencyOption = 'daily' | 'weekly' | 'monthly' | 'yearly'
export type MonthlyMode = 'day_of_month' | 'nth_weekday' | 'last_day'
export type EndType = 'never' | 'on_date' | 'after_count'

export const FREQUENCY_OPTIONS: { value: FrequencyOption; label: string }[] = [
    { value: 'daily', label: 'Day' },
    { value: 'weekly', label: 'Week' },
    { value: 'monthly', label: 'Month' },
    { value: 'yearly', label: 'Year' },
]

export const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const
export const WEEKDAY_PILL_LABELS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'] as const
export const WEEKDAY_RRULE_DAYS = [RRule.MO, RRule.TU, RRule.WE, RRule.TH, RRule.FR, RRule.SA, RRule.SU]
export const WEEKDAY_FULL_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export const NTH_LABELS = ['1st', '2nd', '3rd', '4th', '5th']

export interface ScheduleState {
    interval: number
    frequency: FrequencyOption
    weekdays: number[] // 0=Mon, 6=Sun
    monthlyMode: MonthlyMode
    endType: EndType
    endDate: string | null
    endCount: number
}

export const DEFAULT_STATE: ScheduleState = {
    interval: 1,
    frequency: 'weekly',
    weekdays: [],
    monthlyMode: 'day_of_month',
    endType: 'never',
    endDate: null,
    endCount: 10,
}

export function frequencyToRRule(freq: FrequencyOption): Frequency {
    switch (freq) {
        case 'daily':
            return RRule.DAILY
        case 'weekly':
            return RRule.WEEKLY
        case 'monthly':
            return RRule.MONTHLY
        case 'yearly':
            return RRule.YEARLY
    }
}

export function getNthWeekdayOfMonth(date: dayjs.Dayjs): { n: number; weekday: number } {
    const dayOfMonth = date.date()
    const weekday = (date.day() + 6) % 7
    const n = Math.ceil(dayOfMonth / 7)
    return { n, weekday }
}

export function parseRRuleToState(rruleStr: string): ScheduleState {
    try {
        const rule = RRule.fromString(rruleStr)
        const opts = rule.options

        let frequency: FrequencyOption = 'weekly'
        switch (opts.freq) {
            case RRule.DAILY:
                frequency = 'daily'
                break
            case RRule.WEEKLY:
                frequency = 'weekly'
                break
            case RRule.MONTHLY:
                frequency = 'monthly'
                break
            case RRule.YEARLY:
                frequency = 'yearly'
                break
        }

        const weekdays = opts.byweekday ? opts.byweekday.map((d: number) => d) : []

        let monthlyMode: MonthlyMode = 'day_of_month'
        if (frequency === 'monthly') {
            if (opts.bymonthday && opts.bymonthday.includes(-1)) {
                monthlyMode = 'last_day'
            } else if (opts.bysetpos && opts.bysetpos.length > 0) {
                monthlyMode = 'nth_weekday'
            }
        }

        let endType: EndType = 'never'
        let endDate: string | null = null
        let endCount = 10

        if (opts.until) {
            endType = 'on_date'
            endDate = dayjs(opts.until).toISOString()
        } else if (opts.count) {
            endType = 'after_count'
            endCount = opts.count
        }

        return { interval: opts.interval || 1, frequency, weekdays, monthlyMode, endType, endDate, endCount }
    } catch {
        return { ...DEFAULT_STATE }
    }
}

function buildRRuleOptions(
    state: ScheduleState,
    startsAt: string | null
): Partial<ConstructorParameters<typeof RRule>[0]> {
    const options: Partial<ConstructorParameters<typeof RRule>[0]> = {
        freq: frequencyToRRule(state.frequency),
        interval: state.interval,
    }

    if (state.frequency === 'weekly' && state.weekdays.length > 0) {
        options.byweekday = state.weekdays.map((d) => WEEKDAY_RRULE_DAYS[d])
    }

    if (state.frequency === 'monthly' && startsAt) {
        const date = dayjs(startsAt)
        if (state.monthlyMode === 'last_day') {
            options.bymonthday = [-1]
        } else if (state.monthlyMode === 'day_of_month') {
            options.bymonthday = [date.date()]
        } else {
            const { n, weekday } = getNthWeekdayOfMonth(date)
            options.byweekday = [WEEKDAY_RRULE_DAYS[weekday]]
            options.bysetpos = [n]
        }
    }

    if (state.endType === 'on_date' && state.endDate) {
        const d = dayjs(state.endDate)
        options.until = new Date(Date.UTC(d.year(), d.month(), d.date(), 23, 59, 59, 999))
    } else if (state.endType === 'after_count') {
        options.count = state.endCount
    }

    return options
}

export function stateToRRule(state: ScheduleState, startsAt: string | null): string {
    const options = buildRRuleOptions(state, startsAt)
    const rule = new RRule(options as ConstructorParameters<typeof RRule>[0])
    return rule.toString().replace('RRULE:', '')
}

export function computePreviewOccurrences(state: ScheduleState, startsAt: string, count?: number): Date[] {
    const maxCount =
        count ??
        (state.endType === 'after_count' ? Math.min(state.endCount, 200) : state.endType === 'on_date' ? 200 : 6)
    try {
        const local = dayjs(startsAt)
        const dtstartLocal = new Date(
            Date.UTC(local.year(), local.month(), local.date(), local.hour(), local.minute(), 0)
        )
        const options = buildRRuleOptions(state, startsAt)
        options.dtstart = dtstartLocal

        const fullRule = new RRule(options as ConstructorParameters<typeof RRule>[0])
        return fullRule.all((_, i) => i < maxCount)
    } catch {
        return []
    }
}

export function buildSummary(state: ScheduleState, startsAt: string | null): string {
    const freqLabel = state.frequency === 'daily' ? 'day' : state.frequency.replace('ly', '')
    const intervalStr = state.interval > 1 ? `${state.interval} ${freqLabel}s` : freqLabel

    let summary = `Runs every ${intervalStr}`

    if (state.frequency === 'weekly' && state.weekdays.length > 0) {
        const dayNames = state.weekdays.map((d) => WEEKDAY_FULL_LABELS[d])
        summary += ` on ${dayNames.join(', ')}`
    }

    if (state.frequency === 'monthly') {
        if (state.monthlyMode === 'last_day') {
            summary += ` on the last day`
        } else if (state.monthlyMode === 'day_of_month' && startsAt) {
            summary += ` on the ${dayjs(startsAt).format('Do')}`
        } else if (state.monthlyMode === 'nth_weekday' && startsAt) {
            const { n, weekday } = getNthWeekdayOfMonth(dayjs(startsAt))
            summary += ` on the ${NTH_LABELS[n - 1]} ${WEEKDAY_FULL_LABELS[weekday]}`
        }
    }

    if (startsAt) {
        summary += `, starting ${dayjs(startsAt).format('MMMM D')}`
    }

    if (state.endType === 'after_count') {
        summary += `, ${state.endCount} times`
    } else if (state.endType === 'on_date' && state.endDate) {
        summary += `, until ${dayjs(state.endDate).format('MMMM D, YYYY')}`
    }

    return summary + '.'
}
