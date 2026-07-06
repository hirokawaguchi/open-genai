import {
  CreateChatResponse,
  CreateMessagesRequest,
  CreateMessagesResponse,
  PredictRequest,
  PredictResponse,
  PredictTitleRequest,
  PredictTitleResponse,
  UpdateTitleRequest,
  UpdateTitleResponse,
} from 'genai-web';
import { genUApi } from '@/lib/fetcher';
import { getIdToken } from '@/local/localAuth';
import { decomposeId } from '@/utils/decomposeId';

export const createChat = async (req: { usecase?: string } = {}) => {
  const res = await genUApi.post<CreateChatResponse>('chats', req);
  return res.data;
};

export const createMessages = async (_chatId: string, req: CreateMessagesRequest) => {
  const chatId = decomposeId(_chatId);
  const res = await genUApi.post<CreateMessagesResponse>(`chats/${chatId}/messages`, req);
  return res.data;
};

export const deleteChat = async (chatId: string) => {
  return genUApi.delete<void>(`chats/${chatId}`);
};

export const updateTitle = async (chatId: string, title: string) => {
  const req: UpdateTitleRequest = {
    title,
  };
  const res = await genUApi.put<UpdateTitleResponse>(`chats/${chatId}/title`, req);
  return res.data;
};

export const predict = async (req: PredictRequest): Promise<string> => {
  const res = await genUApi.post<PredictResponse>('predict', req);
  return res.data;
};

/**
 * Open GENAI: クラウド版は Lambda の InvokeWithResponseStream を直接叩くが、
 * ローカルではバックエンド (FastAPI) の /predict/stream を fetch でストリーム取得する。
 * バックエンドは改行区切り JSON (StreamingChunk) を返すため、完全な 1 行ごとに
 * yield して呼び出し側 (useChat) の JSON.parse が壊れないようにする。
 */
export async function* predictStream(req: PredictRequest) {
  const token = await getIdToken();

  const res = await fetch(`${import.meta.env.VITE_APP_API_ENDPOINT}/predict/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(req),
  });

  if (!res.ok || !res.body) {
    throw new Error(`ストリーム取得に失敗しました (status: ${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex = buffer.indexOf('\n');
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      if (line.trim().length > 0) {
        yield line;
      }
      newlineIndex = buffer.indexOf('\n');
    }
  }

  if (buffer.trim().length > 0) {
    yield buffer;
  }
}

export const predictTitle = async (req: PredictTitleRequest) => {
  const res = await genUApi.post<PredictTitleResponse>('predict/title', req);
  return res.data;
};
