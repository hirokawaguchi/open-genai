import type { PredictRequest } from 'genai-web';
import { MERMAID_DIAGRAM_TYPES } from '@/features/generate-diagram/constants';
import type { DiagramType, MermaidDiagramType } from '@/features/generate-diagram/types';
import {
  extractDiagramCode,
  normalizeDiagramCode,
} from '@/features/generate-diagram/utils/extractDiagram';
import { findModelByModelId } from '@/models';
import { getPrompter } from '@/prompts';

const validTypes = Object.keys(MERMAID_DIAGRAM_TYPES) as MermaidDiagramType[];

const extractDiagramType = (targetText: string): MermaidDiagramType => {
  const defaultType = validTypes[0];
  const match = targetText.match(/<output>(.*?)<\/output>/i);
  if (!match) return defaultType;
  const content = match[1].toLowerCase();
  if (validTypes.includes(content as MermaidDiagramType)) {
    return content as MermaidDiagramType;
  }
  const matchingType = validTypes.find((type) => content.includes(type) || type.includes(content));
  return matchingType || defaultType;
};

export const generateMermaidDraft = async (args: {
  content: string;
  type: DiagramType;
  modelId: string;
  predict: (req: PredictRequest) => Promise<string>;
}): Promise<string> => {
  const model = findModelByModelId(args.modelId);
  if (!model) {
    throw new Error('利用するモデルが見つかりません');
  }
  const prompter = getPrompter(args.modelId);
  let diagramType: MermaidDiagramType = args.type === 'AI' ? validTypes[0] : args.type;

  if (args.type === 'AI') {
    const decided = await args.predict({
      model,
      messages: [
        { role: 'system', content: prompter.diagramPrompt({ determineType: true }) },
        { role: 'user', content: `<content>${args.content}</content>` },
      ],
      id: '/diagram',
    });
    diagramType = extractDiagramType(decided);
  }

  const generated = await args.predict({
    model,
    messages: [
      {
        role: 'system',
        content: prompter.diagramPrompt({ determineType: false, diagramType }),
      },
      { role: 'user', content: args.content },
    ],
    id: '/diagram',
  });
  const code = normalizeDiagramCode(extractDiagramCode(generated));
  if (!code) {
    throw new Error('Mermaid の図を取得できませんでした。文章を変えて再度お試しください。');
  }
  return code;
};
