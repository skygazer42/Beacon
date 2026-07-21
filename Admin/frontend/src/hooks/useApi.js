import { useState, useEffect, useCallback } from 'react';
import { apiGet } from '../api/client';

export default function useApi(url, params, options = {}) {
  const { manual = false, defaultData = null } = options;
  const [data, setData] = useState(defaultData);
  const [loading, setLoading] = useState(!manual);
  const [error, setError] = useState(null);

  const paramsKey = params ? JSON.stringify(params) : '';

  const run = useCallback(async (overrideParams) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiGet(url, overrideParams || params);
      setData(result);
      return result;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setLoading(false);
    }
  }, [url, paramsKey]);

  useEffect(() => {
    if (!manual) {
      run();
    }
  }, [run, manual]);

  return { data, loading, error, run, setData };
}
