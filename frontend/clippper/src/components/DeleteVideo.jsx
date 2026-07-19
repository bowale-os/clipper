import { TrashIcon } from './icons'

/* Two states in one spot: a quiet trash button, and the confirm that replaces
   it in place. Nothing moves around it, so the row keeps its shape. */

function DeleteVideo({ error, filename, isDeleting, isPending, onAsk, onCancel, onConfirm }) {
  const name = filename || 'this stream'

  if (isPending) {
    // A failure swaps the prompt for the reason and leaves both buttons, so the
    // retry and the way out are where the user is already looking.
    return (
      <span className="delete-confirm">
        <span className={`delete-confirm-text${error ? ' is-bad' : ''}`}>
          {error || 'Delete for good?'}
        </span>
        <button
          className="delete-yes"
          disabled={isDeleting}
          onClick={onConfirm}
          type="button"
        >
          {isDeleting ? 'Deleting' : 'Yes, delete'}
        </button>
        <button className="delete-no" disabled={isDeleting} onClick={onCancel} type="button">
          Keep it
        </button>
      </span>
    )
  }

  return (
    <button aria-label={`Delete ${name}`} className="delete-btn" onClick={onAsk} type="button">
      <TrashIcon size={16} />
    </button>
  )
}

export default DeleteVideo
