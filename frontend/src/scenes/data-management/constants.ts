import { LemonSelectOptions } from '@posthog/lemon-ui'

export const verifiedOptions: LemonSelectOptions<string> = [
    { value: '', label: 'Any status' },
    { value: 'true', label: 'Verified only' },
    { value: 'false', label: 'Unverified only' },
]
