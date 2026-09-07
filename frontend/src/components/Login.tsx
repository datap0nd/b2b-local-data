import {useState} from 'react';
import {Button} from './ui/button';

/** Initial name identification (only where the server requires it). The name is not repeated in the workspace. */
export function Login({onLogin}: {onLogin: (name: string) => Promise<void>}) {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="grid min-h-screen place-items-center bg-surface px-4">
      <form
        className="w-full max-w-sm rounded-card border border-line bg-canvas p-6 shadow-card"
        onSubmit={async e => { e.preventDefault(); if (!name.trim() || busy) return; setBusy(true); setError(null); try { await onLogin(name.trim()); } catch (err) { setError(err instanceof Error ? err.message : 'Could not sign in.'); } finally { setBusy(false); } }}>
        <h1 className="text-lg font-semibold">Your name</h1>
        <p className="mt-1 text-sm text-ink-2">Used to keep your conversations.</p>
        <input autoFocus value={name} onChange={e => setName(e.target.value)} maxLength={60} autoComplete="name" placeholder="First and last name" aria-label="Your name"
          className="mt-4 h-10 w-full rounded-lg border border-line px-3 text-[15px] outline-none focus:border-line-2" />
        {error && <p className="mt-2 text-sm text-danger" role="alert">{error}</p>}
        <Button type="submit" className="mt-4 w-full" disabled={busy || !name.trim()}>Continue</Button>
      </form>
    </div>
  );
}
