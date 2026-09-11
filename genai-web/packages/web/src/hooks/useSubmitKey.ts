import { useLocalStorage } from '@/hooks/useLocalStorage';
import {
  DEFAULT_SUBMIT_KEY,
  parseSubmitKey,
  SUBMIT_KEY_STORAGE,
  submitKeyHint,
  type SubmitKey,
} from '@/utils/keyboard';

export const useSubmitKey = () => {
  const [raw, setRaw] = useLocalStorage(SUBMIT_KEY_STORAGE, DEFAULT_SUBMIT_KEY);
  const key = parseSubmitKey(raw);
  return {
    key,
    setKey: (next: SubmitKey) => setRaw(next),
    hint: submitKeyHint(key),
  };
};
