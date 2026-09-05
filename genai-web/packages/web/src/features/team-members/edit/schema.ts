import { z } from 'zod';

export const teamMemberUpdateSchema = z.object({
  email: z.email({ message: 'メールアドレスの形式が正しくありません。' }),
  isAdmin: z.boolean(),
  isPrimary: z.boolean(),
});

export type TeamMemberUpdateSchema = z.infer<typeof teamMemberUpdateSchema>;
