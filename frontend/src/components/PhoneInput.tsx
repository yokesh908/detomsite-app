import { InputHTMLAttributes } from 'react'

/* Indian mobile number input.
   The user simply types their 10-digit number — no +91 is forced onto the
   field. The controlled value is kept in full E.164 form ("+919876543210")
   so whatever is submitted to the backend already includes the +91 country
   code. Pasted values like "+91 98765 43210" or "919876543210" are
   normalised too (a leading 91 is treated as the country code). */

export function extractDigits(value: string) {
  return value.replace(/\D/g, '')
}

export function toE164(value: string) {
  let digits = extractDigits(value)
  // Drop the country code if the user typed/pasted it themselves (91 + 10 digits)
  if (digits.length > 10 && digits.startsWith('91')) digits = digits.slice(2)
  digits = digits.slice(-10)
  return digits ? `+91${digits}` : ''
}

export function isValidMobile(value: string) {
  // Accept both a plain 10-digit number and the E.164 form the input emits (+91 + 10 digits)
  const digits = extractDigits(value)
  return digits.length === 10 || (digits.length === 12 && digits.startsWith('91'))
}

/* Show ONLY the user's digits — never the +91 prefix. The stored value is E.164
   ("+919876543210"), so the country code must be stripped back off before it is
   echoed into the field, otherwise typing "9" shows "919" (the 91 leaks in on
   every keystroke). Only strip when the 91 really is the prefix we added: the raw
   value carries the "+91" marker, or it is a pasted 12-digit E.164 number. */
export function displayDigits(value: string) {
  let digits = extractDigits(value)
  const raw = String(value || '')
  if (digits.startsWith('91') && (raw.startsWith('+91') || digits.length > 10)) digits = digits.slice(2)
  return digits.slice(-10)
}

interface PhoneInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> {
  value: string
  onChange: (value: string) => void
}

export function PhoneInput({ value, onChange, placeholder = '98765 43210', className = '', ...rest }: PhoneInputProps) {
  const digits = displayDigits(value)
  return (
    <div className={`w-full overflow-hidden rounded-btn border-2 border-gray-200 bg-white transition-all focus-within:border-emerald-500 focus-within:shadow-emerald-sm ${className}`}>
      {/* No maxLength here — the browser would truncate a pasted "+91…" number
          before toE164 gets a chance to strip the country code. displayDigits
          clamps the echoed value to the last 10 digits. */}
      <input
        type="tel"
        inputMode="numeric"
        autoComplete="off"
        value={digits}
        placeholder={placeholder}
        onChange={e => onChange(toE164(e.target.value))}
        className="w-full px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 outline-none"
        {...rest}
      />
    </div>
  )
}
