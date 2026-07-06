import type { PredictRequest } from 'genai-web';
import { MERMAID_DIAGRAM_TYPES } from '@/features/generate-diagram/constants';
import { useDiagramStore } from '@/features/generate-diagram/stores/useDiagramStore';
import type { MermaidDiagramType } from '@/features/generate-diagram/types';
import { useChat } from '@/hooks/useChat';
import { useChatApi } from '@/hooks/useChatApi';
import { findModelByModelId } from '@/models';
import { getPrompter } from '@/prompts';

const validTypes = Object.keys(MERMAID_DIAGRAM_TYPES) as MermaidDiagramType[];

export const useDiagram = (usecase: string, chatId?: string) => {
  const { diagramType, setDiagramType } = useDiagramStore();

  const {
    loading,
    getModelId,
    setModelId,
    setLoading,
    clear,
    updateSystemContext,
    messages,
    isEmpty,
    postChat,
  } = useChat(usecase, chatId);

  const modelId = getModelId();
  const model = findModelByModelId(modelId);
  const prompter = getPrompter(modelId);
  const { predict } = useChatApi();

  // ダイアグラムタイプの抽出
  const extractDiagramType = (targetText: string): MermaidDiagramType => {
    const defaultType = validTypes[0];
    const match = targetText.match(/<output>(.*?)<\/output>/i);
    if (!match) return defaultType;

    const content = match[1].toLowerCase();

    // 完全一致チェック
    if (validTypes.includes(content as MermaidDiagramType)) {
      return content as MermaidDiagramType;
    }

    // 部分一致チェック
    const matchingType = validTypes.find(
      (type) => content.includes(type) || type.includes(content),
    );
    return matchingType || defaultType;
  };

  const selectDiagram = async (content: string) => {
    try {
      if (!model) {
        throw new Error('Model not found');
      }

      const payload: PredictRequest = {
        model: model,
        messages: [
          {
            role: 'system',
            content: prompter.diagramPrompt({ determineType: true }),
          },
          {
            role: 'user',
            content: `<content>${content}</content>`,
          },
        ],
        id: usecase,
      };

      const res = await predict(payload);
      const type = extractDiagramType(res);
      setDiagramType(type);
      return type;
    } catch (error: unknown) {
      throw `${error}`;
    }
  };

  const postDiagram = async (content: string, type: MermaidDiagramType | 'AI') => {
    setDiagramType('');
    try {
      let chosenType = type;

      // 1. AIチョイス時はダイアグラムタイプを決定
      if (type === 'AI') {
        chosenType = await selectDiagram(content);
      } else {
        setDiagramType(type);
      }

      // 2. メッセージの過去の履歴をクリア
      clear();

      // 3. 決定したダイアグラムタイプのシステムプロンプトを設定
      const systemPrompt = prompter.diagramPrompt({
        determineType: false,
        diagramType: chosenType,
      });
      updateSystemContext(systemPrompt);

      // 4. ダイアグラム生成
      await postChat(content, { ignoreHistory: true });
    } catch (error: unknown) {
      setLoading(false);
      throw `${error}`;
    }
  };

  return {
    loading,
    getModelId,
    setModelId,
    setLoading,
    clear,
    messages,
    isEmpty,
    postDiagram,
    diagramType,
  };
};
