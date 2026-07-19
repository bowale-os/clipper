function Toggle({ checked, onChange, disabled = false, label, ariaLabel }) {
  return (
    <label className="switch">
      <input
        aria-label={label ? undefined : ariaLabel}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <span className="switch-track" />
      {label ? <span>{label}</span> : null}
    </label>
  )
}

export default Toggle
