function Toggle({ checked, onChange, disabled = false, label }) {
  return (
    <label className="switch">
      <input
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      <span className="switch-track" />
      <span>{label}</span>
    </label>
  )
}

export default Toggle
