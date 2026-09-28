import type { DiagramType } from '@/features/generate-diagram/types';
import { genUApi } from '@/lib/fetcher';

export type SavedDiagramSummary = {
  diagramId: string;
  title: string;
  createdDate: string;
  updatedDate: string;
};

export type SavedDiagram = SavedDiagramSummary & {
  instruction: string;
  diagramType: DiagramType | '';
  mermaidSource: string;
  drawioXml: string;
};

export const listDiagrams = async () => {
  const res = await genUApi.get<{ diagrams: SavedDiagramSummary[] }>('diagrams');
  return res.data.diagrams;
};

export const getDiagram = async (diagramId: string) => {
  const res = await genUApi.get<{ diagram: SavedDiagram }>(`diagrams/${diagramId}`);
  return res.data.diagram;
};

export const createDiagram = async (body: {
  title: string;
  instruction?: string;
  diagramType?: DiagramType | '';
  mermaidSource?: string;
  drawioXml?: string;
}) => {
  const res = await genUApi.post<{ diagram: SavedDiagram }>('diagrams', body);
  return res.data.diagram;
};

export const updateDiagram = async (
  diagramId: string,
  body: {
    title?: string;
    instruction?: string;
    diagramType?: DiagramType | '';
    mermaidSource?: string;
    drawioXml?: string;
  },
) => {
  const res = await genUApi.put<{ diagram: SavedDiagram }>(`diagrams/${diagramId}`, body);
  return res.data.diagram;
};

export const deleteDiagram = async (diagramId: string) => {
  await genUApi.delete<void>(`diagrams/${diagramId}`);
};
