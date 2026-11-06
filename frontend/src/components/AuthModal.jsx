import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api.js'
import Icon from './Icon.jsx'

export default function AuthModal({ isOpen, onClose, onAuthSuccess, initialMode = 'login', theme = 'light' }) {
  const [mode, setMode] = useState(initialMode) // 'login', 'signup', 'login-otp', 'forgot'
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [otpSent, setOtpSent] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)

  const googleBtnRef = useRef(null)
  const timerRef = useRef(null)

  useEffect(() => {
    setMode(initialMode)
    setError('')
    setSuccess('')
    setOtpSent(false)
  }, [initialMode, isOpen])

  // Countdown timer for OTP resend
  useEffect(() => {
    if (resendCooldown > 0) {
      timerRef.current = window.setTimeout(() => setResendCooldown((c) => c - 1), 1000)
    }
    return () => window.clearTimeout(timerRef.current)
  }, [resendCooldown])

  // Initialize Google Identity Services button
  useEffect(() => {
    if (!isOpen) return
    const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || '226549113706-p95qn8laovuceqkc3ed07sqesquq2513.apps.googleusercontent.com'

    function handleGoogleCallback(response) {
      if (!response.credential) return
      setLoading(true)
      setError('')
      api.googleAuth(response.credential)
        .then((res) => {
          api.setAuth(res.token, res.user)
          onAuthSuccess(res.user, 'Logged in with Google')
          onClose()
        })
        .catch((err) => {
          setError(err.message || 'Google sign-in failed. Please try again.')
        })
        .finally(() => setLoading(false))
    }

    const checkGoogle = () => {
      if (window.google?.accounts?.id && googleBtnRef.current) {
        try {
          window.google.accounts.id.initialize({
            client_id: clientId,
            callback: handleGoogleCallback,
          })
          googleBtnRef.current.innerHTML = ''
          window.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: theme === 'dark' ? 'filled_black' : 'outline',
            size: 'large',
            width: 340,
            text: mode === 'signup' ? 'signup_with' : 'signin_with',
            shape: 'pill',
          })
        } catch {
          // Fallback handled below
        }
      }
    }

    const timer = setTimeout(checkGoogle, 150)
    return () => clearTimeout(timer)
  }, [isOpen, mode, theme])

  if (!isOpen) return null

  async function handleSendOtp(purpose) {
    if (!email.trim() || !email.includes('@')) {
      setError('Please enter a valid email address first.')
      return
    }
    setLoading(true)
    setError('')
    setSuccess('')
    try {
      const res = await api.sendOtp(email.trim(), purpose)
      setOtpSent(true)
      setResendCooldown(60)
      setSuccess(`Verification code sent to ${email.trim()}. Please check your inbox or spam folder.`)
    } catch (err) {
      setError(err.message || 'Failed to send OTP. Please check your email or network connection.')
    } finally {
      setLoading(false)
    }
  }

  async function handleLogin(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await api.login(email.trim(), password)
      api.setAuth(res.token, res.user)
      onAuthSuccess(res.user, 'Signed in successfully')
      onClose()
    } catch (err) {
      setError(err.message || 'Invalid email or password.')
    } finally {
      setLoading(false)
    }
  }

  async function handleLoginOtp(e) {
    e.preventDefault()
    if (!otp.trim()) {
      setError('Please enter the 6-digit verification code.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await api.loginOtp(email.trim(), otp.trim())
      api.setAuth(res.token, res.user)
      onAuthSuccess(res.user, 'Signed in with OTP')
      onClose()
    } catch (err) {
      setError(err.message || 'Invalid or expired OTP.')
    } finally {
      setLoading(false)
    }
  }

  async function handleSignup(e) {
    e.preventDefault()
    if (!name.trim()) {
      setError('Please enter your full name.')
      return
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters long.')
      return
    }
    if (!otp.trim()) {
      setError('Please request and enter the 6-digit email verification code.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await api.signup({
        name: name.trim(),
        email: email.trim(),
        password,
        otp: otp.trim(),
      })
      api.setAuth(res.token, res.user)
      onAuthSuccess(res.user, 'Account created and signed in successfully')
      onClose()
    } catch (err) {
      setError(err.message || 'Signup failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  async function handleResetPassword(e) {
    e.preventDefault()
    if (!otp.trim()) {
      setError('Please enter the verification code sent to your email.')
      return
    }
    if (newPassword.length < 6) {
      setError('New password must be at least 6 characters long.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const res = await api.resetPassword({
        email: email.trim(),
        otp: otp.trim(),
        newPassword,
      })
      setSuccess(res.message || 'Password reset successfully! Please sign in with your new password.')
      setMode('login')
      setPassword('')
      setOtp('')
    } catch (err) {
      setError(err.message || 'Password reset failed.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="auth-modal-title">
      <div className="auth-modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="auth-modal-header">
          <div className="auth-modal-brand">
            <span className="auth-modal-badge"><Icon name="spark" size={16} /></span>
            <div>
              <span className="eyebrow">RESEARCHPAPER AI ACCOUNT</span>
              <h2 id="auth-modal-title">
                {mode === 'login' && 'Sign in to your library'}
                {mode === 'login-otp' && 'Sign in with Email OTP'}
                {mode === 'signup' && 'Create your research account'}
                {mode === 'forgot' && 'Reset your password'}
              </h2>
            </div>
          </div>
          <button className="icon-button close-button" type="button" onClick={onClose} aria-label="Close dialog">
            <Icon name="close" size={17} />
          </button>
        </div>

        {/* Tab switcher */}
        {(mode === 'login' || mode === 'signup') && (
          <div className="auth-tabs" role="tablist">
            <button
              className={`auth-tab ${mode === 'login' ? 'active' : ''}`}
              type="button"
              role="tab"
              aria-selected={mode === 'login'}
              onClick={() => { setMode('login'); setError(''); setSuccess('') }}
            >
              Sign In
            </button>
            <button
              className={`auth-tab ${mode === 'signup' ? 'active' : ''}`}
              type="button"
              role="tab"
              aria-selected={mode === 'signup'}
              onClick={() => { setMode('signup'); setError(''); setSuccess('') }}
            >
              Create Account
            </button>
          </div>
        )}

        {/* Google One-Click Auth */}
        {(mode === 'login' || mode === 'signup') && (
          <div className="auth-google-section">
            <div ref={googleBtnRef} className="google-btn-container" />
            <div className="auth-divider"><span>OR CONTINUE WITH EMAIL</span></div>
          </div>
        )}

        {error && <div className="notice notice-error" role="alert">{error}</div>}
        {success && <div className="notice notice-info" role="status">{success}</div>}

        {/* Form: Standard Password Login */}
        {mode === 'login' && (
          <form className="auth-form" onSubmit={handleLogin}>
            <div className="auth-field">
              <label htmlFor="auth-email">Academic or Personal Email</label>
              <input
                id="auth-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="researcher@university.edu"
                required
                autoComplete="email"
              />
            </div>

            <div className="auth-field">
              <div className="auth-field-header">
                <label htmlFor="auth-password">Password</label>
                <button
                  type="button"
                  className="auth-link-btn"
                  onClick={() => { setMode('forgot'); setError(''); setSuccess('') }}
                >
                  Forgot password?
                </button>
              </div>
              <div className="auth-password-wrapper">
                <input
                  id="auth-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  required
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  <Icon name={showPassword ? 'sun' : 'moon'} size={15} />
                </button>
              </div>
            </div>

            <button className="primary-action full-width" type="submit" disabled={loading}>
              {loading ? <span className="button-spinner" /> : <Icon name="check" size={16} />}
              {loading ? 'Authenticating…' : 'Sign in to ResearchPaper AI'}
            </button>

            <div className="auth-footer-links">
              <button
                type="button"
                className="auth-link-secondary"
                onClick={() => { setMode('login-otp'); setError(''); setSuccess('') }}
              >
                Sign in with OTP code instead (passwordless)
              </button>
            </div>
          </form>
        )}

        {/* Form: Passwordless OTP Login */}
        {mode === 'login-otp' && (
          <form className="auth-form" onSubmit={handleLoginOtp}>
            <div className="auth-field">
              <label htmlFor="auth-login-otp-email">Email Address</label>
              <div className="auth-input-action-row">
                <input
                  id="auth-login-otp-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="researcher@university.edu"
                  required
                />
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => handleSendOtp('login')}
                  disabled={loading || resendCooldown > 0}
                >
                  {resendCooldown > 0 ? `Resend (${resendCooldown}s)` : 'Send OTP'}
                </button>
              </div>
            </div>

            {otpSent && (
              <div className="auth-field">
                <label htmlFor="auth-login-otp-code">6-Digit Login Code</label>
                <input
                  id="auth-login-otp-code"
                  type="text"
                  maxLength="6"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                  placeholder="123456"
                  className="otp-input-highlight"
                  required
                  autoFocus
                />
              </div>
            )}

            <button className="primary-action full-width" type="submit" disabled={loading || !otpSent}>
              {loading ? <span className="button-spinner" /> : <Icon name="check" size={16} />}
              {loading ? 'Verifying OTP…' : 'Sign in with Code'}
            </button>

            <div className="auth-footer-links">
              <button
                type="button"
                className="auth-link-secondary"
                onClick={() => { setMode('login'); setError(''); setSuccess('') }}
              >
                ← Back to Password Sign In
              </button>
            </div>
          </form>
        )}

        {/* Form: Sign Up with OTP Verification */}
        {mode === 'signup' && (
          <form className="auth-form" onSubmit={handleSignup}>
            <div className="auth-field">
              <label htmlFor="auth-signup-name">Full Name</label>
              <input
                id="auth-signup-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Dr. Vivek Shukla"
                required
              />
            </div>

            <div className="auth-field">
              <label htmlFor="auth-signup-email">Email Address</label>
              <div className="auth-input-action-row">
                <input
                  id="auth-signup-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="researcher@university.edu"
                  required
                />
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => handleSendOtp('signup')}
                  disabled={loading || resendCooldown > 0}
                >
                  {resendCooldown > 0 ? `Resend (${resendCooldown}s)` : 'Send Code'}
                </button>
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="auth-signup-password">Password (min 6 characters)</label>
              <div className="auth-password-wrapper">
                <input
                  id="auth-signup-password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Create a strong password"
                  required
                  minLength="6"
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword((s) => !s)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  <Icon name={showPassword ? 'sun' : 'moon'} size={15} />
                </button>
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="auth-signup-otp">Email Verification Code (from inbox)</label>
              <input
                id="auth-signup-otp"
                type="text"
                maxLength="6"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                placeholder={otpSent ? 'Enter 6-digit code' : 'Click "Send Code" above first'}
                className="otp-input-highlight"
                required
              />
            </div>

            <button className="primary-action full-width" type="submit" disabled={loading}>
              {loading ? <span className="button-spinner" /> : <Icon name="spark" size={16} />}
              {loading ? 'Creating Account…' : 'Complete Registration'}
            </button>
          </form>
        )}

        {/* Form: Password Reset */}
        {mode === 'forgot' && (
          <form className="auth-form" onSubmit={handleResetPassword}>
            <p className="auth-form-description">
              Enter your email to receive a password reset verification code.
            </p>

            <div className="auth-field">
              <label htmlFor="auth-forgot-email">Account Email</label>
              <div className="auth-input-action-row">
                <input
                  id="auth-forgot-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="researcher@university.edu"
                  required
                />
                <button
                  type="button"
                  className="secondary-action"
                  onClick={() => handleSendOtp('reset_password')}
                  disabled={loading || resendCooldown > 0}
                >
                  {resendCooldown > 0 ? `Resend (${resendCooldown}s)` : 'Send Code'}
                </button>
              </div>
            </div>

            {otpSent && (
              <>
                <div className="auth-field">
                  <label htmlFor="auth-reset-otp">6-Digit Reset Code</label>
                  <input
                    id="auth-reset-otp"
                    type="text"
                    maxLength="6"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                    placeholder="123456"
                    className="otp-input-highlight"
                    required
                  />
                </div>

                <div className="auth-field">
                  <label htmlFor="auth-new-password">New Password</label>
                  <input
                    id="auth-new-password"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Enter at least 6 characters"
                    required
                    minLength="6"
                  />
                </div>
              </>
            )}

            <button className="primary-action full-width" type="submit" disabled={loading || !otpSent}>
              {loading ? <span className="button-spinner" /> : <Icon name="check" size={16} />}
              {loading ? 'Resetting Password…' : 'Update Password'}
            </button>

            <div className="auth-footer-links">
              <button
                type="button"
                className="auth-link-secondary"
                onClick={() => { setMode('login'); setError(''); setSuccess('') }}
              >
                ← Back to Sign In
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
