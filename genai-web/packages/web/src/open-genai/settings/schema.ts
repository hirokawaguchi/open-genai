import { z } from 'zod';

export const profileSchema = z.object({
  lastName: z.string().trim().max(100, '姓は100文字以内で入力してください'),
  firstName: z.string().trim().max(100, '名は100文字以内で入力してください'),
});

export type ProfileSchema = z.infer<typeof profileSchema>;

export const passwordSchema = z
  .object({
    currentPassword: z.string().min(1, '現在のパスワードを入力してください'),
    newPassword: z.string().min(8, '新しいパスワードは8文字以上で入力してください'),
    confirmPassword: z.string().min(1, '確認用のパスワードを入力してください'),
  })
  .refine((v) => v.newPassword === v.confirmPassword, {
    path: ['confirmPassword'],
    message: '新しいパスワードが一致しません',
  });

export type PasswordSchema = z.infer<typeof passwordSchema>;
