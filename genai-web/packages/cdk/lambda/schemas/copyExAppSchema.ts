import { z } from 'zod';
import { parseHttpsUrl } from '../utils/exAppUrlSecurity';

const isValidJson = (value: string): boolean => {
  try {
    JSON.parse(value);
    return true;
  } catch {
    return false;
  }
};

const isValidHttpsUrl = (value: string): boolean => {
  try {
    parseHttpsUrl(value);
    return true;
  } catch {
    return false;
  }
};

export const copyExAppSchema = z.object({
  exAppName: z
    .string({ error: 'アプリ名の形式が不正です。' })
    .trim()
    .min(1, 'アプリ名は必須です。'),
  endpoint: z
    .string({ error: 'APIエンドポイントの形式が不正です。' })
    .refine(isValidHttpsUrl, 'APIエンドポイントの形式が不正です。')
    .optional(),
  config: z
    .string({ error: 'コンフィグの形式が不正です。' })
    .refine((val) => !val || isValidJson(val), 'コンフィグのJSON形式が不正です。')
    .optional(),
  // 対話型(Dify チャット)や入力不要のアプリでは空で構わない
  placeholder: z
    .string({ error: 'APIリクエストの形式が不正です。' })
    .refine((val) => !val.trim() || isValidJson(val), 'APIリクエストのJSON形式が不正です。')
    .optional()
    .default(''),
  systemPrompt: z.string({ error: 'システムプロンプトの形式が不正です。' }).optional(),
  systemPromptKeyName: z.string({ error: 'システムプロンプトキー名の形式が不正です。' }).optional(),
  description: z.string({ error: '概要の形式が不正です。' }).trim().min(1, '概要は必須です。'),
  howToUse: z.string({ error: '使い方の形式が不正です。' }).trim().min(1, '使い方は必須です。'),
  apiKey: z
    .string({ error: 'APIキーの形式が不正です。' })
    .trim()
    .min(1, 'APIキーの形式が不正です。')
    .optional(),
  copyable: z.boolean({ error: 'コピー可能フラグの形式が不正です。' }).optional().default(false),
  status: z
    .string({ error: 'ステータスの形式が不正です。' })
    .trim()
    .min(1, 'ステータスは必須です。')
    .refine(
      (val) => val === 'draft' || val === 'published',
      'ステータスはdraftかpublishedのいずれかである必要があります。',
    ),
});

export type CopyExAppInput = z.infer<typeof copyExAppSchema>;
