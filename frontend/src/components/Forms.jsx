export function Field({ label, hint, error, id, className = '', children, ...props }) {
  return (
    <div className={`field ${className}`.trim()}>
      <label htmlFor={id}>{label}</label>
      {children || <input id={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined} {...props} />}
      {hint && <small id={`${id}-hint`}>{hint}</small>}
      {error && <small id={`${id}-error`} className="field-error" role="alert">{error}</small>}
    </div>
  );
}

export function SelectField({ label, id, options, ...props }) {
  return <Field label={label} id={id}><select id={id} {...props}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></Field>;
}
