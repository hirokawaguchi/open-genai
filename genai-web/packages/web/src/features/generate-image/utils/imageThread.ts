import type { ShownMessage } from 'genai-web';
import { parseImageResultExtraData } from './imageResultExtraData';

export type ImageTurn = {
  key: string;
  prompt: string;
  sourceUrl?: string;
  images: { src: string }[];
};

const imageSrc = (fileUrl: string) => fileUrl;

export const buildImageTurns = (messages: ShownMessage[]): ImageTurn[] => {
  const turns: ImageTurn[] = [];
  for (const message of messages) {
    if (message.role === 'user') {
      turns.push({
        key: message.messageId || `user-${turns.length}`,
        prompt: message.content,
        images: [],
      });
      continue;
    }
    if (message.role !== 'assistant') {
      continue;
    }
    const result = parseImageResultExtraData(message.extraData);
    if (!result?.images?.length) {
      continue;
    }
    const images = result.images
      .filter((image) => image.fileUrl)
      .map((image) => ({ src: imageSrc(image.fileUrl) }));
    const last = turns[turns.length - 1];
    if (last && last.images.length === 0) {
      last.images = images;
      last.sourceUrl = result.sourceImage?.fileUrl;
      if (!last.prompt) {
        last.prompt = result.prompt;
      }
      continue;
    }
    turns.push({
      key: message.messageId || `image-${turns.length}`,
      prompt: result.prompt,
      sourceUrl: result.sourceImage?.fileUrl,
      images,
    });
  }
  return turns.filter((turn) => turn.prompt || turn.images.length > 0);
};
