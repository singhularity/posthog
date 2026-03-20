import { useValues } from 'kea'

import { MySeatCard } from './MySeatCard'
import { OrgSeatsSection } from './OrgSeatsSection'
import { seatBillingLogic } from './seatBillingLogic'

export function BillingSeats(): JSX.Element {
    const { isAdmin } = useValues(seatBillingLogic)

    return (
        <div className="flex flex-col gap-8 max-w-300 mt-4">
            <MySeatCard />
            {isAdmin && <OrgSeatsSection />}
        </div>
    )
}
