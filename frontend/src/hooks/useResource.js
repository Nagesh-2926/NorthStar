import { useEffect, useState } from 'react';

export function useResource(loader, dependencies = []) {
  const [resource, setResource] = useState({ data: null, loading: true, error: null });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    setResource((current) => ({ ...current, loading: true, error: null }));
    Promise.resolve().then(loader).then((data) => {
      if (active) setResource({ data, loading: false, error: null });
    }).catch((error) => {
      if (active) setResource({ data: null, loading: false, error });
    });
    return () => { active = false; };
    // Callers list every value used by loader in dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, revision]);

  const retry = () => setRevision((value) => value + 1);
  const setData = (data) => setResource({ data, loading: false, error: null });
  return { ...resource, retry, setData };
}
