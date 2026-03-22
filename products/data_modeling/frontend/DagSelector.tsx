import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { DataModelingDAG } from '~/types'

const CREATE_NEW_DAG_VALUE = '__create_new__'

export function DagSelector({
    dags,
    selectedDagId,
    dagName,
    onSelectDag,
    onDagName,
}: {
    dags: DataModelingDAG[]
    selectedDagId: string | null
    dagName: string | null
    onSelectDag: (dagId: string | null) => void
    onDagName: (name: string | null) => void
}): JSX.Element {
    const isCreating = dagName !== null
    const existingNames = new Set(dags.map((d) => d.name))

    const handleSelectChange = (selected: string | null): void => {
        if (selected === CREATE_NEW_DAG_VALUE) {
            onSelectDag(null)
            onDagName('')
        } else {
            onDagName(null)
            onSelectDag(selected)
        }
    }

    const options = [
        ...dags.map((d) => ({ value: d.id, label: d.name })),
        { value: CREATE_NEW_DAG_VALUE, label: '+ Create new' },
    ]

    return (
        <div className="space-y-2">
            <LemonSelect
                value={isCreating ? CREATE_NEW_DAG_VALUE : selectedDagId}
                onChange={handleSelectChange}
                options={options}
                placeholder="Select a DAG"
                fullWidth
            />
            {isCreating && (
                <>
                    <LemonInput
                        value={dagName ?? ''}
                        onChange={(name) => onDagName(name)}
                        placeholder="Enter DAG name"
                        autoFocus
                    />
                    {dagName && existingNames.has(dagName.trim()) && (
                        <p className="text-danger text-xs">A DAG with this name already exists</p>
                    )}
                </>
            )}
        </div>
    )
}
