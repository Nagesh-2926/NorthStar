import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { authApi } from '../api/services';
import { TOKEN_KEY } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children, tokenStorage = window.localStorage }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let current = true;
    const clearSession = () => {
      tokenStorage.removeItem(TOKEN_KEY);
      if (current) {
        setUser(null);
        setLoading(false);
        setNotice('');
      }
    };
    window.addEventListener('auth:expired', clearSession);
    if (!tokenStorage.getItem(TOKEN_KEY)) {
      setLoading(false);
    } else {
      authApi.me().then((account) => {
        if (current) setUser(account);
      }).catch(clearSession).finally(() => {
        if (current) setLoading(false);
      });
    }
    return () => {
      current = false;
      window.removeEventListener('auth:expired', clearSession);
    };
  }, [tokenStorage]);

  const signIn = async (credentials) => {
    const token = await authApi.login(credentials);
    tokenStorage.setItem(TOKEN_KEY, token.access_token);
    try {
      const account = await authApi.me();
      setUser(account);
      return account;
    } catch (error) {
      tokenStorage.removeItem(TOKEN_KEY);
      throw error;
    }
  };

  const register = async (details) => {
    await authApi.register(details);
    return signIn({ email: details.email, password: details.password });
  };

  const signOut = (message = '') => {
    tokenStorage.removeItem(TOKEN_KEY);
    setUser(null);
    setNotice(message);
  };

  const clearNotice = () => setNotice('');

  const value = useMemo(() => ({ user, loading, notice, clearNotice, signIn, register, signOut }),
    [user, loading, notice, tokenStorage]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
