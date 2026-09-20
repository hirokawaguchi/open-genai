import { useMyTenants } from './useTenants';

/**
 * どの棟にも所属していない利用者への案内。
 * 真のマルチテナント運用では棟の指定が先。所属が無いとカタログ・履歴は空になる。
 */
export const NoTenantBanner = () => {
  const { tenants, isSystemAdmin, isLoading } = useMyTenants();

  if (isLoading || isSystemAdmin || tenants.length > 0) {
    return null;
  }

  return (
    <div
      className='border-b border-error-2 bg-red-50 px-6 py-3 text-dns-14N-130 text-error-1 lg:px-8'
      role='alert'
    >
      所属する棟がありません。ご利用には棟への登録が必要です。管理者に連絡してください。
    </div>
  );
};
