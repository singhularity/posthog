import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { CODE_PLAN_FREE, CODE_PLAN_PRO, CODE_PRODUCT_KEY } from './constants'
import type { seatBillingLogicType } from './seatBillingLogicType'
import type { SeatData } from './types'

export const seatBillingLogic = kea<seatBillingLogicType>([
    path(['scenes', 'billing', 'seatBillingLogic']),
    connect(() => ({
        values: [organizationLogic, ['currentOrganization'], userLogic, ['user']],
    })),
    actions({
        upgradeSeat: (planKey: string) => ({ planKey }),
        cancelSeat: true,
        reactivateSeat: true,
        createSeat: (planKey: string) => ({ planKey }),
    }),
    loaders(() => ({
        mySeat: [
            null as SeatData | null,
            {
                loadMySeat: async (): Promise<SeatData | null> => {
                    try {
                        return await api.get(`api/seats/me/?product_key=${CODE_PRODUCT_KEY}`)
                    } catch (e: any) {
                        if (e.status === 404) {
                            return null
                        }
                        throw e
                    }
                },
            },
        ],
        orgSeats: [
            [] as SeatData[],
            {
                loadOrgSeats: async (): Promise<SeatData[]> => {
                    try {
                        return await api.get(`api/seats/?product_key=${CODE_PRODUCT_KEY}`)
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),
    selectors({
        isAdmin: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean =>
                !!(
                    currentOrganization?.membership_level &&
                    currentOrganization.membership_level >= OrganizationMembershipLevel.Admin
                ),
        ],
        isPro: [(s) => [s.mySeat], (mySeat): boolean => mySeat?.plan_key === CODE_PLAN_PRO],
        isFree: [(s) => [s.mySeat], (mySeat): boolean => mySeat?.plan_key === CODE_PLAN_FREE],
        canUpgrade: [
            (s) => [s.mySeat],
            (mySeat): boolean => !!mySeat && mySeat.status === 'active' && mySeat.plan_key === CODE_PLAN_FREE,
        ],
        canCancel: [(s) => [s.mySeat], (mySeat): boolean => !!mySeat && mySeat.status === 'active'],
        canReactivate: [(s) => [s.mySeat], (mySeat): boolean => !!mySeat && mySeat.status === 'canceling'],
    }),
    listeners(({ actions, values }) => ({
        upgradeSeat: async ({ planKey }) => {
            try {
                await api.update(`api/seats/me/`, { product_key: CODE_PRODUCT_KEY, plan_key: planKey })
                lemonToast.success('Seat upgraded successfully')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch {
                lemonToast.error('Failed to upgrade seat')
            }
        },
        cancelSeat: async () => {
            try {
                await api.delete(`api/seats/me/?product_key=${CODE_PRODUCT_KEY}`)
                lemonToast.success('Seat canceled')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch {
                lemonToast.error('Failed to cancel seat')
            }
        },
        reactivateSeat: async () => {
            try {
                await api.create(`api/seats/me/reactivate/`, { product_key: CODE_PRODUCT_KEY })
                lemonToast.success('Seat reactivated')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch {
                lemonToast.error('Failed to reactivate seat')
            }
        },
        createSeat: async ({ planKey }) => {
            try {
                await api.create(`api/seats/`, {
                    product_key: CODE_PRODUCT_KEY,
                    plan_key: planKey,
                    user_distinct_id: values.user?.distinct_id,
                })
                lemonToast.success('Seat created')
                actions.loadMySeat()
                if (values.isAdmin) {
                    actions.loadOrgSeats()
                }
            } catch {
                lemonToast.error('Failed to create seat')
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadMySeat()
        if (values.isAdmin) {
            actions.loadOrgSeats()
        }
    }),
])
