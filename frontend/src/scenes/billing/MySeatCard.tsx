import { useActions, useValues } from 'kea'

import { IconTerminal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'

import { CODE_PLAN_FREE, CODE_PLAN_PRO } from './constants'
import { seatBillingLogic } from './seatBillingLogic'

function planLabel(planKey: string): string {
    if (planKey === CODE_PLAN_PRO) {
        return 'Pro ($200/mo)'
    }
    return 'Free ($0/mo)'
}

function statusColor(status: string): 'success' | 'warning' | 'muted' | 'primary' {
    switch (status) {
        case 'active':
            return 'success'
        case 'canceling':
            return 'warning'
        case 'expired':
        case 'withdrawn':
            return 'muted'
        default:
            return 'primary'
    }
}

export function MySeatCard(): JSX.Element {
    const { mySeat, mySeatLoading, canUpgrade, canCancel, canReactivate } = useValues(seatBillingLogic)
    const { upgradeSeat, cancelSeat, reactivateSeat, createSeat } = useActions(seatBillingLogic)

    if (mySeatLoading && !mySeat) {
        return (
            <div className="relative min-h-30">
                <SpinnerOverlay />
            </div>
        )
    }

    if (!mySeat) {
        return (
            <div className="bg-surface-secondary rounded p-6">
                <div className="flex items-center gap-2 mb-4">
                    <IconTerminal className="text-2xl" />
                    <h3 className="mb-0 text-lg font-semibold">PostHog Code</h3>
                </div>
                <p className="text-muted mb-4">You don't have a PostHog Code seat yet.</p>
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={() => createSeat(CODE_PLAN_FREE)}>
                        Get started free
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => createSeat(CODE_PLAN_PRO)}>
                        Subscribe to Pro
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="bg-surface-secondary rounded p-6">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                    <IconTerminal className="text-2xl" />
                    <h3 className="mb-0 text-lg font-semibold">PostHog Code</h3>
                    <LemonTag type={statusColor(mySeat.status)}>{mySeat.status}</LemonTag>
                </div>
                {canCancel && mySeat.status === 'active' && (
                    <More
                        overlay={
                            <LemonButton
                                fullWidth
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Cancel your seat?',
                                        description:
                                            'Your seat will remain active until the end of the current billing period.',
                                        primaryButton: {
                                            children: 'Cancel seat',
                                            status: 'danger',
                                            onClick: cancelSeat,
                                        },
                                        secondaryButton: { children: 'Keep seat' },
                                    })
                                }}
                            >
                                Cancel seat
                            </LemonButton>
                        }
                    />
                )}
            </div>

            <div className="flex flex-col gap-2 mb-4">
                <div>
                    <span className="text-muted mr-2">Plan:</span>
                    <span className="font-semibold">{planLabel(mySeat.plan_key)}</span>
                </div>
                {mySeat.active_from && (
                    <div>
                        <span className="text-muted mr-2">Active from:</span>
                        <span>{dayjs(mySeat.active_from).format('MMM D, YYYY')}</span>
                    </div>
                )}
                {mySeat.active_until && (
                    <div>
                        <span className="text-muted mr-2">Active until:</span>
                        <span>{dayjs(mySeat.active_until).format('MMM D, YYYY')}</span>
                    </div>
                )}
            </div>

            {mySeat.status === 'canceling' && (
                <LemonBanner type="warning" className="mb-4">
                    Your seat is set to expire
                    {mySeat.active_until ? ` on ${dayjs(mySeat.active_until).format('MMM D, YYYY')}` : ''}.
                    <LemonButton type="secondary" size="small" className="ml-2" onClick={reactivateSeat}>
                        Reactivate
                    </LemonButton>
                </LemonBanner>
            )}

            {canUpgrade && (
                <LemonButton type="primary" onClick={() => upgradeSeat(CODE_PLAN_PRO)}>
                    Upgrade to Pro
                </LemonButton>
            )}

            {canReactivate && mySeat.status !== 'canceling' && (
                <LemonButton type="primary" onClick={reactivateSeat}>
                    Reactivate
                </LemonButton>
            )}
        </div>
    )
}
