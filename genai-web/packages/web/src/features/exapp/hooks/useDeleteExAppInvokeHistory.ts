import { InvokeExAppHistory } from 'genai-web';
import { teamApi } from '@/lib/fetcher';

export const useDeleteExAppInvokeHistory = () => {
  const deleteHistory = async (history: InvokeExAppHistory) => {
    await teamApi.delete(
      `/teams/${history.teamId}/exapps/${history.exAppId}/history?createdDate=${history.createdDate}`,
    );
  };

  const deleteConversation = async (teamId: string, exAppId: string, sessionId: string) => {
    await teamApi.delete(`/teams/${teamId}/exapps/${exAppId}/history`, undefined, {
      params: { sessionId },
    });
  };

  return {
    deleteHistory,
    deleteConversation,
  };
};
