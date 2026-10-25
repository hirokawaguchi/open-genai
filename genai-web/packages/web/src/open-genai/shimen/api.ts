import { genUApi, isApiError } from '@/lib/fetcher';

export const rewriteText = async (text: string, instruction: string): Promise<string> => {
  const response = await genUApi.post<{ text: string }>('/shimen/rewrite', { text, instruction });
  return response.data.text;
};

export const generatePlacedImage = async (prompt: string): Promise<string> => {
  const response = await genUApi.post<string>('/image/generate', {
    params: {
      textPrompt: [{ text: prompt, weight: 1 }],
      width: 768,
      height: 768,
    },
  });
  const data = response.data.trim();
  if (data.startsWith('data:')) {
    return data;
  }
  return `data:image/png;base64,${data}`;
};

export const errorMessage = (error: unknown, fallback: string): string => {
  if (isApiError(error) && error.data && typeof error.data === 'object') {
    const data = error.data as { error?: string; message?: string };
    return data.error || data.message || fallback;
  }
  return fallback;
};
