const MERMAID_DIRECTIVE =
  /^(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|gitGraph|mindmap|timeline|block-beta|block|C4Context|sankey-beta|xychart-beta|architecture-beta|packet-beta)/i;

const stripMarkup = (text: string): string =>
  text.replace(/<\/?description>/gi, '').replace(/<\/?output>/gi, '').trim();

const pickMermaidBody = (text: string): string => {
  const cleaned = stripMarkup(text);
  if (!cleaned) {
    return '';
  }

  const lines = cleaned.split('\n');
  const startIdx = lines.findIndex((line) => MERMAID_DIRECTIVE.test(line.trim()));
  if (startIdx >= 0) {
    return lines.slice(startIdx).join('\n').trim();
  }

  return MERMAID_DIRECTIVE.test(lines[0]?.trim() ?? '') ? cleaned : '';
};

const listMermaidBlocks = (content: string): string[] => {
  if (!content.toLowerCase().includes('```mermaid')) {
    return [];
  }

  const blocks: string[] = [];
  for (const part of content.split(/```mermaid\s*/i).slice(1)) {
    const block = part.split('```')[0]?.trim();
    if (block) {
      blocks.push(block);
    }
  }
  return blocks;
};

// description 部分のみを抽出
export const extractDiagramSentence = (content: string): string => {
  if (content.toLowerCase().includes('<description>')) {
    return content
      .split(/<description>/i)[1]
      .split(/<\/description>/i)[0]
      .trim();
  }

  if (content.includes('ただいまアクセスが集中しているため時間をおいて試してみてください。')) {
    return 'ただいまアクセスが集中しているため時間をおいて試してみてください。';
  }

  return content;
};

// mermaid コードブロック部分のみを抽出
export const extractDiagramCode = (content: string): string => {
  for (const block of listMermaidBlocks(content)) {
    const code = pickMermaidBody(block);
    if (code) {
      return code;
    }
  }

  // フェンス無しで Mermaid 記法だけ返すモデル向けフォールバック
  return pickMermaidBody(content);
};
