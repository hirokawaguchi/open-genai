import { z } from 'zod';

export const teamMemberCreateSchema = z.object({
  email: z.email({ message: 'メールアドレスの形式が正しくありません。' }),
  isAdmin: z.boolean(),
  isPrimary: z.boolean(),
});

export type TeamMemberCreateSchema = z.infer<typeof teamMemberCreateSchema>;
