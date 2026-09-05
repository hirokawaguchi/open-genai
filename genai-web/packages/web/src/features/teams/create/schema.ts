import { z } from 'zod';

export const teamCreateSchema = z.object({
  name: z
    .string()
    .min(1, { message: 'チーム名を入力してください' })
    .max(100, { message: 'チーム名は100文字以内で入力してください' }),
  email: z.email({ message: 'メールアドレスの形式が正しくありません。' }),
  parentTeamId: z.string().optional(),
});

export type TeamCreateSchema = z.infer<typeof teamCreateSchema>;
