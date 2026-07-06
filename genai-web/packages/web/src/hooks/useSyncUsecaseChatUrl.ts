import { useEffect } from 'react';
import { useNavigate } from 'react-router';

/** 初回送信でチャットが作成されたら `/image/{id}` 等へ URL を同期する */
export const useSyncUsecaseChatUrl = (
  usecase: string,
  urlChatId: string | undefined,
  sessionChatId: string | undefined,
) => {
  const navigate = useNavigate();

  useEffect(() => {
    if (!urlChatId && sessionChatId) {
      navigate(`${usecase}/${sessionChatId}`, { replace: true });
    }
  }, [urlChatId, sessionChatId, usecase, navigate]);
};
