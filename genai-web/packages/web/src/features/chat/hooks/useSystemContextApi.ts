import {
  CreateSystemContextRequest,
  SystemContext,
  UpdateSystemContextTitleResponse,
} from 'genai-web';
import useSWR from 'swr';
import { genUApi, genUApiFetcher } from '@/lib/fetcher';
import { decomposeId } from '@/utils/decomposeId';

export type MyTeam = { teamId: string; teamName: string };

export type SystemContextShareOptions = {
  isPublic?: boolean;
  sharedTeams?: string[];
};

export const useSystemContextApi = () => {
  return {
    createSystemContext: async (
      systemContextTitle: string,
      systemContext: string,
      options?: SystemContextShareOptions,
    ) => {
      const res = await genUApi.post<CreateSystemContextRequest>('/systemcontexts', {
        systemContextTitle: systemContextTitle,
        systemContext: systemContext,
        isPublic: options?.isPublic ?? false,
        sharedTeams: options?.sharedTeams ?? [],
      });
      return res.data;
    },
    listMyTeams: async (): Promise<MyTeam[]> => {
      const res = await genUApi.get<{ teams: MyTeam[] }>('/me/teams');
      return res.data?.teams ?? [];
    },
    deleteSystemContext: async (_systemContextId: string) => {
      const systemContextId = decomposeId(_systemContextId);
      return genUApi.delete<void>(`/systemcontexts/${systemContextId}`);
    },
    updateSystemContextTitle: async (_systemContextId: string, title: string) => {
      const systemContextId = decomposeId(_systemContextId);
      const res = await genUApi.put<UpdateSystemContextTitleResponse>(
        `systemcontexts/${systemContextId}/title`,
        {
          title,
        },
      );
      return res.data;
    },
    listSystemContexts: () => {
      return useSWR<SystemContext[]>('/systemcontexts', genUApiFetcher);
    },
  };
};
