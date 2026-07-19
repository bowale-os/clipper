function EmptyState({ glyph, title, description, action, roomy = false }) {
  return (
    <div className={roomy ? 'empty-state empty-state-roomy' : 'empty-state'}>
      {glyph ? <span className="empty-glyph">{glyph}</span> : null}
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action}
    </div>
  )
}

export default EmptyState
