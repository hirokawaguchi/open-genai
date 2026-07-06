import { getPrompter } from '@/prompts';
import { useChat } from './useChat';
import { useUsecasePath } from './useUsecasePath';

export const usePrompter = () => {
  const { usecase, chatId } = useUsecasePath();
  const { getModelId } = useChat(usecase, chatId);
  const prompter = getPrompter(getModelId());

  return { prompter };
};
