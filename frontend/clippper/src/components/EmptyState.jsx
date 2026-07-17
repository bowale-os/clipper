function EmptyState({ glyph, title, description, action }) {
  return (
    <div className="empty-state">
      {glyph ? <span className="empty-glyph">{glyph}</span> : null}
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action}
    </div>
  )
}

export default EmptyState
